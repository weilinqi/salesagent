"""LangGraph 搜索路由：判断该查本地知识库、联网，还是两路都要。

设计目标（对应《知识库搜索优化方案》）：
1. 不再用「相似度 >= 0.75 就搜网」这种一次拍板；
2. 先按问题类型分类（内部 / 外部 / 混合 / 不用搜），低置信时两路并行；
3. 检索完再做一次「证据够不够」的验收，不够就补救一次（改写成检索式再联网）。

外部约定
--------
``route_search`` 的入参与 ``rag.hybrid_search.hybrid_search`` 保持一致：
``(request, semantic_search, keyword_search, web_search)``，其中三个 callable
的签名分别是 ``(request) -> list``、``(request) -> list``、``(query, num) -> list``。

``mode='local'`` / ``'web'`` 仍然走旧实现，保证显式指定的调用方行为不变。
仅 ``mode='auto'`` 进入本模块的图。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Awaitable, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from app.services.rag.hybrid_search import fuse_results, safe_web_results

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

KIND_INTERNAL = "internal"
KIND_EXTERNAL = "external"
KIND_HYBRID = "hybrid"
KIND_NONE = "none"

# 分类置信度达到该值才敢只走一路，否则两路并行
CONFIDENT = 0.75
# 证据充分性达到该分才算够用（0-3）
MIN_SUFFICIENCY = 2
# 单个节点的时间上限（秒），保证整体搜索可控
CLASSIFY_TIMEOUT = 1.5
SUFFICIENCY_TIMEOUT = 2.0
REWRITE_TIMEOUT = 1.5
WEB_TIMEOUT = 6.0
# 分数兜底阈值，仅在没有 LLM 判定时使用
STRONG_SCORE = 0.75

INTERNAL_TERMS = (
    "话术", "异议", "框架", "案例", "脚本", "流程", "政策", "退费", "课时",
    "教材", "师资", "课程介绍", "成单", "逼单", "邀约", "开场", "提问",
    "spin", "情景问题", "难点问题", "暗示问题", "需求效益",
)
EXTERNAL_TERMS = (
    "最新", "今年", "现在", "最近", "当前", "政策变化", "新闻", "行情",
    "排名", "多少钱", "学费", "口碑", "评价", "竞品", "同行", "别家",
)
HEDGE_TERMS = ("你好", "谢谢", "在吗", "嗯", "好的")

# 「第三方评价」护栏：这类问题一律不联网
EVALUATION_TERMS = (
    "怎么样", "好不好", "口碑", "评价", "靠谱", "排名", "值得", "值不值",
    "对比", "比较", "优缺点", "坑不坑", "是不是坑",
)
# 这些词几乎只在评价某个主体时出现，命中即视为在问第三方口碑
STRONG_EVALUATION_TERMS = (
    "口碑", "评价", "靠谱", "排名", "值得", "值不值", "优缺点", "坑不坑", "是不是坑",
)
INSTITUTION_TERMS = (
    "机构", "学校", "教育", "培训", "辅导", "校区", "补习", "培训班",
)
COMPETITOR_TERMS = ("竞品", "同行", "别家", "其他机构", "竞争对手", "对手")
SELF_TERMS = (
    "我们", "咱们", "本机构", "自家", "我司", "本校", "课程", "课时",
    "退费", "话术", "流程", "政策", "教材", "师资", "报名",
)

_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub("", text or "")


def forbids_web_search(query: str) -> bool:
    """是否禁止联网：涉及第三方机构评价的问题一律不联网。

    规则只做粗筛保底，分类器的提示词里还有同样的约束，
    两道关都过不了才会真的去联网评同行。
    """
    q = _norm(query).lower()
    if not q:
        return False
    if not any(term.lower() in q for term in EVALUATION_TERMS):
        return False
    mentions_self = any(term.lower() in q for term in SELF_TERMS)
    # 明说竞品/同行 → 直接拦
    if any(term.lower() in q for term in COMPETITOR_TERMS):
        return True
    # 「口碑/评价/靠谱/排名」这类强评价词，只要不是在说自家 → 拦
    if any(term.lower() in q for term in STRONG_EVALUATION_TERMS) and not mentions_self:
        return True
    # 提到"机构/学校"且在问评价，且不是问自家 → 拦
    if any(term.lower() in q for term in INSTITUTION_TERMS) and not mentions_self:
        return True
    # 「XX的口碑怎么样」这类没有机构词但指向第三方的问法 → 拦
    if "的" in q and not mentions_self:
        return True
    return False


# ---------------------------------------------------------------------------
# 状态
# ---------------------------------------------------------------------------


class SearchState(TypedDict, total=False):
    query: str
    normalized: str
    kind: str
    confidence: float
    reason: str
    web_query: str
    local: list[dict[str, Any]]
    web: list[dict[str, Any]]
    local_failed: bool
    local_error: Any
    sufficiency: int
    missing: str
    repaired: bool
    forbidden_web: bool
    notices: list[str]
    trace: list[str]
    # 三个检索回调，由调用方注入
    semantic_search: Callable[[Any], Awaitable[list]]
    keyword_search: Callable[[Any], Awaitable[list]]
    web_search: Callable[..., Awaitable[list]]
    request: Any


def _trace(state: SearchState, message: str) -> list[str]:
    return [*(state.get("trace") or []), message]


def _notice(state: SearchState, message: str) -> list[str]:
    return [*(state.get("notices") or []), message]


# ---------------------------------------------------------------------------
# LLM 辅助
# ---------------------------------------------------------------------------


def _json_object(text: str) -> dict[str, Any]:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError("no json")
    return json.loads(match.group())


async def _ask_json(messages: list[dict[str, str]], *, timeout: float, max_tokens: int = 300) -> dict[str, Any]:
    from app.services.llm import get_minimax_service

    response = await asyncio.wait_for(
        get_minimax_service().chat(
            messages, model="MiniMax-M3", temperature=0.0, max_tokens=max_tokens,
        ),
        timeout=timeout,
    )
    return _json_object(response)


# ---------------------------------------------------------------------------
# 节点：规范化
# ---------------------------------------------------------------------------


def _rule_classify(query: str) -> tuple[str, float, str]:
    """没有模型时的规则分类，也用作模型失败时的兜底。"""
    q = _norm(query).lower()
    if len(q) <= 3:
        return KIND_NONE, 0.9, "问题过短，无需检索"
    if any(term in q for term in HEDGE_TERMS) and len(q) <= 6:
        return KIND_NONE, 0.8, "寒暄类，无需检索"
    internal = sum(1 for term in INTERNAL_TERMS if term.lower() in q)
    external = sum(1 for term in EXTERNAL_TERMS if term.lower() in q)
    if internal and external:
        return KIND_HYBRID, 0.6, "同时命中内部与外部关键词"
    if internal:
        return KIND_INTERNAL, 0.7, "命中内部资料关键词"
    if external:
        return KIND_EXTERNAL, 0.7, "命中时效/外部关键词"
    return KIND_HYBRID, 0.4, "未命中明确信号，两路并行更稳妥"


async def normalize(state: SearchState) -> dict[str, Any]:
    query = str(state.get("query") or "").strip()
    return {
        "normalized": _norm(query),
        "repaired": False,
        "web_query": query,
        "local": [],
        "web": [],
        "notices": [],
        "trace": [f"normalize: 输入长度 {len(query)}"],
    }


# ---------------------------------------------------------------------------
# 节点：分类
# ---------------------------------------------------------------------------


def _classify_prompt(query: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": (
            "你是销售对练系统的检索路由分类器。判断用户问题该查哪类资料。\n"
            "类别取值：\n"
            "- internal：公司内部资料能回答（话术、异议处理、SPIN、课程介绍、政策流程、案例）\n"
            "- external：需要外部实时信息（机构口碑、竞品动向、最新政策、市场行情、价格对比）\n"
            "- hybrid：两边都需要\n"
            "- none：寒暄、通用常识、不需要检索\n"
            "硬性规则：凡是要「评价第三方机构/学校/竞品」的问题（口碑、怎么样、好不好、排名、对比），"
            "一律归为 internal，绝不允许外部检索。\n"
            "只输出 JSON："
            '{"kind":"internal|external|hybrid|none","confidence":0-1,'
            '"reason":"不超过30字","web_query":"若需要联网，给出适合搜索引擎的检索式；否则空字符串"}'
        )},
        {"role": "user", "content": query},
    ]


async def classify(state: SearchState) -> dict[str, Any]:
    query = state.get("query") or ""
    forbidden = forbids_web_search(query)
    trace = list(state.get("trace") or [])
    notices = list(state.get("notices") or [])

    kind, confidence, reason = _rule_classify(query)
    web_query = state.get("web_query") or query
    try:
        payload = await _ask_json(_classify_prompt(query), timeout=CLASSIFY_TIMEOUT)
        candidate = str(payload.get("kind") or "").strip().lower()
        if candidate in (KIND_INTERNAL, KIND_EXTERNAL, KIND_HYBRID, KIND_NONE):
            kind = candidate
            confidence = float(payload.get("confidence") or 0.6)
            reason = str(payload.get("reason") or "")[:60]
        candidate_query = str(payload.get("web_query") or "").strip()
        if candidate_query:
            web_query = candidate_query[:200]
        trace.append(f"classify(LLM): {kind} {confidence:.2f} {reason}")
    except Exception:
        confidence = max(confidence, 0.6)
        trace.append(f"classify(规则兜底): {kind} {confidence:.2f} {reason}")

    if forbidden:
        if kind == KIND_EXTERNAL:
            kind = KIND_INTERNAL
        reason = "涉及第三方机构评价，按规范不联网"
        notices.append("该问题涉及对第三方机构的评价，按规范只使用内部资料，不联网检索。")
        trace.append("护栏生效：禁止联网")

    return {
        "kind": kind,
        "confidence": confidence,
        "reason": reason,
        "web_query": web_query,
        "forbidden_web": forbidden,
        "notices": list(dict.fromkeys(notices)),
        "trace": list(dict.fromkeys(trace)),
    }


# ---------------------------------------------------------------------------
# 节点：检索
# ---------------------------------------------------------------------------


async def local_search(state: SearchState) -> dict[str, Any]:
    request = state["request"]
    semantic = state["semantic_search"]
    keyword = state["keyword_search"]
    started = time.perf_counter()
    values = await asyncio.gather(semantic(request), keyword(request), return_exceptions=True)
    semantic_rows = values[0] if isinstance(values[0], list) else []
    keyword_rows = values[1] if isinstance(values[1], list) else []
    fused = fuse_results(semantic_rows, keyword_rows, request)
    local_failed = all(isinstance(value, Exception) for value in values)
    # 向量库自身报错（通常已被 _search 转成 HTTPException 503）要保留下来，
    # 不能因为"联网兜回来了一点内容"就把后端故障掩盖掉。
    local_error = next(
        (value for value in values
         if isinstance(value, Exception) and getattr(value, "status_code", None)),
        None,
    )
    notices = state.get("notices") or []
    if any(isinstance(value, Exception) for value in values):
        notices = [*notices, "本地部分检索暂不可用，已保留可用结果。请检查模型和文档入库状态。"]
    elapsed = int((time.perf_counter() - started) * 1000)
    return {
        "local": fused,
        "local_failed": local_failed,
        "local_error": local_error,
        "notices": notices,
        "trace": _trace(state, f"local_search: {len(fused)} 条，{elapsed}ms"),
    }


async def web_search_node(state: SearchState) -> dict[str, Any]:
    if state.get("forbidden_web"):
        return {"web": [], "trace": _trace(state, "web_search: 被护栏拦截，跳过")}

    request = state["request"]
    query = state.get("web_query") or state.get("query") or ""
    started = time.perf_counter()
    try:
        rows = await asyncio.wait_for(
            state["web_search"](query, min(request.top_k, 10)), timeout=WEB_TIMEOUT,
        )
        web = safe_web_results(rows, request.top_k)
    except Exception:
        return {
            "web": [],
            "notices": _notice(state, "MiniMax 联网搜索暂不可用，请检查搜索密钥、搜索权限或网络后重试。本地结果仍可使用。"),
            "trace": _trace(state, "web_search: 失败，已降级"),
        }
    notices = state.get("notices") or []
    if not web:
        notices = [*notices, "联网搜索没有找到可展示的来源，已回落到本地结果。"]
    elapsed = int((time.perf_counter() - started) * 1000)
    return {"web": web, "notices": notices, "trace": _trace(state, f"web_search: {len(web)} 条，{elapsed}ms")}


async def both_search(state: SearchState) -> dict[str, Any]:
    local_part, web_part = await asyncio.gather(
        local_search(state), web_search_node(state), return_exceptions=True,
    )
    merged: dict[str, Any] = {}
    trace = list(state.get("trace") or [])
    notices = list(state.get("notices") or [])
    for part in (local_part, web_part):
        if isinstance(part, Exception):
            continue
        for key, value in part.items():
            if key == "trace":
                trace.extend(value)
            elif key == "notices":
                notices = list(value)
            else:
                merged[key] = value
    merged["trace"] = list(dict.fromkeys(trace))
    merged["notices"] = list(dict.fromkeys(notices))
    return merged


# ---------------------------------------------------------------------------
# 节点：验收
# ---------------------------------------------------------------------------


def _heuristic_sufficiency(state: SearchState) -> int:
    local = state.get("local") or []
    web = state.get("web") or []
    if not local and not web:
        return 0
    if any(row.get("score", 0) >= STRONG_SCORE for row in local):
        return 3
    if local:
        return 2 if len(local) >= 2 else 1
    return 2 if web else 0


def _sufficiency_prompt(query: str, local: list[dict], web: list[dict]) -> list[dict[str, str]]:
    def snippet(rows, key, limit=3):
        lines = []
        for row in rows[:limit]:
            text = str(row.get(key) or row.get("text") or "")[:180]
            if text:
                lines.append(f"- {text}")
        return "\n".join(lines) or "（无）"

    return [
        {"role": "system", "content": (
            "你是检索结果验收员。判断下面的材料能否**直接回答**用户的问题。\n"
            "3 = 能完整回答\n2 = 能回答大部分，缺一两个细节\n1 = 只是相关，答不了具体问题\n0 = 完全无关\n"
            "只输出 JSON：{\"score\":0-3,\"missing\":\"还缺什么，不超过30字\"}"
        )},
        {"role": "user", "content": (
            f"用户问题：{query}\n\n内部资料片段：\n{snippet(local, 'text')}\n\n"
            f"外部资料片段：\n{snippet(web, 'snippet')}"
        )},
    ]


async def sufficiency(state: SearchState) -> dict[str, Any]:
    fallback = _heuristic_sufficiency(state)
    try:
        payload = await _ask_json(
            _sufficiency_prompt(state.get("query") or "", state.get("local") or [], state.get("web") or []),
            timeout=SUFFICIENCY_TIMEOUT,
        )
        score = int(payload.get("score"))
        score = max(0, min(3, score))
        missing = str(payload.get("missing") or "")[:60]
        trace = _trace(state, f"sufficiency(LLM): {score} {missing}")
    except Exception:
        score, missing = fallback, ""
        trace = _trace(state, f"sufficiency(兜底): {score}")
    return {"sufficiency": score, "missing": missing, "trace": trace}


def _needs_repair(state: SearchState) -> str:
    if state.get("repaired"):
        return "merge"
    if state.get("forbidden_web"):
        return "merge"
    if int(state.get("sufficiency") or 0) >= MIN_SUFFICIENCY:
        return "merge"
    # 已经在联网结果里也救不回来，就不再重试
    if state.get("web"):
        return "merge"
    return "rewrite"


# ---------------------------------------------------------------------------
# 节点：补救
# ---------------------------------------------------------------------------


async def rewrite_web_query(state: SearchState) -> dict[str, Any]:
    query = state.get("query") or ""
    missing = state.get("missing") or ""
    prompt = [
        {"role": "system", "content": (
            "把用户的口语问题改写成适合搜索引擎的检索式：补上地域/学段/科目等限定，"
            "去掉口语词。只输出改写后的检索式，不要解释，不超过 40 字。"
        )},
        {"role": "user", "content": f"用户问题：{query}\n还缺的信息：{missing or '无'}"},
    ]
    try:
        from app.services.llm import get_minimax_service
        text = await asyncio.wait_for(
            get_minimax_service().chat(prompt, model="MiniMax-M3", temperature=0.0, max_tokens=80),
            timeout=REWRITE_TIMEOUT,
        )
        rewritten = re.sub(r"\s+", " ", str(text or "")).strip().strip('"')
        if len(rewritten) < 2:
            raise ValueError("empty rewrite")
    except Exception:
        rewritten = state.get("web_query") or query
    return {
        "web_query": rewritten[:200],
        "repaired": True,
        "trace": _trace(state, f"rewrite: {rewritten[:40]}"),
    }


async def repair_web_search(state: SearchState) -> dict[str, Any]:
    """补救专用：改写后重新联网。

    单独成节点是为了避免 ``web_search`` 同时有两条出边
    （LangGraph 会并行执行两条边，导致 trace 被并发写入而报错）。
    """
    result = await web_search_node({**state, "web": []})
    return result


# ---------------------------------------------------------------------------
# 节点：合并
# ---------------------------------------------------------------------------


async def merge(state: SearchState) -> dict[str, Any]:
    local = state.get("local") or []
    web = state.get("web") or []
    annotated = [
        {**row, "source_type": "internal"}
        for row in local
    ]
    web_rows = [
        {**row, "source_type": "web"}
        for row in web
    ]
    return {
        "local": annotated,
        "web": web_rows,
        "trace": _trace(state, f"merge: 内部 {len(annotated)} 条 / 外部 {len(web_rows)} 条"),
    }


# ---------------------------------------------------------------------------
# 路由边
# ---------------------------------------------------------------------------


def _route(state: SearchState) -> str:
    kind = state.get("kind") or KIND_HYBRID
    confidence = float(state.get("confidence") or 0)
    if kind == KIND_NONE:
        return "merge"
    if kind == KIND_INTERNAL and confidence >= CONFIDENT:
        return "local"
    if kind == KIND_EXTERNAL and confidence >= CONFIDENT and not state.get("forbidden_web"):
        return "web"
    return "both"


_builder = StateGraph(SearchState)
_builder.add_node("normalize", normalize)
_builder.add_node("classify", classify)
_builder.add_node("local_search", local_search)
_builder.add_node("web_search", web_search_node)
_builder.add_node("both_search", both_search)
_builder.add_node("sufficiency", sufficiency)
_builder.add_node("rewrite", rewrite_web_query)
_builder.add_node("repair_web_search", repair_web_search)
_builder.add_node("merge", merge)

_builder.add_edge(START, "normalize")
_builder.add_edge("normalize", "classify")
_builder.add_conditional_edges("classify", _route, {
    "local": "local_search",
    "web": "web_search",
    "both": "both_search",
    "merge": "merge",
})
_builder.add_edge("local_search", "sufficiency")
_builder.add_edge("web_search", "sufficiency")
_builder.add_edge("both_search", "sufficiency")
_builder.add_conditional_edges("sufficiency", _needs_repair, {
    "rewrite": "rewrite",
    "merge": "merge",
})
_builder.add_edge("rewrite", "repair_web_search")
_builder.add_edge("repair_web_search", "merge")
_builder.add_edge("merge", END)
_graph = _builder.compile()


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------


async def route_search(request, semantic_search, keyword_search, web_search) -> dict[str, Any]:
    """按 request.mode 选择实现；auto 走本模块的 LangGraph。"""
    from app.services.rag.hybrid_search import hybrid_search

    mode = getattr(request, "mode", "auto")
    if mode in ("local", "web"):
        # 显式指定模式时保持旧行为，避免"优化"掉调用方的意图
        return await hybrid_search(request, semantic_search, keyword_search, web_search)

    started = time.perf_counter()
    result = await _graph.ainvoke({
        "query": request.query,
        "semantic_search": semantic_search,
        "keyword_search": keyword_search,
        "web_search": web_search,
        "request": request,
    })
    elapsed = int((time.perf_counter() - started) * 1000)
    local = result.get("local") or []
    web = result.get("web") or []
    # 向量库本身报错 → 直接抛出（上层转 503），不让联网结果掩盖后端故障
    local_error = result.get("local_error")
    if isinstance(local_error, Exception):
        raise local_error
    # 本地检索整体失败、外部也没有结果 → 视为检索不可用，由上层报 503，
    # 与改造前的行为保持一致（不能让故障被"降级"成空结果）。
    if result.get("local_failed") and not web:
        raise RuntimeError("Knowledge retrieval unavailable")
    if not local and not web and not result.get("kind") == KIND_NONE:
        # 两路都空且不是"不用检索"，视为检索不可用，交给上层报 503
        raise RuntimeError("Knowledge retrieval unavailable")

    return {
        "results": local,
        "query": request.query,
        "total": len(local),
        "web_results": web,
        "notices": result.get("notices") or [],
        "mode": mode,
        "route": result.get("kind") or KIND_HYBRID,
        "sufficiency": int(result.get("sufficiency") or 0),
        "route_reason": result.get("reason") or "",
        "forbidden_web": bool(result.get("forbidden_web")),
        "trace": [*(result.get("trace") or []), f"总耗时 {elapsed}ms"],
    }
