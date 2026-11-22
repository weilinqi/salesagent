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
    training_mode: str
    price_context: dict[str, Any]
    round_number: int
    previous_guidance: dict[str, Any]
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
    previous = state.get("previous_guidance") or {}
    previous_summary = {
        key: previous.get(key)
        for key in ("phase", "focus", "parent_facts", "unknowns", "next_step", "reminder", "script")
        if previous.get(key)
    }
    facts = "\n".join(
        f"- [{item['source']}] {item['text'][:500]}" for item in references[:4]
    ) or "尚无检索资料"
    training_mode = state.get("training_mode", "full")
    price_context = state.get("price_context") or {}
    price_mode_rules = (
        "当前是价格异议处理专项。已知事实优先记录客户明确说出的价格顾虑、预算限制、比较对象、价值关注和决策条件。"
        "价格顾虑是主线；比较对象和价格比较方面只在需要解释价格差异时使用，不要求客户每一轮都重复 A/B 比较。"
        "待了解优先列出尚未确认的价格顾虑原因、预算差距、费用构成、决策人、优惠条件或下一步承诺。"
        "下一步和话术应先帮助销售确认价格顾虑的真实原因，再讨论价值、方案、总成本或条件；不得直接建议降价，不得编造报价、竞品价格和优惠。"
        "如果已提供价格比较资料，需要比较时保持同一 A/B/C 品牌和同一价格比较方面，不要把单课时价格与总价混为一谈。"
        if training_mode == "price_objection" else ""
    )
    return [
        {"role": "system", "content": (
            "你是上海教培机构销售员工的SPIN实时教练。每完成一轮销售员与家长的来回，都必须根据最新一轮重新评估并更新侧栏。"
            "仅把家长明确说出的内容列为已知；未知信息放入待了解。不要把推测写成事实。"
            "将本轮家长新提供的信息加入已知事实，并从待了解中移除已回答项。即使本轮没有新事实，也要结合销售员刚才的提问或回应，调整焦点、下一步和提醒，不能原样重复上一轮。"
            "请为家长表达的真实顾虑给一个短、具体、可立即照做的提醒；没有明显问题就给正向下一步。"
            "如果对话明确涉及具体学校、课程、价格、校区、退费/请假规则，或需要引用话术依据，"
            "先调用 search_knowledge 检索；普通寒暄和一般沟通不检索。若与上次资料主题相同，沿用已有资料，不要重复检索；只有主题发生变化或此前资料明显不适用时才再次检索。拿到工具结果后再输出。"
            "只能引用检索结果；无结果时明确写‘知识库未找到相关资料’，禁止补造。"
            + price_mode_rules +
            "最终只输出JSON：{phase, focus, parent_facts:[...], unknowns:[...], next_step, reminder, script, references:[{source,text}], not_found}。"
            "focus/next_step/reminder/script简短且针对本轮。parent_facts和unknowns必须反映完整近期对话，不得丢弃仍有效的已知事实。references只能来自工具结果或传入的上一轮已核实资料。phase取Situation/Problem/Implication/Need-payoff之一。"
        )},
        {"role": "user", "content": f"这是第 {state.get('round_number', 0)} 轮完整对话。\n当前训练模式：{training_mode}\n当前阶段：{state.get('phase', 'discovery')}\n价格比较资料：{json.dumps(price_context, ensure_ascii=False) if price_context else '无'}\n上一轮侧栏：{json.dumps(previous_summary, ensure_ascii=False)}\n上次检索主题：{state.get('last_search_query') or '无'}\n最近对话：\n{state['transcript']}\n已核实资料：\n{facts}"},
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


def _normalize(result: dict[str, Any], training_mode: str = "full") -> dict[str, Any]:
    draft = result.get("draft") or {}
    refs = result.get("references") or []
    facts = draft.get("parent_facts") if isinstance(draft.get("parent_facts"), list) else []
    unknowns = draft.get("unknowns") if isinstance(draft.get("unknowns"), list) else []
    clean_refs = [{"source": str(ref.get("source", "知识库资料")), "text": str(ref.get("text", ""))[:600]}
                  for ref in refs if isinstance(ref, dict) and ref.get("text")]
    price_mode = training_mode == "price_objection"
    return {
        "phase": str(draft.get("phase") or "Situation")[:24],
        "focus": str(draft.get("focus") or ("确认客户在和什么相比以及真实价格差距" if price_mode else "继续倾听家长需求"))[:100],
        "parent_facts": [str(item)[:100] for item in facts[:6]],
        "unknowns": [str(item)[:100] for item in unknowns[:6]],
        "next_step": str(draft.get("next_step") or ("先确认客户说贵是比较预算、竞品还是价值不清楚" if price_mode else "用开放问题了解家长最关心的目标"))[:120],
        "reminder": str(draft.get("reminder") or ("不要直接降价或虚构优惠，先问清和什么相比、怎么收费" if price_mode else "先回应家长顾虑，再追问具体影响"))[:120],
        "script": str(draft.get("script") or ("您说价格偏高，主要是和预算比，还是和其他方案比？" if price_mode else "您最希望孩子这学期在哪方面有所进步？"))[:160],
        "references": clean_refs,
        "not_found": bool(result.get("search_attempted")) and not clean_refs,
        "searched": bool(result.get("search_attempted")),
        "search_error": bool(result.get("search_error")),
        "round_number": int(result.get("round_number") or 0),
        "last_search_query": result.get("last_search_query", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


async def update_guidance(session_id: str) -> dict[str, Any] | None:
    """Run a bounded tool-calling LangGraph agent and publish to the active socket."""
    from app.websocket.manager import manager, session_manager

    try:
        previous = getattr(manager, "_spin_guidance", {}).get(session_id, {})
        context = session_manager.get_context(session_id) or []
        recent = context[-20:]
        round_number = sum(1 for row in context if row.get("role") == "user")
        info = session_manager.get_session_info(session_id) or {}
        phase = info.get("current_phase") or "discovery"
        training_mode = (info.get("customer_context") or {}).get("training_mode", "full")
        preparation = (info.get("customer_context") or {}).get("preparation") or {}
        price_context = {
            key: preparation.get(key, "")
            for key in ("price_brand_a", "price_brand_b", "price_brand_c", "price_comparison_aspect", "price_concern")
            if preparation.get(key)
        }
        customer_label = "客户" if training_mode == "price_objection" else "家长"
        transcript = "\n".join(
            f"{customer_label if row.get('role') == 'ai' else '销售'}：{str(row.get('content') or '')[:420]}"
            for row in recent if row.get("role") in ("user", "ai", "assistant")
        )[-6000:]
        result = await _graph.ainvoke({
                                        "transcript": transcript,
                                        "phase": phase,
                                        "training_mode": training_mode,
                                        "price_context": price_context,
                                        "round_number": round_number,
                                        "previous_guidance": previous,
                                        "references": previous.get("references", []),
                                        "last_search_query": previous.get("last_search_query", ""),
                                    },
                                      config={"recursion_limit": 5})
        guidance = _normalize(result, training_mode)
        states = getattr(manager, "_spin_guidance", None)
        if states is None:
            manager._spin_guidance = states = {}
        states[session_id] = guidance
        await manager.send_message(session_id, {"type": "spin_guidance", "data": guidance})
        return guidance
    except Exception:
        logger.exception("SPIN guidance update failed for session")
        return None
