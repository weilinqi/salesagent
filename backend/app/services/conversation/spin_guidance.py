"""Asynchronous SPIN coaching graph for an authenticated practice session."""
import json
import logging
import re
import asyncio
from datetime import datetime, timezone
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.services.llm import get_minimax_service

logger = logging.getLogger(__name__)

SEARCH_TOOL = [{
    "type": "function",
    "function": {
        "name": "search_knowledge",
        "description": "Only when the conversation needs verified school, course, price, policy, or reference-script facts, search the existing knowledge base. Never infer missing facts.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Concise topic-specific search query"},
                "category": {"type": "string", "enum": ["all", "script", "objection", "framework", "case"]},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 4},
            },
            "required": ["query"],
        },
    },
}]


class GuidanceState(TypedDict, total=False):
    transcript: str
    phase: str
    draft: dict[str, Any]
    tool_call: dict[str, Any]
    references: list[dict[str, Any]]
    search_attempted: bool
    last_search_query: str


def _json_object(text: str) -> dict[str, Any]:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError("Guidance model returned no JSON")
    return json.loads(match.group())


def _coach_prompt(state: GuidanceState) -> list[dict[str, str]]:
    references = state.get("references") or []
    facts = "\n".join(
        f"- [{item['source']}] {item['text'][:500]}" for item in references[:4]
    ) or "尚无检索资料"
    return [
        {"role": "system", "content": (
            "你是上海教培机构销售员工的SPIN实时教练。根据最近对练，简短更新侧栏。"
            "仅把家长明确说出的内容列为已知；未知信息放入待了解。不要把推测写成事实。"
            "请为家长表达的真实顾虑给一个短、具体、可立即照做的提醒；没有明显问题就给正向下一步。"
            "如果对话明确涉及具体学校、课程、价格、校区、退费/请假规则，或需要引用话术依据，"
            "先调用 search_knowledge 检索；普通寒暄和一般沟通不检索。若与上次资料主题相同，沿用已有资料，不要重复检索；只有主题发生变化或此前资料明显不适用时才再次检索。拿到工具结果后再输出。"
            "只能引用检索结果；无结果时明确写‘知识库未找到相关资料’，禁止补造。"
            "最终只输出JSON：{phase, focus, parent_facts:[...], unknowns:[...], next_step, reminder, script, references:[{source,text}], not_found}。"
            "focus/next_step/reminder/script简短。references只能来自工具结果。phase取Situation/Problem/Implication/Need-payoff之一。"
        )},
        {"role": "user", "content": f"当前阶段：{state.get('phase', 'discovery')}\n上次检索主题：{state.get('last_search_query') or '无'}\n最近对话：\n{state['transcript']}\n检索资料：\n{facts}"},
    ]


async def _analyze(state: GuidanceState) -> dict[str, Any]:
    response = await get_minimax_service().chat(
        _coach_prompt(state), model="MiniMax-M3", temperature=0.2, max_tokens=700,
        tools=SEARCH_TOOL if not state.get("search_attempted") else None,
    )
    try:
        result = json.loads(response)
    except (TypeError, json.JSONDecodeError):
        result = {}
    if result.get("type") == "function_call":
        calls = result.get("tool_calls") or []
        if calls:
            return {"tool_call": calls[0]}
    return {"draft": _json_object(response), "tool_call": {}}


