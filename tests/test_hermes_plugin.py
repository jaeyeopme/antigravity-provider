import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import antigravity_provider.hermes_plugin as plugin
import antigravity_provider.runtime as runtime
from antigravity_provider.runtime import HermesAntigravityClient, ensure_provider_profile_files, openai_completion_object


class FakeCtx:
    def __init__(self):
        self.cli = {}
        self.middleware = []

    def register_cli_command(self, **kwargs):
        self.cli[kwargs["name"]] = kwargs

    def register_middleware(self, kind, callback):
        self.middleware.append((kind, callback))


class HermesPluginTests(unittest.TestCase):
    def test_register_adds_cli_and_session_request_middleware(self):
        ctx = FakeCtx()
        plugin.register(ctx)
        self.assertIn("agy", ctx.cli)
        self.assertEqual(ctx.middleware[0][0], "llm_request")

    def test_request_middleware_passthrough_for_other_provider(self):
        request = {"model": "x"}
        out = plugin.antigravity_llm_request(provider="openai", request=request, session_id="s")
        self.assertEqual(out, {"request": request})

    def test_request_middleware_injects_real_session_id(self):
        out = plugin.antigravity_llm_request(
            provider="antigravity",
            request={"model": "gemini-3.1-pro"},
            session_id="hermes-session",
        )
        self.assertEqual(out["request"]["_antigravity_session_id"], "hermes-session")

    def test_custom_client_returns_openai_compatible_object(self):
        old = runtime.generate_chat_completion
        try:
            runtime.generate_chat_completion = lambda request, session_id=None: {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "model": request["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
            out = HermesAntigravityClient().chat.completions.create(
                model="google-antigravity/gemini-3.1-pro",
                messages=[{"role": "user", "content": "ping"}],
                _antigravity_session_id="hermes-session",
            )
            self.assertEqual(out.choices[0].message.content, "pong")
            self.assertIsNone(out.choices[0].message.tool_calls)
        finally:
            runtime.generate_chat_completion = old

    def test_custom_client_supports_async_completion_and_streaming(self):
        completion = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": "google-antigravity/gemini-3.1-pro",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        chunk = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="pong"))])

        async def exercise():
            client = HermesAntigravityClient()
            with (
                patch.object(runtime, "generate_chat_completion", return_value=completion),
                patch.object(runtime, "stream_chat_completion", return_value=iter([chunk])),
            ):
                sync_response = client.chat.completions.create(
                    model=completion["model"],
                    messages=[{"role": "user", "content": "ping"}],
                )
                self.assertEqual(sync_response.choices[0].message.content, "pong")
                response = await client.chat.completions.create(
                    model=completion["model"],
                    messages=[{"role": "user", "content": "ping"}],
                )
                stream = await client.chat.completions.create(
                    model=completion["model"],
                    messages=[{"role": "user", "content": "ping"}],
                    stream=True,
                )
                chunks = [value async for value in stream]
            self.assertEqual(response.choices[0].message.content, "pong")
            self.assertEqual(chunks[0].choices[0].delta.content, "pong")
            self.assertTrue(client.HERMES_SKIP_ASYNC_WRAP)

        asyncio.run(exercise())

    def test_custom_client_propagates_provider_errors(self):
        old = runtime.generate_chat_completion
        try:
            runtime.generate_chat_completion = lambda request, session_id=None: (_ for _ in ()).throw(
                RuntimeError("provider down")
            )
            with self.assertRaisesRegex(RuntimeError, "provider down"):
                HermesAntigravityClient().chat.completions.create(
                    model="gemini-3.1-pro",
                    messages=[],
                )
        finally:
            runtime.generate_chat_completion = old

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
