"""对话账本测试：验证"问过并被答复"的话题会被记录，并渲染成防重复提示。"""

import os
import unittest

os.environ.setdefault("SECRET_KEY", "dialogue-ledger-test-secret-long-enough-for-tests")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")

from app.services.conversation import dialogue_ledger


def conv(*rows):
    """rows: ('sales'|'parent', 文本)"""
    context = []
    for role, text in rows:
        context.append({"role": "user" if role == "sales" else "ai", "content": text})
    return context


class TopicDetectionTests(unittest.TestCase):
    def test_detects_trial_topic(self):
        self.assertIn("trial", dialogue_ledger.detect_topics("试听课怎么安排？"))

    def test_detects_multiple_topics(self):
        topics = dialogue_ledger.detect_topics("价格多少，校区在哪")
        self.assertIn("price", topics)
        self.assertIn("campus", topics)

    def test_plain_statement_has_no_topic(self):
        self.assertEqual(dialogue_ledger.detect_topics("孩子初二"), [])

    def test_question_detection(self):
        self.assertTrue(dialogue_ledger.is_question("试听怎么安排"))
        self.assertTrue(dialogue_ledger.is_question("多少钱?"))
        self.assertFalse(dialogue_ledger.is_question("好的我知道了"))


class LedgerTests(unittest.TestCase):
    def test_repeated_question_is_marked_answered(self):
        ledger = dialogue_ledger.build_ledger(conv(
            ("parent", "试听课怎么安排？"),
            ("sales", "周六上午十点有一节体验课，可以带孩子来"),
        ))
        trial = next(r for r in ledger["asked"] if r["topic"] == "trial")
        self.assertTrue(trial["answered"])
        self.assertIn("周六", trial["answer"])
        self.assertEqual(ledger["unanswered"], [])

    def test_question_without_answer_stays_open(self):
        ledger = dialogue_ledger.build_ledger(conv(
            ("parent", "试听课怎么安排？"),
            ("sales", "您孩子现在几年级？"),
        ))
        trial = next(r for r in ledger["asked"] if r["topic"] == "trial")
        self.assertFalse(trial["answered"])
        self.assertEqual([item["topic"] for item in ledger["unanswered"]], ["trial"])

    def test_times_asked_accumulates_before_answer(self):
        ledger = dialogue_ledger.build_ledger(conv(
            ("parent", "试听课怎么安排？"),
            ("sales", "您先说说孩子情况"),
            ("parent", "我问试听听课怎么安排"),
        ))
        trial = next(r for r in ledger["asked"] if r["topic"] == "trial")
        self.assertEqual(trial["times_asked"], 2)
        self.assertFalse(trial["answered"])

    def test_answer_after_second_ask_closes_topic(self):
        ledger = dialogue_ledger.build_ledger(conv(
            ("parent", "试听课怎么安排？"),
            ("sales", "孩子几年级？"),
            ("parent", "试听怎么安排嘛"),
            ("sales", "周六上午十点体验课"),
        ))
        trial = next(r for r in ledger["asked"] if r["topic"] == "trial")
        self.assertTrue(trial["answered"])

    def test_answered_topic_not_reopened_by_later_question(self):
        ledger = dialogue_ledger.build_ledger(conv(
            ("parent", "试听课怎么安排？"),
            ("sales", "周六上午十点有体验课"),
            ("parent", "那价格呢？"),
            ("sales", "一学期 12800"),
        ))
        trial = next(r for r in ledger["asked"] if r["topic"] == "trial")
        price = next(r for r in ledger["asked"] if r["topic"] == "price")
        self.assertTrue(trial["answered"])
        self.assertTrue(price["answered"])
        self.assertEqual(len(ledger["asked"]), 2)

    def test_empty_context_yields_empty_ledger(self):
        ledger = dialogue_ledger.build_ledger([])
        self.assertEqual(ledger["asked"], [])


