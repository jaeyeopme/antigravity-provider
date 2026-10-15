"""Drive a real Hermes agent through this plugin against a fake Antigravity backend.

Checks the parts unit tests cannot: Hermes builds our client through ProviderProfile.create_client,
streams through it, executes the tool call, and replays the tool call's thought signature on the
next turn. Run it with the Python that has Hermes installed:

    python scripts/e2e_hermes.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SIGNATURE = "E2E_THOUGHT_SIGNATURE"
SAFE_TOOLS = ("todo", "session_search", "skills_list")

os.environ["HERMES_HOME"] = tempfile.mkdtemp(prefix="antigravity-e2e-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

generate_requests: list[dict] = []


def sse(events: list[dict]) -> bytes:
    return b"".join(b"data: " + json.dumps({"response": event}).encode() + b"\n\n" for event in events)


class FakeAntigravity(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        return

    def _send(self, content_type: str, data: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "fetchAvailableModels" in self.path:
            models = {"gemini-3.1-pro-low": {"maxOutputTokens": 8192, "supportsThinking": True, "thinkingBudget": 1001}}
            self._send("application/json", json.dumps({"models": models}).encode())
            return
        if "streamGenerateContent" not in self.path:
            self.send_error(404)
            return
        generate_requests.append(body)
        request = body["request"]
        if any("functionResponse" in part for content in request["contents"] for part in content["parts"]):
            self._send("text/event-stream", sse([
                {"candidates": [{"content": {"role": "model", "parts": [{"text": "all done"}]}, "finishReason": "STOP"}]},
            ]))
            return
        names = [d["name"] for tool in request.get("tools", []) for d in tool["functionDeclarations"]]
        tool = next((name for name in SAFE_TOOLS if name in names), names[0])
        self._send("text/event-stream", sse([
            {"candidates": [{"content": {"role": "model", "parts": [{"text": "planning", "thought": True}]}}]},
            {"candidates": [{"content": {"role": "model", "parts": [
                {"functionCall": {"name": tool, "args": {}}, "thoughtSignature": SIGNATURE},
            ]}, "finishReason": "STOP"}]},
        ]))


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAntigravity)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"

    import antigravity_provider.client as client_module
    from antigravity_provider.credentials import CredentialStore, Credentials
    from antigravity_provider.hermes_provider import PROVIDER_BASE_URL, register_provider_profile

    client_module.ANTIGRAVITY_ENDPOINTS[:] = [url]
    CredentialStore.default().save(
        Credentials(access_token="tok", refresh_token="ref", project_id="proj", expires_at=time.time() + 3600)
    )
    if not register_provider_profile():
        print("FAIL: Hermes provider registry is not importable")
        return 1

    from run_agent import AIAgent

    agent = AIAgent(
        provider="antigravity", model="google-antigravity/gemini-3.1-pro", api_key="hermes-plugin", base_url=PROVIDER_BASE_URL,
        api_mode="chat_completions", quiet_mode=True, skip_memory=True, skip_context_files=True, max_iterations=4,
    )
    reply = agent.chat("please use a tool")
    replayed = [
        part for content in generate_requests[-1]["request"]["contents"]
        for part in content["parts"] if "functionCall" in part
    ]
    checks = {
        "assistant reply came back": reply == "all done",
        "tool round trip took two requests": len(generate_requests) == 2,
        "thought signature replayed": bool(replayed) and replayed[0].get("thoughtSignature") == SIGNATURE,
        "one Antigravity session": len({r["request"]["sessionId"] for r in generate_requests}) == 1,
    }
    for name, passed in checks.items():
        print(f"{'ok  ' if passed else 'FAIL'} {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
