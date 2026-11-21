"""对练推进状态：槽位合并、覆盖率、阶段判定、结单判定。

本模块只做**纯函数**计算，不碰网络与数据库，便于单元测试。
LLM 只负责抽取事实（见 ``deal_graph``），所有"还差什么 / 走到哪一步 / 该不该收尾"
都由这里的规则决定，从而避免模型漂移。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.services.conversation.deal_templates import (
    REQUIRED,
    STAGE_LABELS,
    STAGE_ORDER,
    get_template,
    resolve_template_id,
)

# 销售员话术中出现这些词视为"已介绍课程/方案"
COURSE_TERMS = (
    "我们有个", "我们这边", "课程", "班型", "一对一", "小班", "课时", "课时费",
    "老师", "师资", "试听", "体验课", "校区", "上课时间", "教材", "提分方案",
    "教学计划", "辅导方案", "梳理", "集训", "冲刺班", "基础班", "培优",
)

# 家长表达异议的信号
OBJECTION_TERMS = (
    "太贵", "贵", "钱", "预算", "考虑", "再想", "商量", "远", "没时间", "时间冲突",
    "有用吗", "效果", "怕", "不愿意", "不想", "孩子不愿意", "别人家",
)

# 结单结果信号（只从家长的话里判断）
RESULT_SIGNALS: list[tuple[str, tuple[str, ...]]] = [
    ("won", ("报名", "缴费", "交钱", "刷卡", "就定你们", "定下来了", "什么时候开课", "签合同")),
    ("trial", ("试听", "体验课", "来上一节", "安排一节课")),
    ("lost_explicit", ("不需要", "不考虑", "不报了", "不学了", "别打了", "没兴趣", "算了")),
    ("lost_soft", ("再想想", "商量", "回去说", "考虑一下", "过几天", "问一下他爸", "问一下他妈")),
]

RESULT_LABELS = {
    "won": "成交",
    "trial": "约了试听",
    "lost_explicit": "明确拒绝",
    "lost_soft": "考虑中（可跟进）",
    "incomplete": "提前终止",
}

# 覆盖率低于该值就结束时，记为"提前终止"
INCOMPLETE_THRESHOLD = 60
# 连续多少轮没有新信息就建议收尾
STALE_ROUNDS = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 状态构造
# ---------------------------------------------------------------------------


def new_state(template_id: str | None = None) -> dict[str, Any]:
    template_id = template_id or resolve_template_id()
    return {
        "template_id": template_id,
        "stage": "opening",
        "slots": {},
        "round_number": 0,
        "last_gain_round": 0,
        "flags": {"parent_turns": 0, "course_introduced": False, "objection_raised": False},
        "deal_result": None,
        "updated_at": _now(),
    }


def slot_value(slots: dict[str, Any], key: str) -> str:
    entry = slots.get(key) or {}
    value = entry.get("value")
    return value.strip() if isinstance(value, str) else ""


def is_filled(slots: dict[str, Any], key: str) -> bool:
    return bool(slot_value(slots, key))


# ---------------------------------------------------------------------------
# 槽位合并（只增不删，改口需证据）
# ---------------------------------------------------------------------------


def merge_slots(
    existing: dict[str, Any],
    delta: dict[str, Any],
    round_number: int,
) -> tuple[dict[str, Any], list[str]]:
    """把抽取结果合并进已有槽位。

    规则：
    - 空值不覆盖已有值；
    - 没有 ``evidence`` 的值一律丢弃（防幻觉）；
    - ``revised=true`` 时才允许覆盖，并记录 ``revised_at``。

    返回 (合并后的槽位, 本轮新增/更新的 key 列表)。
    """
    merged = {key: dict(value) for key, value in (existing or {}).items() if isinstance(value, dict)}
    changed: list[str] = []
    for key, raw in (delta or {}).items():
        if not isinstance(raw, dict):
            continue
        value = raw.get("value")
        evidence = raw.get("evidence")
        if not isinstance(value, str) or not value.strip():
            continue
        if not isinstance(evidence, str) or not evidence.strip():
            # 没有原文证据的抽取结果不可信
            continue
        value = value.strip()[:200]
        evidence = evidence.strip()[:120]
        previous = merged.get(key) or {}
        if previous.get("value") and not raw.get("revised"):
            continue
        merged[key] = {
            "value": value,
            "evidence": evidence,
            "round": int(round_number),
            "revised": bool(raw.get("revised")),
        }
        changed.append(key)
    return merged, changed


# ---------------------------------------------------------------------------
# 覆盖率与缺口
# ---------------------------------------------------------------------------


def compute_coverage(slots: dict[str, Any], template_id: str) -> dict[str, int]:
    template = get_template(template_id)
    required = [slot for slot in template["slots"] if slot["level"] == REQUIRED]
    recommended = [slot for slot in template["slots"] if slot["level"] != REQUIRED]
    required_filled = sum(1 for slot in required if is_filled(slots, slot["key"]))
    recommended_filled = sum(1 for slot in recommended if is_filled(slots, slot["key"]))
    percent = round(required_filled * 100 / len(required)) if required else 0
    return {
        "required_total": len(required),
        "required_filled": required_filled,
        "recommended_total": len(recommended),
        "recommended_filled": recommended_filled,
        "percent": percent,
    }


def compute_gaps(
    slots: dict[str, Any],
    template_id: str,
    stage: str,
    limit: int = 4,
) -> list[dict[str, str]]:
    """按"当前阶段优先、必填优先"排序的待了解清单。"""
    template = get_template(template_id)
    stage_index = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else 0
    pending: list[tuple[int, int, dict[str, Any]]] = []
    for slot in template["slots"]:
        if is_filled(slots, slot["key"]):
            continue
        slot_stage = slot.get("stage", "discovery")
        slot_index = STAGE_ORDER.index(slot_stage) if slot_stage in STAGE_ORDER else 0
        # 当前阶段及之前没收齐的最紧急
        distance = 0 if slot_index <= stage_index else slot_index - stage_index
        level_rank = 0 if slot["level"] == REQUIRED else 1
        pending.append((distance, level_rank, slot))
    pending.sort(key=lambda item: (item[0], item[1]))
    return [
        {
            "key": slot["key"],
            "label": slot["label"],
            "ask": slot["ask"],
            "level": slot["level"],
            "stage": slot.get("stage", "discovery"),
        }
        for _, _, slot in pending[:limit]
    ]


def slot_board(slots: dict[str, Any], template_id: str) -> list[dict[str, Any]]:
    """给前端渲染的完整槽位表。"""
    template = get_template(template_id)
    board = []
    for slot in template["slots"]:
        value = slot_value(slots, slot["key"])
        board.append({
            "key": slot["key"],
            "label": slot["label"],
            "level": slot["level"],
            "stage": slot.get("stage", "discovery"),
            "filled": bool(value),
            "value": value or None,
        })
    return board


# ---------------------------------------------------------------------------
# 阶段推进（门槛制，每轮最多推进一阶，允许跳过没发生的异议阶段）
# ---------------------------------------------------------------------------


def _gate(stage_index: int, slots: dict[str, Any], flags: dict[str, Any]) -> bool:
    """进入 ``STAGE_ORDER[stage_index]`` 需要满足的条件。"""
    if stage_index <= 0:
        return True
    if stage_index == 1:  # discovery
        return int(flags.get("parent_turns") or 0) >= 1
    if stage_index == 2:  # diagnosis
        return all(is_filled(slots, key) for key in ("student_grade", "weak_subjects", "target_subject"))
    if stage_index == 3:  # solution
        return all(is_filled(slots, key) for key in ("current_score", "pain_point", "target_goal"))
    if stage_index == 4:  # objection
        return bool(flags.get("course_introduced")) and is_filled(slots, "preferred_format")
    if stage_index == 5:  # closing
        handled_objection = bool(flags.get("objection_raised")) and bool(flags.get("course_introduced"))
        ready_to_close = bool(flags.get("course_introduced")) and is_filled(slots, "budget_range")
        return handled_objection or ready_to_close
    return False


def compute_stage(
    current: str,
    slots: dict[str, Any],
    flags: dict[str, Any],
) -> str:
    """返回本轮应有的阶段，最多前进一阶，绝不回退。"""
    current_index = STAGE_ORDER.index(current) if current in STAGE_ORDER else 0
    target_index = current_index
    for index in range(current_index + 1, len(STAGE_ORDER)):
        if _gate(index, slots, flags):
            target_index = index
        else:
            break

    no_objection = not flags.get("objection_raised")
    # 家长从没提异议时，允许跳过异议处理直接进入收尾
    if no_objection and target_index >= 5:
        return "closing"
    # 没提异议就不要停在异议阶段空转
    if no_objection and target_index == 4:
        target_index = current_index
    return STAGE_ORDER[min(target_index, current_index + 1)]


def update_flags(flags: dict[str, Any], *, parent_turns: int, parent_text: str, sales_text: str) -> dict[str, Any]:
    updated = dict(flags or {})
    updated["parent_turns"] = int(parent_turns)
    if sales_text and any(term in sales_text for term in COURSE_TERMS):
        updated["course_introduced"] = True
    if parent_text and any(term in parent_text for term in OBJECTION_TERMS):
        updated["objection_raised"] = True
    return updated


# ---------------------------------------------------------------------------
# 结单判定
# ---------------------------------------------------------------------------


def detect_result(parent_text: str) -> str | None:
    """从家长最新话术判断结单结果，判断不出返回 None。"""
    if not parent_text:
        return None
    for result, words in RESULT_SIGNALS:
        if any(word in parent_text for word in words):
            return result
    return None


def detect_closing(
    state: dict[str, Any],
    slot_delta_count: int,
    coverage: dict[str, int],
    latest_parent_text: str,
) -> dict[str, Any]:
    """判断是否该建议收尾。**只建议，不自动结束。**"""
    stage = state.get("stage", "opening")
    round_number = int(state.get("round_number") or 0)
    last_gain = int(state.get("last_gain_round") or 0)

    result = detect_result(latest_parent_text)
    if result:
        return {"suggest": True, "reason": f"家长已表态：{RESULT_LABELS[result]}", "result": result}

    if stage == "closing" and coverage["percent"] >= 90:
        return {
            "suggest": True,
            "reason": f"关键信息已收集 {coverage['required_filled']}/{coverage['required_total']}，可以尝试收尾",
            "result": None,
        }

    stale = round_number - last_gain
    if round_number >= 12 and stale >= STALE_ROUNDS and slot_delta_count == 0:
        return {
            "suggest": True,
            "reason": f"最近 {stale} 轮没有新信息，建议主动收尾",
            "result": None,
        }

    return {"suggest": False, "reason": None, "result": None}


def finalize_result(state: dict[str, Any], coverage: dict[str, int]) -> str:
    """会话结束时定结单结果；没有明确表态且信息不足记为 incomplete。"""
    for closing in (state.get("closing") or {}),:
        if isinstance(closing, dict) and closing.get("result"):
            return str(closing["result"])
    if coverage["percent"] < INCOMPLETE_THRESHOLD:
        return "incomplete"
    return "lost_soft"


# ---------------------------------------------------------------------------
# 前端载荷
# ---------------------------------------------------------------------------


def build_progress_payload(state: dict[str, Any]) -> dict[str, Any]:
    template_id = state.get("template_id")
    slots = state.get("slots") or {}
    stage = state.get("stage", "opening")
    coverage = compute_coverage(slots, template_id)
    return {
        "template_id": template_id,
        "template_name": get_template(template_id)["name"],
        "stage": stage,
        "stage_label": STAGE_LABELS.get(stage, stage),
        "stage_order": STAGE_ORDER,
        "stage_labels": STAGE_LABELS,
        "coverage": coverage,
        "slots": slot_board(slots, template_id),
        "gaps": compute_gaps(slots, template_id, stage),
        "closing": state.get("closing") or {"suggest": False, "reason": None, "result": None},
        "deal_result": state.get("deal_result"),
        "round_number": int(state.get("round_number") or 0),
        "updated_at": state.get("updated_at") or _now(),
    }


def infer_template_from_context(*texts: str | None) -> str:
    return resolve_template_id(*texts)


def extract_grade_token(text: str) -> str:
    """从文本里抓年级词，供模板推断使用。"""
    match = re.search(r"(小学|初中|高中|高[一二三]|初[一二三]|[一二三四五六七八九]年级|七|八|九年级)", text or "")
    return match.group(0) if match else ""
