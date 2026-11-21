"""对练推进模型的纯规则测试：覆盖率、缺口、阶段、结单判定。

这些用例不访问网络，也不依赖数据库，只验证 ``deal_state`` / ``deal_templates``
的规则行为，因此可以在 CI 里稳定运行。
"""

import os
import unittest

os.environ.setdefault("SECRET_KEY", "deal-state-test-secret-long-enough-for-tests")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")

from app.services.conversation import deal_state
from app.services.conversation.deal_templates import (
    REQUIRED,
    STAGE_ORDER,
    get_template,
    resolve_template_id,
    template_slots,
)


def fill(slots, **values):
    for key, value in values.items():
        slots[key] = {"value": value, "evidence": f"家长说：{value}", "round": 1, "revised": False}
    return slots


class TemplateTests(unittest.TestCase):
    def test_template_resolution_by_grade(self):
        self.assertEqual(resolve_template_id("孩子现在初二"), "k12_junior")
        self.assertEqual(resolve_template_id("小学三年级"), "k12_primary")
        self.assertEqual(resolve_template_id("高二了"), "k12_senior")
        self.assertEqual(resolve_template_id(""), "k12_junior")

    def test_each_template_has_required_slots(self):
        for template_id in ("k12_primary", "k12_junior", "k12_senior"):
            required = [slot for slot in template_slots(template_id) if slot["level"] == REQUIRED]
            self.assertGreaterEqual(len(required), 13, template_id)
            keys = {slot["key"] for slot in template_slots(template_id)}
            self.assertIn("student_grade", keys)
            self.assertIn("current_score", keys)

    def test_primary_has_its_own_slot(self):
        primary = {slot["key"] for slot in template_slots("k12_primary")}
        junior = {slot["key"] for slot in template_slots("k12_junior")}
        self.assertIn("homework_supervision", primary)
        self.assertNotIn("homework_supervision", junior)


class CoverageTests(unittest.TestCase):
    def test_empty_state_coverage_is_zero(self):
        coverage = deal_state.compute_coverage({}, "k12_junior")
        self.assertEqual(coverage["required_filled"], 0)
        self.assertEqual(coverage["percent"], 0)
        self.assertGreater(coverage["required_total"], 0)

    def test_recommended_slots_do_not_change_percent(self):
        slots = fill({}, parent_role="妈妈")
        coverage = deal_state.compute_coverage(slots, "k12_junior")
        self.assertEqual(coverage["percent"], 0)
        self.assertEqual(coverage["recommended_filled"], 1)

    def test_required_fill_increases_percent(self):
        slots = fill({}, student_grade="初二", student_school="某某中学", weak_subjects="数学")
        coverage = deal_state.compute_coverage(slots, "k12_junior")
        self.assertEqual(coverage["required_filled"], 3)
        self.assertGreater(coverage["percent"], 0)
        self.assertLess(coverage["percent"], 100)


class MergeTests(unittest.TestCase):
    def test_value_without_evidence_is_dropped(self):
        merged, changed = deal_state.merge_slots({}, {"student_grade": {"value": "初二"}}, 1)
        self.assertEqual(merged, {})
        self.assertEqual(changed, [])

    def test_empty_value_is_ignored(self):
        merged, changed = deal_state.merge_slots(
            {}, {"student_grade": {"value": "  ", "evidence": "初二是吧"}}, 1
        )
        self.assertEqual(merged, {})
        self.assertEqual(changed, [])

    def test_existing_value_is_kept_without_revision(self):
        existing = fill({}, student_grade="初一")
        merged, changed = deal_state.merge_slots(
            existing, {"student_grade": {"value": "初二", "evidence": "现在初二了"}}, 2
        )
        self.assertEqual(merged["student_grade"]["value"], "初一")
        self.assertEqual(changed, [])

    def test_revision_overwrites_with_evidence(self):
        existing = fill({}, student_grade="初一")
        merged, changed = deal_state.merge_slots(
            existing,
            {"student_grade": {"value": "初二", "evidence": "现在初二了", "revised": True}},
            2,
        )
        self.assertEqual(merged["student_grade"]["value"], "初二")
        self.assertTrue(merged["student_grade"]["revised"])
        self.assertEqual(changed, ["student_grade"])


