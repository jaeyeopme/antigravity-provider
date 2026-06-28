import unittest

from antigravity_provider.cloudcode import load_or_onboard_project, read_default_tier, read_project_id


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


if __name__ == "__main__":
    unittest.main()
