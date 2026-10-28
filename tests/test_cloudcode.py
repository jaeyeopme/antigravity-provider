import unittest

from antigravity_provider.cloudcode import (
    PROJECT_ONBOARD_INTERVAL_SECONDS,
    load_or_onboard_project,
    read_default_tier,
    read_project_id,
)
from antigravity_provider.errors import AntigravityError


class CloudCodeTests(unittest.TestCase):
    def test_project_id_string_or_object(self):
        self.assertEqual(read_project_id("p1"), "p1")
        self.assertEqual(read_project_id({"id": "p2"}), "p2")
        self.assertIsNone(read_project_id({}))

    def test_default_tier(self):
        self.assertEqual(read_default_tier([{"id": "free"}, {"id": "pro", "isDefault": True}]), "pro")
        self.assertEqual(read_default_tier([]), "legacy-tier")

    def test_onboards_when_no_project(self):
        calls = []
        def fake_post(url, body, headers):
            calls.append((url, body))
            if url.endswith("loadCodeAssist"):
                return {"allowedTiers": [{"id": "pro", "isDefault": True}]}
            return {"done": True, "response": {"cloudaicompanionProject": {"id": "p3"}}}
        self.assertEqual(load_or_onboard_project("tok", post_json=fake_post, sleep=lambda _: None), "p3")
        self.assertTrue(calls[1][0].endswith("onboardUser"))

    def test_onboarding_waits_for_the_operation_to_finish(self):
        answers = iter([{}, {"done": False}, {"done": False}, {"done": True, "response": {"cloudaicompanionProject": "p4"}}])
        sleeps = []
        project = load_or_onboard_project("tok", post_json=lambda url, body, headers: next(answers), sleep=sleeps.append)
        self.assertEqual(project, "p4")
        self.assertEqual(sleeps, [PROJECT_ONBOARD_INTERVAL_SECONDS] * 2)

    def test_onboarding_that_never_finishes_is_an_error(self):
        with self.assertRaisesRegex(AntigravityError, "project id"):
            load_or_onboard_project("tok", post_json=lambda url, body, headers: {"done": False}, sleep=lambda _: None)


if __name__ == "__main__":
    unittest.main()
