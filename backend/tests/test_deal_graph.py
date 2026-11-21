"""对练推进图的编排测试：验证 plan / extract / judge 的走向与降级行为。

LLM 全部打桩，不访问网络。
"""

import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SECRET_KEY", "deal-graph-test-secret-long-enough-for-tests")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")

from app.services.conversation import deal_graph, deal_state


def run_async(coroutine):
    if os.name == "nt":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def base_state(**overrides):
    state = {
        "template_id": "k12_junior",
        "slots": {},
        "flags": {},
        "stage": "opening",
        "round_number": 1,
        "new_messages": [],
    }
    state.update(overrides)
    return state


class GraphRoutingTests(unittest.TestCase):
    def test_no_parent_message_skips_extractor(self):
        service = AsyncMock()
        with patch.object(deal_graph, "get_minimax_service", return_value=service):
            result = run_async(deal_graph._graph.ainvoke(base_state(
                new_messages=[{"role": "sales", "content": "您好，我这边是某某教育"}],
            )))
        service.chat.assert_not_called()
        self.assertEqual(result.get("extracted"), {})

    def test_parent_message_runs_extractor(self):
        payload = json.dumps({"slots": {"student_grade": {"value": "初二", "evidence": "现在初二是吧"}}})
        service = AsyncMock()
        service.chat = AsyncMock(return_value=payload)
        with patch.object(deal_graph, "get_minimax_service", return_value=service):
            result = run_async(deal_graph._graph.ainvoke(base_state(
                new_messages=[{"role": "parent", "content": "现在初二是吧，数学有点跟不上"}],
            )))
        service.chat.assert_awaited_once()
        self.assertEqual(result["extracted"]["student_grade"]["value"], "初二")
        self.assertTrue(result["extracted"]["student_grade"]["evidence"])

    def test_extractor_failure_degrades_without_raising(self):
        service = AsyncMock()
        service.chat = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(deal_graph, "get_minimax_service", return_value=service):
            result = run_async(deal_graph._graph.ainvoke(base_state(
                new_messages=[{"role": "parent", "content": "初二是吧"}],
            )))
        self.assertEqual(result.get("extracted"), {})
        self.assertEqual(result.get("error"), "RuntimeError")

    def test_extractor_non_json_degrades(self):
        service = AsyncMock()
        service.chat = AsyncMock(return_value="抱歉，我无法回答")
        with patch.object(deal_graph, "get_minimax_service", return_value=service):
            result = run_async(deal_graph._graph.ainvoke(base_state(
                new_messages=[{"role": "parent", "content": "初二是吧"}],
            )))
        self.assertEqual(result.get("extracted"), {})


class MessageSplitTests(unittest.TestCase):
    def test_relabels_practice_roles(self):
        context = [
            {"role": "user", "content": "您好"},
            {"role": "ai", "content": "你好，哪位"},
            {"role": "assistant", "content": "孩子初二"},
            {"role": "knowledge_refs", "content": []},
            {"role": "system", "content": ""},
        ]
        rows = deal_graph._split_messages(context, 0)
        self.assertEqual([row["role"] for row in rows], ["sales", "parent", "parent"])

    def test_respects_start_index(self):
        context = [
            {"role": "user", "content": "第一轮"},
            {"role": "ai", "content": "第一轮回复"},
            {"role": "user", "content": "第二轮"},
            {"role": "ai", "content": "第二轮回复"},
        ]
        rows = deal_graph._split_messages(context, 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["content"], "第二轮")

    def test_latest_parent_text_returns_last_parent_line(self):
        rows = [
            {"role": "parent", "content": "早先说过的"},
            {"role": "sales", "content": "销售的话"},
            {"role": "parent", "content": "最后一句"},
        ]
        self.assertEqual(deal_graph._latest_parent_text(rows), "最后一句")


class EndToEndRuleTests(unittest.TestCase):
    """抽取成功后，规则层应正确推进阶段与覆盖率。"""

    def test_extraction_feeds_stage_and_coverage(self):
        payload = json.dumps({"slots": {
            "student_grade": {"value": "初二", "evidence": "现在初二是吧"},
            "weak_subjects": {"value": "数学", "evidence": "数学有点跟不上"},
            "target_subject": {"value": "数学", "evidence": "主要想补数学"},
        }})
        service = AsyncMock()
        service.chat = AsyncMock(return_value=payload)
        with patch.object(deal_graph, "get_minimax_service", return_value=service):
            result = run_async(deal_graph._graph.ainvoke(base_state(
                new_messages=[{"role": "parent", "content": "现在初二是吧，数学有点跟不上，主要想补数学"}],
            )))

        slots, changed = deal_state.merge_slots({}, result["extracted"], 1)
        self.assertEqual(len(changed), 3)
        coverage = deal_state.compute_coverage(slots, "k12_junior")
        self.assertEqual(coverage["required_filled"], 3)

        flags = deal_state.update_flags(
            {}, parent_turns=1,
            parent_text="现在初二是吧，数学有点跟不上，主要想补数学",
            sales_text="您孩子现在几年级？",
        )
        self.assertEqual(deal_state.compute_stage("opening", slots, flags), "discovery")


class AnalyzeSessionTests(unittest.TestCase):
    """端到端跑 analyze_session：必须真的把 deal_progress 推出去。

    回归背景：_persist 是同步函数，曾被误写成 `await _persist(...)`，
    结果落库成功但推送前抛 TypeError，前端看板停在初始状态永不更新。
    """

    def test_analyze_session_pushes_progress_event(self):
        import importlib
        from unittest.mock import MagicMock

        # 注意：app.websocket.__init__ 导出了 manager 实例，
        # 因此必须用 importlib 拿模块本身，不能用 from app.websocket import manager。
        ws_module = importlib.import_module("app.websocket.manager")

        payload = json.dumps({"slots": {"student_grade": {"value": "初二", "evidence": "初二是吧"}}})
        service = AsyncMock()
        service.chat = AsyncMock(return_value=payload)
        send = AsyncMock(return_value=True)

        context = [
            {"role": "user", "content": "孩子现在几年级？"},
            {"role": "ai", "content": "初二"},
        ]
        with patch.object(ws_module.manager, "send_message", new=send), \
             patch.object(ws_module.session_manager, "get_context", return_value=context), \
             patch.object(ws_module.session_manager, "get_session_info", return_value={}), \
             patch.object(ws_module.session_manager, "update_phase", new=MagicMock()), \
             patch.object(deal_graph, "_persist") as persist, \
             patch.object(deal_graph, "get_minimax_service", return_value=service):
            result = run_async(deal_graph.analyze_session("session-push-test"))

        self.assertIsNotNone(result, "analyze_session 不应返回 None")
        self.assertEqual(result["template_name"], "K12 · 初中")
        persist.assert_called_once()
        send.assert_awaited_once()
        event = send.await_args.args[1]
        self.assertEqual(event["type"], "deal_progress")
        self.assertEqual(event["data"]["stage"], "discovery")

    def test_persist_is_not_awaited(self):
        """守卫：_persist 必须是同步函数，否则 await 会抛 TypeError。"""
        import inspect

        self.assertFalse(inspect.iscoroutinefunction(deal_graph._persist))


if __name__ == "__main__":
    unittest.main()