async def _search(state: GuidanceState) -> dict[str, Any]:
    call = state.get("tool_call") or {}
    function = call.get("function", {})
    if function.get("name") != "search_knowledge":
        return {"search_attempted": True, "references": [], "tool_call": {}}
    query = ""
    try:
        raw_args = function.get("arguments") or {}
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        if not isinstance(args, dict):
            args = {}
        query = str(args.get("query", ""))[:240]
        from app.services.knowledge.tools import execute_search_knowledge
        raw = await asyncio.to_thread(
            execute_search_knowledge, query,
            str(args.get("category", "all")), min(max(int(args.get("top_k", 3)), 1), 4),
        )
        parsed = json.loads(raw)
        rows = parsed.get("results", []) if isinstance(parsed, dict) else []
        refs = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            content = row.get("text") or row.get("excerpt") or row.get("content") or ""
            if isinstance(content, list):
                content = "\n".join(str(part) for part in content if part)
            if content:
                refs.append({
                    "source": str(row.get("source") or row.get("document") or "知识库资料"),
                    "text": str(content),
                })
        refs = refs[:4]
        return {"references": refs, "search_attempted": True, "last_search_query": query, "tool_call": {}}
    except Exception:
        logger.exception("SPIN guidance knowledge search failed")
        return {"references": [], "search_attempted": True, "search_error": True,
                "last_search_query": query, "tool_call": {}}


def _route(state: GuidanceState) -> str:
    return "search" if state.get("tool_call") and not state.get("search_attempted") else "finish"


_builder = StateGraph(GuidanceState)
_builder.add_node("analyze", _analyze)
_builder.add_node("search", _search)
_builder.add_edge(START, "analyze")
_builder.add_conditional_edges("analyze", _route, {"search": "search", "finish": END})
_builder.add_edge("search", "analyze")
_graph = _builder.compile()


def _normalize(result: dict[str, Any]) -> dict[str, Any]:
    draft = result.get("draft") or {}
    refs = result.get("references") or []
    facts = draft.get("parent_facts") if isinstance(draft.get("parent_facts"), list) else []
    unknowns = draft.get("unknowns") if isinstance(draft.get("unknowns"), list) else []
    clean_refs = [{"source": str(ref.get("source", "知识库资料")), "text": str(ref.get("text", ""))[:600]}
                  for ref in refs if isinstance(ref, dict) and ref.get("text")]
    return {
        "phase": str(draft.get("phase") or "Situation")[:24],
        "focus": str(draft.get("focus") or "继续倾听家长需求")[:100],
        "parent_facts": [str(item)[:100] for item in facts[:6]],
        "unknowns": [str(item)[:100] for item in unknowns[:6]],
        "next_step": str(draft.get("next_step") or "用开放问题了解家长最关心的目标")[:120],
        "reminder": str(draft.get("reminder") or "先回应家长顾虑，再追问具体影响")[:120],
        "script": str(draft.get("script") or "您最希望孩子这学期在哪方面有所进步？")[:160],
        "references": clean_refs,
        "not_found": bool(result.get("search_attempted")) and not clean_refs,
        "searched": bool(result.get("search_attempted")),
        "search_error": bool(result.get("search_error")),
        "last_search_query": result.get("last_search_query", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


async def update_guidance(session_id: str) -> dict[str, Any] | None:
    """Run a bounded tool-calling LangGraph agent and publish to the active socket."""
    from app.websocket.manager import manager, session_manager

    context = session_manager.get_context(session_id) or []
    recent = context[-12:]
    transcript = "\n".join(
        f"{'家长' if row.get('role') == 'ai' else '销售'}：{str(row.get('content') or '')[:280]}"
        for row in recent if row.get("role") in ("user", "ai", "assistant")
    )[-3600:]
    info = session_manager.get_session_info(session_id) or {}
    phase = info.get("current_phase") or "discovery"
    try:
        previous = getattr(manager, "_spin_guidance", {}).get(session_id, {})
        result = await _graph.ainvoke({"transcript": transcript, "phase": phase, "references": [],
                                        "last_search_query": previous.get("last_search_query", "")},
                                      config={"recursion_limit": 5})
        guidance = _normalize(result)
        states = getattr(manager, "_spin_guidance", None)
        if states is None:
            manager._spin_guidance = states = {}
        states[session_id] = guidance
        await manager.send_message(session_id, {"type": "spin_guidance", "data": guidance})
        return guidance
    except Exception:
        logger.exception("SPIN guidance update failed for session")
        return None