class StageTests(unittest.TestCase):
    def setUp(self):
        self.flags = {"parent_turns": 0, "course_introduced": False, "objection_raised": False}

    def test_advances_to_discovery_after_first_parent_turn(self):
        flags = dict(self.flags, parent_turns=1)
        self.assertEqual(deal_state.compute_stage("opening", {}, flags), "discovery")

    def test_does_not_advance_without_parent_turn(self):
        self.assertEqual(deal_state.compute_stage("opening", {}, self.flags), "opening")

    def test_advances_at_most_one_stage_per_turn(self):
        slots = fill(
            {},
            student_grade="初二",
            weak_subjects="数学",
            target_subject="数学",
            current_score="78分",
            pain_point="计算总丢分",
            target_goal="想进前100",
        )
        flags = dict(self.flags, parent_turns=3)
        # 门槛都满足，但一轮只能前进一阶
        self.assertEqual(deal_state.compute_stage("discovery", slots, flags), "diagnosis")

    def test_never_regresses(self):
        self.assertEqual(deal_state.compute_stage("closing", {}, self.flags), "closing")

    def test_skips_objection_when_none_raised(self):
        slots = fill(
            {},
            student_grade="初二",
            weak_subjects="数学",
            target_subject="数学",
            current_score="78分",
            pain_point="计算总丢分",
            target_goal="想进前100",
            preferred_format="一对一",
            budget_range="一学期2万",
        )
        flags = {"parent_turns": 5, "course_introduced": True, "objection_raised": False}
        self.assertEqual(deal_state.compute_stage("solution", slots, flags), "closing")


class GapTests(unittest.TestCase):
    def test_gaps_exclude_filled_slots(self):
        slots = fill({}, student_grade="初二")
        gaps = deal_state.compute_gaps(slots, "k12_junior", "discovery")
        self.assertNotIn("student_grade", [gap["key"] for gap in gaps])

    def test_gaps_respect_limit_and_carry_ask(self):
        gaps = deal_state.compute_gaps({}, "k12_junior", "opening", limit=3)
        self.assertEqual(len(gaps), 3)
        self.assertTrue(all(gap["ask"] for gap in gaps))

    def test_required_gaps_come_before_recommended(self):
        gaps = deal_state.compute_gaps({}, "k12_junior", "closing", limit=40)
        levels = [gap["level"] for gap in gaps]
        self.assertEqual(levels[0], REQUIRED)


class ClosingTests(unittest.TestCase):
    def test_detects_won(self):
        self.assertEqual(deal_state.detect_result("那就报名吧，怎么缴费"), "won")

    def test_detects_trial(self):
        self.assertEqual(deal_state.detect_result("那先安排一节试听看看"), "trial")

    def test_detects_explicit_refusal(self):
        self.assertEqual(deal_state.detect_result("不用了，我们不考虑"), "lost_explicit")

    def test_detects_soft_refusal(self):
        self.assertEqual(deal_state.detect_result("我回去和孩子爸爸商量一下"), "lost_soft")

    def test_no_signal_returns_none(self):
        self.assertIsNone(deal_state.detect_result("孩子最近在学钢琴"))

    def test_closing_suggested_when_parent_states_intent(self):
        closing = deal_state.detect_closing(
            {"stage": "solution", "round_number": 5, "last_gain_round": 5},
            slot_delta_count=2,
            coverage={"required_total": 14, "required_filled": 3, "percent": 21},
            latest_parent_text="那我考虑一下",
        )
        self.assertTrue(closing["suggest"])
        self.assertEqual(closing["result"], "lost_soft")

    def test_closing_suggested_when_coverage_high(self):
        closing = deal_state.detect_closing(
            {"stage": "closing", "round_number": 9, "last_gain_round": 9},
            slot_delta_count=1,
            coverage={"required_total": 14, "required_filled": 13, "percent": 93},
            latest_parent_text="嗯，然后呢",
        )
        self.assertTrue(closing["suggest"])
        self.assertIsNone(closing["result"])

    def test_no_suggestion_early_in_conversation(self):
        closing = deal_state.detect_closing(
            {"stage": "discovery", "round_number": 2, "last_gain_round": 2},
            slot_delta_count=1,
            coverage={"required_total": 14, "required_filled": 2, "percent": 14},
            latest_parent_text="嗯嗯",
        )
        self.assertFalse(closing["suggest"])

    def test_finalize_marks_incomplete_when_coverage_low(self):
        state = {"closing": {}, "stage": "discovery"}
        result = deal_state.finalize_result(state, {"required_total": 14, "required_filled": 2, "percent": 14})
        self.assertEqual(result, "incomplete")

    def test_finalize_uses_detected_result(self):
        state = {"closing": {"result": "won"}, "stage": "closing"}
        result = deal_state.finalize_result(state, {"required_total": 14, "required_filled": 14, "percent": 100})
        self.assertEqual(result, "won")


class PayloadTests(unittest.TestCase):
    def test_payload_shape(self):
        state = deal_state.new_state("k12_junior")
        state["slots"] = fill({}, student_grade="初二")
        state["stage"] = "diagnosis"
        payload = deal_state.build_progress_payload(state)
        self.assertEqual(payload["stage"], "diagnosis")
        self.assertEqual(payload["stage_label"], "现状诊断")
        self.assertEqual(payload["stage_order"], STAGE_ORDER)
        self.assertTrue(payload["coverage"]["required_total"] >= 13)
        self.assertTrue(any(slot["filled"] for slot in payload["slots"]))
        self.assertIn("closing", payload)

    def test_template_name_is_exposed(self):
        payload = deal_state.build_progress_payload(deal_state.new_state("k12_senior"))
        self.assertEqual(payload["template_name"], get_template("k12_senior")["name"])


if __name__ == "__main__":
    unittest.main()
