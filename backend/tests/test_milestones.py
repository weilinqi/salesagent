"""里程碑节点测试：检测、完成、撤销、世界状态渲染。

全部纯规则，不访问网络与数据库。
"""

import os
import unittest

os.environ.setdefault("SECRET_KEY", "milestone-test-secret-long-enough-for-tests")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")

from app.services.conversation import deal_state, milestones


class DetectTests(unittest.TestCase):
    def test_agreement_to_trial_is_detected(self):
        flags = {}
        changed = milestones.detect(flags, "那约个试听吧", round_number=3)
        self.assertEqual(changed, ["trial"])
        self.assertEqual(milestones.get_status(flags, "trial"), milestones.STATUS_AGREED)

    def test_asking_about_trial_is_not_agreement(self):
        flags = {}
        self.assertEqual(milestones.detect(flags, "试听课怎么安排？", round_number=2), [])
        self.assertEqual(milestones.get_status(flags, "trial"), milestones.STATUS_PENDING)

    def test_assessment_agreement_is_detected(self):
        flags = {}
        self.assertEqual(milestones.detect(flags, "行，那就做个测评吧", round_number=5), ["assessment"])

    def test_completed_milestone_is_not_redetected(self):
        flags = {}
        milestones.detect(flags, "那约个试听吧", round_number=3)
        milestones.complete(flags, "trial", "satisfied")
        self.assertEqual(milestones.detect(flags, "再约一次试听吧", round_number=9), [])


class CompleteTests(unittest.TestCase):
    def test_complete_sets_result(self):
        flags = {}
        milestones.detect(flags, "那约个试听吧", round_number=3)
        milestones.complete(flags, "trial", "satisfied")
        self.assertEqual(milestones.get_status(flags, "trial"), milestones.STATUS_COMPLETED)
        self.assertEqual(milestones.get_result(flags, "trial"), "satisfied")

    def test_invalid_outcome_raises(self):
        with self.assertRaises(ValueError):
            milestones.complete({}, "trial", "unknown")

    def test_invalid_milestone_raises(self):
        with self.assertRaises(ValueError):
            milestones.complete({}, "nope", "satisfied")

    def test_reopen_returns_to_agreed(self):
        flags = {}
        milestones.detect(flags, "那约个试听吧", round_number=3)
        milestones.complete(flags, "trial", "satisfied")
        milestones.reopen(flags, "trial")
        self.assertEqual(milestones.get_status(flags, "trial"), milestones.STATUS_AGREED)
        self.assertIsNone(milestones.get_result(flags, "trial"))


class PendingEventTests(unittest.TestCase):
    def test_no_pending_event_by_default(self):
        self.assertIsNone(milestones.pending_event({}))

    def test_agreed_milestone_becomes_card(self):
        flags = {}
        milestones.detect(flags, "那约个试听吧", round_number=3)
        event = milestones.pending_event(flags)
        self.assertIsNotNone(event)
        self.assertEqual(event["id"], "trial")
        self.assertEqual(len(event["outcomes"]), 3)
        self.assertTrue(event["title"])

    def test_completed_milestone_is_not_pending(self):
        flags = {}
        milestones.detect(flags, "那约个试听吧", round_number=3)
        milestones.complete(flags, "trial", "neutral")
        self.assertIsNone(milestones.pending_event(flags))


class WorldStateTests(unittest.TestCase):
    def test_empty_state_renders_nothing(self):
        self.assertEqual(milestones.render_world_state({}), "")

    def test_completed_trial_changes_stance(self):
        flags = {}
        milestones.detect(flags, "那约个试听吧", round_number=3)
        milestones.complete(flags, "trial", "satisfied")
        text = milestones.render_world_state(flags)
        self.assertIn("已经发生的事", text)
        self.assertIn("很满意", text)
        self.assertIn("不要反问", text)

    def test_agreed_trial_states_it_has_not_happened(self):
        flags = {}
        milestones.detect(flags, "那约个试听吧", round_number=3)
        text = milestones.render_world_state(flags)
        self.assertIn("还没发生", text)
        self.assertIn("不能编造", text)

    def test_system_notice_contains_label(self):
        notice = milestones.render_system_notice("trial", "satisfied")
        self.assertIn("试听", notice)
        self.assertIn("满意", notice)


class PayloadIntegrationTests(unittest.TestCase):
    def test_deal_payload_carries_pending_event(self):
        state = deal_state.new_state("k12_junior")
        flags = {}
        milestones.detect(flags, "那约个试听吧", round_number=3)
        state["flags"] = flags
        payload = deal_state.build_progress_payload(state)
        self.assertIsNotNone(payload["pending_event"])
        self.assertEqual(payload["pending_event"]["id"], "trial")
        self.assertEqual(payload["milestones"]["trial"]["status"], "agreed")

    def test_payload_hides_pending_event_after_completion(self):
        state = deal_state.new_state("k12_junior")
        flags = {}
        milestones.detect(flags, "那约个试听吧", round_number=3)
        milestones.complete(flags, "trial", "satisfied")
        state["flags"] = flags
        payload = deal_state.build_progress_payload(state)
        self.assertIsNone(payload["pending_event"])
        self.assertEqual(payload["milestones"]["trial"]["result"], "satisfied")


if __name__ == "__main__":
    unittest.main()
