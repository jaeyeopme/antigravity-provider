import unittest

from antigravity_provider.errors import AntigravityError
from antigravity_provider.response import collect_response, to_openai_completion, to_openai_stream_chunks


def candidate(parts, finish="STOP"):
    return {"candidates": [{"content": {"parts": parts}, "finishReason": finish}]}


class CompletionTests(unittest.TestCase):
    def test_text_candidate_to_completion(self):
        completion = to_openai_completion("google-antigravity/gemini-3.1-pro", candidate([{"text": "pong"}]))
        self.assertEqual(completion["object"], "chat.completion")
        self.assertEqual(completion["choices"][0]["message"]["content"], "pong")
        self.assertEqual(completion["choices"][0]["finish_reason"], "stop")

    def test_function_call_part_to_openai_tool_call(self):
        out = to_openai_completion("gemini-3.1-pro", candidate([{"functionCall": {"name": "get_time", "args": {}}}]))
        self.assertEqual(out["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "get_time")
        self.assertEqual(out["choices"][0]["finish_reason"], "tool_calls")

    def test_identical_tool_calls_receive_distinct_ids(self):
        part = {"functionCall": {"name": "get_time", "args": {}}}
        calls = to_openai_completion("gemini-3.1-pro", candidate([part, part]))["choices"][0]["message"]["tool_calls"]
        self.assertNotEqual(calls[0]["id"], calls[1]["id"])

    def test_identical_tool_calls_in_later_turns_receive_distinct_ids(self):
        upstream = candidate([{"functionCall": {"name": "read_file", "args": {"path": "a.txt"}}}])
        first = to_openai_completion("gemini-3.1-pro", upstream)["choices"][0]["message"]["tool_calls"][0]["id"]
        second = to_openai_completion("gemini-3.1-pro", upstream)["choices"][0]["message"]["tool_calls"][0]["id"]
        self.assertNotEqual(first, second)

    def test_upstream_tool_call_id_is_kept(self):
        out = to_openai_completion("gemini-3.1-pro", candidate([{"functionCall": {"id": "up-1", "name": "f", "args": {}}}]))
        self.assertEqual(out["choices"][0]["message"]["tool_calls"][0]["id"], "up-1")

    def test_thought_signature_is_exposed_for_hermes_replay(self):
        part = {"functionCall": {"name": "f", "args": {}}, "thoughtSignature": "SIG"}
        call = to_openai_completion("gemini-3.1-pro", candidate([part]))["choices"][0]["message"]["tool_calls"][0]
        self.assertEqual(call["extra_content"], {"google": {"thought_signature": "SIG"}})

    def test_malformed_function_call_without_output_is_a_retryable_error(self):
        with self.assertRaises(AntigravityError) as raised:
            to_openai_completion("gemini-3.1-pro", candidate([], "MALFORMED_FUNCTION_CALL"))
        self.assertEqual(raised.exception.status, 502)
        self.assertIn("MALFORMED_FUNCTION_CALL", raised.exception.message)

    def test_safety_finish_maps_to_content_filter(self):
        out = to_openai_completion("gemini-3.1-pro", candidate([{"text": "partial"}], "SAFETY"))
        self.assertEqual(out["choices"][0]["finish_reason"], "content_filter")


class StreamTests(unittest.TestCase):
    def test_stream_events_are_emitted_as_reasoning_text_tool_and_finish_chunks(self):
        events = [
            {"candidates": [{"content": {"parts": [{"text": "think", "thought": True}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "answer"}]}}]},
            {
                **candidate([{"functionCall": {"name": "lookup", "args": {"q": "x"}}, "thoughtSignature": "SIG"}]),
                "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 3, "totalTokenCount": 5},
            },
        ]
        chunks = list(to_openai_stream_chunks("gemini-3.1-pro", events))
        self.assertEqual(chunks[0]["choices"][0]["delta"]["reasoning_content"], "think")
        self.assertEqual(chunks[1]["choices"][0]["delta"]["content"], "answer")
        tool_call = chunks[2]["choices"][0]["delta"]["tool_calls"][0]
        self.assertEqual(tool_call["function"]["name"], "lookup")
        self.assertEqual(tool_call["index"], 0)
        self.assertEqual(tool_call["extra_content"], {"google": {"thought_signature": "SIG"}})
        self.assertEqual(chunks[-1]["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(chunks[-1]["usage"]["total_tokens"], 5)

    def test_stream_malformed_function_call_without_output_raises(self):
        events = [
            {"candidates": [{"content": {"parts": [{"text": "plan", "thought": True}]}}]},
            candidate([], "MALFORMED_FUNCTION_CALL"),
        ]
        with self.assertRaisesRegex(AntigravityError, "MALFORMED_FUNCTION_CALL"):
            list(to_openai_stream_chunks("gemini-3.1-pro", events))

    def test_stream_malformed_function_call_after_text_finishes_normally(self):
        events = [candidate([{"text": "partial"}], None), candidate([], "MALFORMED_FUNCTION_CALL")]
        chunks = list(to_openai_stream_chunks("gemini-3.1-pro", events))
        self.assertEqual(chunks[-1]["choices"][0]["finish_reason"], "stop")


class CollectTests(unittest.TestCase):
    def test_thought_only_response_is_kept(self):
        out = collect_response([candidate([{"text": "reasoning", "thought": True}])])
        self.assertTrue(out["candidates"][0]["content"]["parts"][0]["thought"])

    def test_chunks_are_concatenated_with_last_finish_and_usage(self):
        out = collect_response([
            {"candidates": [{"content": {"parts": [{"text": "a"}]}}], "responseId": "r1"},
            {**candidate([{"text": "b"}], "MAX_TOKENS"), "usageMetadata": {"totalTokenCount": 3}},
        ])
        self.assertEqual([p["text"] for p in out["candidates"][0]["content"]["parts"]], ["a", "b"])
        self.assertEqual(out["candidates"][0]["finishReason"], "MAX_TOKENS")
        self.assertEqual(out["usageMetadata"]["totalTokenCount"], 3)
        self.assertEqual(out["responseId"], "r1")

    def test_empty_stream_is_an_error(self):
        with self.assertRaisesRegex(AntigravityError, "empty stream"):
            collect_response(iter(()))


if __name__ == "__main__":
    unittest.main()
