import asyncio
import threading
import unittest

from antigravity_provider.errors import AntigravityError
from antigravity_provider.hermes_client import ChunkStream, HermesAntigravityClient, openai_completion_object

COMPLETION = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "model": "google-antigravity/gemini-3.1-pro",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}
CHUNK = {"choices": [{"delta": {"content": "pong"}}]}


class FakeService:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def complete(self, payload, *, session_id=None):
        self.calls.append(("complete", payload, session_id))
        if self.error:
            raise self.error
        return COMPLETION

    def stream(self, payload, *, session_id=None):
        self.calls.append(("stream", payload, session_id))
        return iter([CHUNK])


def create(client, **kwargs):
    return client.chat.completions.create(
        model="google-antigravity/gemini-3.1-pro", messages=[{"role": "user", "content": "ping"}], **kwargs
    )


class HermesClientTests(unittest.TestCase):
    def test_returns_openai_compatible_object_and_passes_session(self):
        service = FakeService()
        out = create(HermesAntigravityClient(service=service), _antigravity_session_id="hermes-session")
        self.assertEqual(out.choices[0].message.content, "pong")
        self.assertIsNone(out.choices[0].message.tool_calls)
        self.assertEqual(service.calls[0][2], "hermes-session")
        self.assertNotIn("_antigravity_session_id", service.calls[0][1])

    def test_async_completion_and_streaming(self):
        async def exercise():
            client = HermesAntigravityClient(service=FakeService())
            sync_style = create(client)  # sync caller on the loop thread
            self.assertEqual(sync_style.choices[0].message.content, "pong")
            response = await create(client)
            stream = await create(client, stream=True)
            chunks = [value async for value in stream]
            return response, chunks

        response, chunks = asyncio.run(exercise())
        self.assertEqual(response.choices[0].message.content, "pong")
        self.assertEqual(chunks[0].choices[0].delta.content, "pong")

    def test_deferred_completion_runs_the_request_once(self):
        async def exercise():
            service = FakeService()
            result = create(HermesAntigravityClient(service=service))
            result.choices  # attribute access on the loop thread
            await result
            result.usage
            return service.calls

        self.assertEqual(len(asyncio.run(exercise())), 1)

    def test_sync_streaming(self):
        stream = create(HermesAntigravityClient(service=FakeService()), stream=True)
        self.assertEqual([c.choices[0].delta.content for c in stream], ["pong"])

    def test_propagates_provider_errors(self):
        client = HermesAntigravityClient(service=FakeService(error=AntigravityError("provider down", status=503)))
        with self.assertRaises(AntigravityError) as raised:
            create(client)
        self.assertEqual(raised.exception.status_code, 503)

    def test_tool_call_extra_content_stays_a_dict_for_hermes(self):
        extra = {"google": {"thought_signature": "SIG"}}
        obj = openai_completion_object({"choices": [{"message": {"tool_calls": [{"id": "c", "extra_content": extra}]}}]})
        self.assertEqual(obj.choices[0].message.tool_calls[0].extra_content, extra)

    def test_openai_completion_object_defaults_tool_calls(self):
        obj = openai_completion_object({"choices": [{"message": {"role": "assistant", "content": "pong"}}]})
        self.assertIsNone(obj.choices[0].message.tool_calls)


def slow_chunks(finalized, reading, release):
    try:
        yield CHUNK
        reading.set()  # a reader is now inside the generator
        release.wait(5)  # upstream is slow to send the next chunk
        yield CHUNK
        yield CHUNK
    finally:
        finalized.set()


def events():
    return threading.Event(), threading.Event(), threading.Event()


class ChunkStreamCloseTests(unittest.TestCase):
    def test_close_from_another_thread_during_read(self):
        finalized, reading, release = events()
        stream = ChunkStream(slow_chunks(finalized, reading, release))
        next(stream)
        reader = threading.Thread(target=lambda: next(stream, None))
        reader.start()
        self.assertTrue(reading.wait(5))
        stream.close()  # Hermes interrupt path; must not raise while the reader is inside the generator
        release.set()
        reader.join(5)
        self.assertTrue(finalized.wait(5))
        self.assertIsNone(next(stream, None))

    def test_async_cancel_then_aclose(self):
        finalized, reading, release = events()

        async def exercise():
            stream = ChunkStream(slow_chunks(finalized, reading, release))
            await stream.__anext__()
            pending = asyncio.ensure_future(stream.__anext__())
            await asyncio.to_thread(reading.wait, 5)
            pending.cancel()
            await stream.aclose()
            release.set()

        asyncio.run(exercise())
        self.assertTrue(finalized.wait(5))

    def test_close_when_idle_finalizes_immediately(self):
        finalized, reading, release = events()
        stream = ChunkStream(slow_chunks(finalized, reading, release))
        next(stream)
        stream.close()
        self.assertTrue(finalized.is_set())


if __name__ == "__main__":
    unittest.main()