class RenderTests(unittest.TestCase):
    def test_render_is_empty_without_data(self):
        self.assertEqual(dialogue_ledger.render_ledger(dialogue_ledger.build_ledger([])), "")

    def test_render_contains_answered_topic_and_answer(self):
        ledger = dialogue_ledger.build_ledger(conv(
            ("parent", "试听课怎么安排？"),
            ("sales", "周六上午十点有体验课"),
        ))
        text = dialogue_ledger.render_ledger(ledger)
        self.assertIn("试听安排", text)
        self.assertIn("周六上午十点", text)
        self.assertIn("不要再问", text)

    def test_render_includes_customer_facts(self):
        ledger = dialogue_ledger.build_ledger(conv(("parent", "孩子初二")))
        text = dialogue_ledger.render_ledger(ledger, customer_facts={"孩子年级": "初二"})
        self.assertIn("孩子年级=初二", text)

    def test_render_lists_open_topics(self):
        ledger = dialogue_ledger.build_ledger(conv(("parent", "退费怎么算？")))
        text = dialogue_ledger.render_ledger(ledger)
        self.assertIn("还没答复", text)
        self.assertIn("退费规则", text)

    def test_turn_reminder_targets_latest_answered_topic(self):
        ledger = dialogue_ledger.build_ledger(conv(
            ("parent", "试听课怎么安排？"),
            ("sales", "周六上午十点有体验课"),
        ))
        reminder = dialogue_ledger.render_turn_reminder(ledger)
        self.assertIn("试听安排", reminder)
        self.assertIn("绝不要再问", reminder)

    def test_turn_reminder_empty_when_nothing_answered(self):
        ledger = dialogue_ledger.build_ledger(conv(("parent", "试听怎么安排？")))
        self.assertEqual(dialogue_ledger.render_turn_reminder(ledger), "")


class RepeatGuardTests(unittest.TestCase):
    def test_flags_repeat_of_answered_topic(self):
        ledger = dialogue_ledger.build_ledger(conv(
            ("parent", "试听课怎么安排？"),
            ("sales", "周六上午十点有体验课"),
        ))
        self.assertTrue(dialogue_ledger.is_repeat_question("那试听课到底怎么安排？", ledger))

    def test_does_not_flag_new_topic(self):
        ledger = dialogue_ledger.build_ledger(conv(
            ("parent", "试听课怎么安排？"),
            ("sales", "周六上午十点有体验课"),
        ))
        self.assertFalse(dialogue_ledger.is_repeat_question("那价格大概多少？", ledger))

    def test_does_not_flag_statement(self):
        ledger = dialogue_ledger.build_ledger(conv(
            ("parent", "试听课怎么安排？"),
            ("sales", "周六上午十点有体验课"),
        ))
        self.assertFalse(dialogue_ledger.is_repeat_question("好的，那我考虑一下", ledger))


class DealStateBridgeTests(unittest.TestCase):
    def test_facts_extracted_from_slots(self):
        state = {
            "template_id": "k12_junior",
            "slots": {
                "student_grade": {"value": "初二", "evidence": "初二是吧", "round": 1},
                "weak_subjects": {"value": "数学", "evidence": "数学跟不上", "round": 1},
                "unknown_key": {"value": "x", "evidence": "y", "round": 1},
            },
        }
        facts = dialogue_ledger.facts_from_deal_state(state)
        self.assertEqual(facts["孩子年级"], "初二")
        self.assertEqual(facts["薄弱科目"], "数学")
        self.assertIn("unknown_key", facts)

    def test_none_state_yields_empty(self):
        self.assertEqual(dialogue_ledger.facts_from_deal_state(None), {})


class RepeatAfterAnswerTests(unittest.TestCase):
    """已经答复过还再问 —— 正是这次要治理的行为。"""

    def test_repeat_after_answer_is_counted(self):
        ledger = dialogue_ledger.build_ledger(conv(
            ("parent", "试听课怎么安排？"),
            ("sales", "周六上午十点有体验课"),
            ("parent", "那试听课怎么安排？"),
        ))
        trial = next(r for r in ledger["asked"] if r["topic"] == "trial")
        self.assertEqual(trial["times_asked"], 2)
        self.assertTrue(trial.get("repeat_after_answer"))

    def test_reminder_uses_strong_wording_for_repeat(self):
        ledger = dialogue_ledger.build_ledger(conv(
            ("parent", "试听课怎么安排？"),
            ("sales", "周六上午十点有体验课"),
            ("parent", "那试听课怎么安排？"),
        ))
        reminder = dialogue_ledger.render_turn_reminder(ledger)
        self.assertIn("又重复问了", reminder)
        self.assertIn("绝对不能再问", reminder)

    def test_no_strong_wording_before_first_answer(self):
        ledger = dialogue_ledger.build_ledger(conv(
            ("parent", "试听课怎么安排？"),
            ("sales", "孩子几年级？"),
            ("parent", "试听怎么安排？"),
        ))
        trial = next(r for r in ledger["asked"] if r["topic"] == "trial")
        self.assertEqual(trial["times_asked"], 2)
        self.assertFalse(trial.get("repeat_after_answer"))


if __name__ == "__main__":
    unittest.main()
