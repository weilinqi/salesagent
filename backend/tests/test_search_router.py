"""检索路由（LangGraph）单元测试：分类、护栏、验收与补救。

全部打桩，不访问网络、不加载模型。
"""

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SECRET_KEY", "search-router-test-secret-long-enough-for-tests")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")

from app.services import search_router


def run_async(coroutine):
    if os.name == "nt":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def request(query="嫌贵怎么办", mode="auto", top_k=5, category=None, source_filter=None):
    return SimpleNamespace(query=query, mode=mode, top_k=top_k,
                           category=category, source_filter=source_filter)


def local_row(row_id="k1", score=0.9, text="价格异议处理：先共情再给方案"):
    return {"id": row_id, "text": text, "source": "话术手册.pdf",
            "score": score, "metadata": {"category": "spin"}, "_query_coverage": score}


def web_row(url="https://example.com/a"):
    return {"url": url, "title": "示例来源", "snippet": "示例摘要", "date": "2026-11-01"}


class Callables:
    """记录调用次数的三个检索替身。"""

    def __init__(self, local=None, web=None):
        self.semantic = AsyncMock(return_value=local if local is not None else [local_row()])
        self.keyword = AsyncMock(return_value=[])
        self.web = AsyncMock(return_value=web if web is not None else [web_row()])


class FallbackClassifierTests(unittest.TestCase):
    def test_internal_terms_classify_as_internal(self):
        kind, confidence, _ = search_router._rule_classify("家长说嫌贵 价格异议怎么处理")
        self.assertEqual(kind, search_router.KIND_INTERNAL)
        self.assertGreater(confidence, 0)

    def test_external_terms_classify_as_external(self):
        kind, _, _ = search_router._rule_classify("上海最新 K12 培训行情 学费多少钱")
        self.assertEqual(kind, search_router.KIND_EXTERNAL)

    def test_mixed_signals_are_hybrid(self):
        kind, _, _ = search_router._rule_classify("最新政策下我们的退费话术怎么写")
        self.assertEqual(kind, search_router.KIND_HYBRID)

    def test_greeting_needs_no_search(self):
        kind, _, _ = search_router._rule_classify("你好")
        self.assertEqual(kind, search_router.KIND_NONE)


class WebGuardTests(unittest.TestCase):
    def test_third_party_evaluation_is_forbidden(self):
        self.assertTrue(search_router.forbids_web_search("学而思的口碑怎么样"))
        self.assertTrue(search_router.forbids_web_search("XX机构靠谱吗"))

    def test_own_material_is_allowed(self):
        self.assertFalse(search_router.forbids_web_search("我们的课程退费政策怎么样"))
        self.assertFalse(search_router.forbids_web_search("家长说太贵怎么办"))

    def test_competitor_comparison_is_forbidden(self):
        self.assertTrue(search_router.forbids_web_search("竞品对比 哪家好 排名"))


