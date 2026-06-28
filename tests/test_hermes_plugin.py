import tempfile
import unittest
from pathlib import Path

import antigravity_provider.hermes_plugin as plugin
from antigravity_provider.runtime import ensure_provider_profile_files, openai_completion_object


class FakeCtx:
    def __init__(self):
        self.cli = {}
        self.middleware = []

    def register_cli_command(self, **kwargs):
        self.cli[kwargs["name"]] = kwargs

    def register_middleware(self, kind, callback):
        self.middleware.append((kind, callback))


class HermesPluginTests(unittest.TestCase):
    def test_register_adds_cli_and_llm_middleware(self):
        ctx = FakeCtx()
        plugin.register(ctx)
        self.assertIn("agy", ctx.cli)
        self.assertEqual(ctx.middleware[0][0], "llm_execution")

    def test_middleware_passthrough_for_other_provider(self):
        seen = []
        out = plugin.antigravity_llm_execution(provider="openai", request={"model": "x"}, next_call=lambda req: seen.append(req) or "ok")
        self.assertEqual(out, "ok")
        self.assertEqual(seen, [{"model": "x"}])

    def test_middleware_returns_openai_compatible_object(self):
        old = plugin.generate_chat_completion
        try:
            plugin.generate_chat_completion = lambda request: {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "model": request["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
            out = plugin.antigravity_llm_execution(
                provider="antigravity",
                request={"model": "google-antigravity/gemini-3.1-pro", "messages": [{"role": "user", "content": "ping"}]},
                next_call=lambda req: self.fail("should not call downstream"),
            )
            self.assertEqual(out.choices[0].message.content, "pong")
            self.assertIsNone(out.choices[0].message.tool_calls)
        finally:
            plugin.generate_chat_completion = old

    def test_middleware_reports_antigravity_error_without_downstream_fallback(self):
        old = plugin.generate_chat_completion
        try:
            plugin.generate_chat_completion = lambda request: (_ for _ in ()).throw(
                RuntimeError("OAuth token request failed: Could not determine client ID from request.")
            )
            out = plugin.antigravity_llm_execution(
                provider="antigravity",
                request={"model": "google-antigravity/gemini-3.1-pro", "messages": []},
                next_call=lambda req: self.fail("should not call downstream"),
            )
            self.assertIn("Antigravity request failed: OAuth token request failed", out.choices[0].message.content)
            self.assertIn("restart Hermes/Desktop", out.choices[0].message.content)
        finally:
            plugin.generate_chat_completion = old

    def test_openai_completion_object_defaults_tool_calls(self):
        obj = openai_completion_object({
            "choices": [{"message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
        })
        self.assertIsNone(obj.choices[0].message.tool_calls)

    def test_ensure_provider_profile_files(self):
        with tempfile.TemporaryDirectory() as td:
            path = ensure_provider_profile_files(Path(td))
            self.assertTrue((path / "__init__.py").exists())
            self.assertTrue((path / "plugin.yaml").exists())
            self.assertIn("register_provider_profile", (path / "__init__.py").read_text())


if __name__ == "__main__":
    unittest.main()
