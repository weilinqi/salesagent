"""DeepAgent 形态的对练推进分析图。

编排（每轮对话后执行一次）：

    plan ──► extract ──► judge ──► END
      └──────────────────► judge

- ``plan``   决定本轮是否需要抽取（没有家长新话就直接跳到判定）
- ``extract``专职子代理：只做"从本轮新增对话里抽结构化事实"，一次 LLM 调用
- ``judge``  纯规则：合并槽位、算覆盖率、判阶段、判是否该收尾

设计取舍：阶段与收尾的判定**不交给模型**，只由 ``deal_state`` 的规则决定，
避免每轮重新生成导致的漂移；模型只负责它擅长的事实抽取。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.services.conversation import deal_state
from app.services.conversation.deal_templates import get_template, resolve_template_id
from app.services.llm import get_minimax_service

logger = logging.getLogger(__name__)

# 单轮抽取消耗上限，超时即放弃本轮抽取但保留规则判定
EXTRACT_TIMEOUT_SECONDS = 20
# 一次送给抽取器的最大字符数（只送本轮新增，通常远小于此）
MAX_NEW_CHARS = 4000


class DealGraphState(TypedDict, total=False):
    template_id: str
    slots: dict[str, Any]
    flags: dict[str, Any]
    stage: str
    round_number: int
    new_messages: list[dict[str, str]]
    extracted: dict[str, Any]
    error: str


def _json_object(text: str) -> dict[str, Any]:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError("deal extractor returned no JSON")
    return json.loads(match.group())


def _schema_for_prompt(template_id: str) -> dict[str, str]:
    template = get_template(template_id)
    return {slot["key"]: slot["hint"] for slot in template["slots"]}


def _extract_prompt(state: DealGraphState) -> list[dict[str, str]]:
    schema = _schema_for_prompt(state.get("template_id") or "")
    transcript = "\n".join(
        f"{'家长' if row.get('role') == 'parent' else '销售'}：{row.get('content', '')[:420]}"
        for row in (state.get("new_messages") or [])
    )[:MAX_NEW_CHARS]
    existing = {
        key: entry.get("value")
        for key, entry in (state.get("slots") or {}).items()
        if isinstance(entry, dict) and entry.get("value")
    }
    return [
        {"role": "system", "content": (
            "你是教培机构销售对练的信息抽取器。只做抽取，不做分析、不做建议。\n"
            "规则：\n"
            "1. 只抽取【家长】明确说出的内容，销售员的话不算事实。\n"
            "2. 每个字段必须给出 evidence：家长原话片段（不超过 50 字）。找不到原话就留空，禁止推断。\n"
            "3. 数字、年级、分数、科目名保持原样，不要换算、不要补全。\n"
            "4. 家长改口时输出 revised=true，否则省略该字段。\n"
            "5. 已经收集且家长没有改口的字段不要重复输出。\n"
            "只输出 JSON，形如："
            '{"slots":{"student_grade":{"value":"初二","evidence":"现在初二是吧"}}}'
            f"\n待抽取字段及含义：{json.dumps(schema, ensure_ascii=False)}"
            f"\n已收集（勿重复输出）：{json.dumps(existing, ensure_ascii=False)}"
        )},
        {"role": "user", "content": f"本轮新增对话：\n{transcript}"},
    ]


async def _plan(state: DealGraphState) -> dict[str, Any]:
    """只有出现家长新话时才值得调用抽取器。"""
    new_messages = state.get("new_messages") or []
    has_parent = any(row.get("role") == "parent" and row.get("content") for row in new_messages)
    if not has_parent:
        return {"extracted": {}}
    return {}


def _needs_extract(state: DealGraphState) -> str:
    return "extract" if "extracted" not in state else "judge"


async def _extract(state: DealGraphState) -> dict[str, Any]:
    try:
        response = await asyncio.wait_for(
            get_minimax_service().chat(
                _extract_prompt(state),
                model="MiniMax-M3",
                temperature=0.1,
                max_tokens=700,
            ),
            timeout=EXTRACT_TIMEOUT_SECONDS,
        )
        payload = _json_object(response)
        slots = payload.get("slots") if isinstance(payload.get("slots"), dict) else {}
        return {"extracted": slots}
    except asyncio.TimeoutError:
        logger.warning("deal extractor timed out")
        return {"extracted": {}, "error": "timeout"}
    except Exception as exc:  # noqa: BLE001 - 抽取失败不应中断对练
        logger.warning("deal extractor failed: %s", type(exc).__name__)
        return {"extracted": {}, "error": type(exc).__name__}


def _judge(state: DealGraphState) -> dict[str, Any]:
    """纯规则结算：合并槽位 → 覆盖率 → 阶段。"""
    return {}


_builder = StateGraph(DealGraphState)
_builder.add_node("plan", _plan)
_builder.add_node("extract", _extract)
_builder.add_node("judge", _judge)
_builder.add_edge(START, "plan")
_builder.add_conditional_edges("plan", _needs_extract, {"extract": "extract", "judge": "judge"})
_builder.add_edge("extract", "judge")
_builder.add_edge("judge", END)
_graph = _builder.compile()


# ---------------------------------------------------------------------------
# 会话侧编排
# ---------------------------------------------------------------------------


def _split_messages(context: list[dict[str, Any]], start: int) -> list[dict[str, str]]:
    """把会话上下文切成抽取器要的 parent/sales 两种角色。"""
    rows: list[dict[str, str]] = []
    for row in context[start:]:
        role = row.get("role")
        content = str(row.get("content") or "").strip()
        if not content or role not in ("user", "ai", "assistant"):
            continue
        rows.append({"role": "parent" if role in ("ai", "assistant") else "sales", "content": content})
    return rows


def _latest_parent_text(new_messages: list[dict[str, str]]) -> str:
    for row in reversed(new_messages):
        if row.get("role") == "parent":
            return row.get("content", "")
    return ""


async def analyze_session(session_id: str) -> dict[str, Any] | None:
    """跑一轮对练推进分析，持久化并通过 WebSocket 推送。"""
    from app.websocket.manager import manager, session_manager

    try:
        context = session_manager.get_context(session_id) or []
        info = session_manager.get_session_info(session_id) or {}

        cached = getattr(manager, "_deal_states", None)
        if not isinstance(cached, dict):
            manager._deal_states = cached = {}
        state = dict(cached.get(session_id) or {})
        if not state:
            # 后端重启后内存缓存是空的，先把上次落库的槽位捞回来，
            # 否则已经问到的信息会凭空清零（看板覆盖率先涨后掉）
            state = dict(load_state(session_id) or {})
        if not state:
            state = deal_state.new_state(
                resolve_template_id(
                    deal_state.extract_grade_token(info.get("customer_grade") or ""),
                    str((info.get("customer_context") or {}).get("preparation") or ""),
                )
            )

        processed = int(state.get("processed_index") or 0)
        if processed > len(context):
            processed = 0
        new_messages = _split_messages(context, processed)

        round_number = sum(1 for row in context if row.get("role") == "user")
        parent_turns = sum(1 for row in context if row.get("role") in ("ai", "assistant"))
        parent_text = "\n".join(row["content"] for row in new_messages if row["role"] == "parent")
        sales_text = "\n".join(row["content"] for row in new_messages if row["role"] == "sales")

        result = await asyncio.wait_for(
            _graph.ainvoke({
                "template_id": state.get("template_id"),
                "slots": state.get("slots") or {},
                "flags": state.get("flags") or {},
                "stage": state.get("stage", "opening"),
                "round_number": round_number,
                "new_messages": new_messages,
            }),
            timeout=EXTRACT_TIMEOUT_SECONDS + 10,
        )

        slots, changed = deal_state.merge_slots(
            state.get("slots") or {}, result.get("extracted") or {}, round_number
        )
        flags = deal_state.update_flags(
            state.get("flags") or {},
            parent_turns=parent_turns,
            parent_text=parent_text,
            sales_text=sales_text,
        )
        stage = deal_state.compute_stage(state.get("stage", "opening"), slots, flags)
        coverage = deal_state.compute_coverage(slots, state.get("template_id"))
        closing = deal_state.detect_closing(
            {"stage": stage, "round_number": round_number, "last_gain_round": state.get("last_gain_round", 0)},
            slot_delta_count=len(changed),
            coverage=coverage,
            latest_parent_text=parent_text,
        )

        state.update({
            "slots": slots,
            "flags": flags,
            "stage": stage,
            "round_number": round_number,
            "processed_index": len(context),
            "last_gain_round": round_number if changed else state.get("last_gain_round", 0),
            "closing": closing,
            "updated_at": deal_state._now(),
        })
        cached[session_id] = state

        session_manager.update_phase(session_id, stage)
        # SQLite 写入放到线程里，避免阻塞事件循环（否则整个服务会卡住不响应）
        await asyncio.to_thread(_persist, session_id, state)
        payload = deal_state.build_progress_payload(state)
        await manager.send_message(session_id, {"type": "deal_progress", "data": payload})
        return payload

    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("deal analysis failed for session")
        return None


def _persist(session_id: str, state: dict[str, Any]) -> None:
    """写回 practice_deal_states；失败只记日志，不影响对练。"""
    try:
        from app.database import SessionLocal
        from app.models.practice import PracticeDealState

        db = SessionLocal()
        try:
            row = db.query(PracticeDealState).filter(PracticeDealState.session_id == session_id).first()
            coverage = deal_state.compute_coverage(state.get("slots") or {}, state.get("template_id"))
            if row is None:
                row = PracticeDealState(session_id=session_id)
                db.add(row)
            row.template_id = state.get("template_id")
            row.stage = state.get("stage")
            row.slots = state.get("slots") or {}
            row.flags = state.get("flags") or {}
            row.coverage_pct = coverage["percent"]
            row.closing = state.get("closing") or {}
            row.deal_result = state.get("deal_result")
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.warning("deal state persist failed", exc_info=True)


def load_state(session_id: str) -> dict[str, Any] | None:
    """优先读内存，其次读数据库。"""
    from app.websocket.manager import manager

    cached = getattr(manager, "_deal_states", None)
    if isinstance(cached, dict) and cached.get(session_id):
        return cached[session_id]
    try:
        from app.database import SessionLocal
        from app.models.practice import PracticeDealState

        db = SessionLocal()
        try:
            row = db.query(PracticeDealState).filter(PracticeDealState.session_id == session_id).first()
            if row is None:
                return None
            state = deal_state.new_state(row.template_id)
            state.update({
                "stage": row.stage or "opening",
                "slots": row.slots or {},
                "flags": row.flags or {},
                "closing": row.closing or {},
                "deal_result": row.deal_result,
            })
            return state
        finally:
            db.close()
    except Exception:
        logger.warning("deal state load failed", exc_info=True)
        return None


def finalize(session_id: str, explicit_result: str | None = None) -> dict[str, Any]:
    """结束时结算结单结果并落库。"""
    state = load_state(session_id) or deal_state.new_state()
    coverage = deal_state.compute_coverage(state.get("slots") or {}, state.get("template_id"))
    result = explicit_result or deal_state.finalize_result(state, coverage)
    state["deal_result"] = result
    state["updated_at"] = deal_state._now()
    from app.websocket.manager import manager

    cached = getattr(manager, "_deal_states", None)
    if isinstance(cached, dict):
        cached[session_id] = state
    _persist(session_id, state)
    payload = deal_state.build_progress_payload(state)
    return payload