class RouterGraphTests(unittest.TestCase):
    def _run(self, req, callables, classify_kind, sufficiency_score=3):
        async def fake_ask_json(messages, *, timeout, max_tokens=300):
            system = messages[0]["content"]
            if "分类器" in system:
                return {"kind": classify_kind, "confidence": 0.95, "reason": "test",
                        "web_query": "改写后的检索式"}
            if "验收员" in system:
                return {"score": sufficiency_score, "missing": ""}
            raise AssertionError(f"unexpected prompt: {system[:40]}")

        with patch.object(search_router, "_ask_json", side_effect=fake_ask_json):
            return run_async(search_router.route_search(
                req, callables.semantic, callables.keyword, callables.web))

    def test_internal_question_skips_web(self):
        callables = Callables()
        result = self._run(request("嫌贵怎么办"), callables, search_router.KIND_INTERNAL)
        self.assertEqual(result["route"], search_router.KIND_INTERNAL)
        self.assertGreater(result["total"], 0)
        callables.web.assert_not_called()
        self.assertEqual(result["results"][0]["source_type"], "internal")

    def test_external_question_calls_web(self):
        callables = Callables(local=[], web=[web_row()])
        result = self._run(request("上海最新培训政策"), callables, search_router.KIND_EXTERNAL)
        callables.web.assert_awaited()
        self.assertTrue(result["web_results"])
        self.assertEqual(result["web_results"][0]["source_type"], "web")

    def test_low_confidence_hits_both(self):
        callables = Callables()
        result = self._run(request("这个怎么弄"), callables, search_router.KIND_HYBRID)
        callables.semantic.assert_awaited()
        callables.web.assert_awaited()
        self.assertTrue(result["results"])
        self.assertTrue(result["web_results"])

    def test_guard_blocks_web_even_if_model_says_external(self):
        callables = Callables(local=[local_row()])
        result = self._run(request("学而思口碑怎么样"), callables, search_router.KIND_EXTERNAL)
        self.assertTrue(result["forbidden_web"])
        callables.web.assert_not_called()
        self.assertTrue(any("不联网" in notice for notice in result["notices"]))

    def test_none_kind_returns_without_search(self):
        callables = Callables()
        result = self._run(request("你好"), callables, search_router.KIND_NONE)
        self.assertEqual(result["route"], search_router.KIND_NONE)
        callables.semantic.assert_not_called()
        callables.web.assert_not_called()


class RepairTests(unittest.TestCase):
    def test_weak_local_without_web_triggers_rewrite_and_retry(self):
        """本地结果弱、联网也没东西 → 应改写查询再搜一次。"""
        callables = Callables(local=[local_row(score=0.3)], web=[])

        async def fake_ask_json(messages, *, timeout, max_tokens=300):
            system = messages[0]["content"]
            if "分类器" in system:
                return {"kind": search_router.KIND_INTERNAL, "confidence": 0.95,
                        "reason": "test", "web_query": "原始查询"}
            if "验收员" in system:
                return {"score": 1, "missing": "缺少具体价格"}
            raise AssertionError("unexpected")

        async def fake_chat(messages, **kwargs):
            return "高二 数学 一对一 课程价格 上海"

        with patch.object(search_router, "_ask_json", side_effect=fake_ask_json), \
             patch("app.services.llm.get_minimax_service") as service:
            service.return_value.chat = fake_chat
            result = run_async(search_router.route_search(
                request("那个课多少钱"), callables.semantic, callables.keyword, callables.web))

        self.assertEqual(callables.web.await_count, 1, "补救时应联网一次")
        self.assertTrue(any("rewrite" in line for line in result["trace"]))

    def test_sufficient_local_does_not_repair(self):
        callables = Callables(local=[local_row(score=0.9)])

        async def fake_ask_json(messages, *, timeout, max_tokens=300):
            if "分类器" in messages[0]["content"]:
                return {"kind": search_router.KIND_INTERNAL, "confidence": 0.95,
                        "reason": "test", "web_query": ""}
            return {"score": 3, "missing": ""}

        with patch.object(search_router, "_ask_json", side_effect=fake_ask_json):
            result = run_async(search_router.route_search(
                request("价格异议话术"), callables.semantic, callables.keyword, callables.web))

        callables.web.assert_not_called()
        self.assertGreaterEqual(result["sufficiency"], 2)


class ModeDelegationTests(unittest.TestCase):
    def test_explicit_local_mode_keeps_old_behaviour(self):
        """mode='local' 必须绕过图，保持原有行为。"""
        callables = Callables()

        async def fake_ask_json(*args, **kwargs):
            raise AssertionError("mode=local 不应触达分类器")

        with patch.object(search_router, "_ask_json", side_effect=fake_ask_json):
            result = run_async(search_router.route_search(
                request("价格异议", mode="local"), callables.semantic, callables.keyword, callables.web))

        self.assertEqual(result["mode"], "local")
        callables.web.assert_not_called()


if __name__ == "__main__":
    unittest.main()
