"""对练里程碑：让对话能跨过"约好试听 → 试听已结束 → 报名"这条时间线。

问题：AI 扮演的家长每轮只拿到一份静态人设 + 最近几条对话，
对话推进到"约好试听"之后就卡住了 —— 在家长的认知里试听还没发生，
学员无法继续谈试听反馈和报名。

做法：
1. 规则检测家长是否已答应某个里程碑动作（试听 / 测评），标记为 agreed；
2. 学员在侧栏确认"已完成"并选择结果（三档），标记为 completed；
3. 把已完成的事件渲染成"世界状态"，每轮注入人设提示词；
4. 未完成的事件只按"还没发生"来扮演，避免 AI 穿越。

本模块只做纯规则与文本渲染，不访问网络与数据库。
"""

from __future__ import annotations

import re
from typing import Any

# 状态
STATUS_PENDING = "pending"
STATUS_AGREED = "agreed"
STATUS_COMPLETED = "completed"

QUESTION_MARKERS = ("?", "？", "怎么", "如何", "多少", "什么", "哪", "几", "吗", "多久", "是不是")
AGREEMENT_MARKERS = ("约", "定", "可以", "行", "吧", "就", "方便")

_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub("", text or "")


# ---------------------------------------------------------------------------
# 里程碑定义（试听 + 测评，其余后续按同样结构追加）
# ---------------------------------------------------------------------------

MILESTONES: dict[str, dict[str, Any]] = {
    "trial": {
        "id": "trial",
        "label": "试听",
        "title": "待办事件 · 试听",
        "agree_terms": ("试听", "体验课"),
        "outcomes": [
            {"value": "satisfied", "label": "试听满意"},
            {"value": "neutral", "label": "试听一般"},
            {"value": "unsatisfied", "label": "试听不满意"},
        ],
        "narratives": {
            "satisfied": "三天前家长带孩子上了试听课，反馈很满意：老师讲得清楚，孩子说能听懂。",
            "neutral": "三天前家长带孩子上了试听课，反馈一般：能听懂，但觉得和学校讲的差不多。",
            "unsatisfied": "三天前家长带孩子上了试听课，反馈不满意：觉得内容偏浅、节奏不太合适。",
        },
        "stance": {
            "satisfied": "你现在认可课程，主要顾虑转到价格和接送距离上。",
            "neutral": "你还在观望，想再确认效果和师资，暂时不会主动提报名。",
            "unsatisfied": "你对效果有疑虑，需要对方解释清楚才可能继续。",
        },
    },
    "assessment": {
        "id": "assessment",
        "label": "班型测评",
        "title": "待办事件 · 班型测评",
        "agree_terms": ("测评", "测试", "摸底", "诊断"),
        "outcomes": [
            {"value": "matched", "label": "评估达标"},
            {"value": "gap", "label": "差距较大"},
            {"value": "weak", "label": "需要加强"},
        ],
        "narratives": {
            "matched": "两天前孩子做了班型测评，结果达标：基础不错，可以直接进进阶班。",
            "gap": "两天前孩子做了班型测评，结果差距较大：需要先补基础，再考虑进班。",
            "weak": "两天前孩子做了班型测评，结论是需要加强训练，具体薄弱点老师已给出。",
        },
        "stance": {
            "matched": "你现在关心的是能不能排上合适的班、老师怎么配。",
            "gap": "你有些犹豫，担心补基础周期太长、花钱多。",
            "weak": "你想知道要补多久、有没有把握提上去。",
        },
    },
}

OUTCOME_LABELS = {
    outcome["value"]: outcome["label"]
    for milestone in MILESTONES.values()
    for outcome in milestone["outcomes"]
}


# ---------------------------------------------------------------------------
# 状态读写（存在 deal_state 的 flags.milestones 里，避免改表结构）
# ---------------------------------------------------------------------------


def _bucket(flags: dict[str, Any]) -> dict[str, Any]:
    milestones = flags.get("milestones")
    if not isinstance(milestones, dict):
        milestones = {}
        flags["milestones"] = milestones
    return milestones


def get_status(flags: dict[str, Any], milestone_id: str) -> str:
    entry = _bucket(flags).get(milestone_id) or {}
    return str(entry.get("status") or STATUS_PENDING)


def get_result(flags: dict[str, Any], milestone_id: str) -> str | None:
    entry = _bucket(flags).get(milestone_id) or {}
    value = entry.get("result")
    return value if isinstance(value, str) else None


def completed_ids(flags: dict[str, Any]) -> list[str]:
    return [mid for mid in MILESTONES if get_status(flags, mid) == STATUS_COMPLETED]


def summary(flags: dict[str, Any]) -> dict[str, Any]:
    return {
        mid: {
            "status": get_status(flags, mid),
            "result": get_result(flags, mid),
            "at_round": (_bucket(flags).get(mid) or {}).get("at_round"),
        }
        for mid in MILESTONES
    }


# ---------------------------------------------------------------------------
# 检测：家长是否已经答应了某个动作
# ---------------------------------------------------------------------------


def _is_agreement(parent_text: str, terms: tuple[str, ...]) -> bool:
    text = _norm(parent_text)
    if not text:
        return False
    if not any(term in text for term in terms):
        return False
    asking = any(marker in text for marker in QUESTION_MARKERS)
    agreed = any(marker in text for marker in AGREEMENT_MARKERS)
    return not (asking and not agreed)


def detect(flags: dict[str, Any], parent_text: str, *, round_number: int) -> list[str]:
    """检测家长是否答应了某个里程碑动作；返回本轮新变成 agreed 的 id。"""
    changed: list[str] = []
    if not parent_text:
        return changed
    bucket = _bucket(flags)
    for milestone_id, definition in MILESTONES.items():
        entry = bucket.get(milestone_id) or {}
        if entry.get("status") in (STATUS_AGREED, STATUS_COMPLETED):
            continue
        if _is_agreement(parent_text, definition["agree_terms"]):
            bucket[milestone_id] = {
                "status": STATUS_AGREED,
                "result": None,
                "at_round": int(round_number),
            }
            changed.append(milestone_id)
    return changed


def complete(flags: dict[str, Any], milestone_id: str, outcome: str) -> dict[str, Any]:
    """标记里程碑已完成；返回更新后的 flags（原地修改并返回）。"""
    definition = MILESTONES.get(milestone_id)
    if definition is None:
        raise ValueError(f"unknown milestone: {milestone_id}")
    valid = {item["value"] for item in definition["outcomes"]}
    if outcome not in valid:
        raise ValueError(f"unknown outcome for {milestone_id}: {outcome}")
    bucket = _bucket(flags)
    entry = bucket.get(milestone_id) or {}
    entry.update({"status": STATUS_COMPLETED, "result": outcome})
    bucket[milestone_id] = entry
    return flags


def reopen(flags: dict[str, Any], milestone_id: str) -> dict[str, Any]:
    """撤销完成，回到"已约定"（用于点错了改期重来）。"""
    if milestone_id not in MILESTONES:
        raise ValueError(f"unknown milestone: {milestone_id}")
    bucket = _bucket(flags)
    entry = bucket.get(milestone_id) or {}
    entry.update({"status": STATUS_AGREED, "result": None})
    bucket[milestone_id] = entry
    return flags


def pending_event(flags: dict[str, Any]) -> dict[str, Any] | None:
    """给前端的待办事件卡：取第一个"已约定但未完成"的里程碑。"""
    bucket = _bucket(flags)
    for milestone_id, definition in MILESTONES.items():
        if (bucket.get(milestone_id) or {}).get("status") != STATUS_AGREED:
            continue
        return {
            "id": milestone_id,
            "title": definition["title"],
            "description": f"家长已经答应{definition['label']}，完成后选一下结果",
            "outcomes": definition["outcomes"],
        }
    return None


# ---------------------------------------------------------------------------
# 渲染：注入人设的"世界状态"
# ---------------------------------------------------------------------------


def render_world_state(flags: dict[str, Any]) -> str:
    """把已完成/已约定的里程碑渲染成提示词片段。

    必须每轮注入：只靠对话历史，模型几分钟后就会"忘掉"试听已经发生过。
    """
    bucket = _bucket(flags)
    completed_lines: list[str] = []
    agreed_lines: list[str] = []
    for milestone_id, definition in MILESTONES.items():
        entry = bucket.get(milestone_id) or {}
        status = entry.get("status")
        if status == STATUS_COMPLETED and entry.get("result"):
            narrative = definition["narratives"].get(entry["result"], "")
            stance = definition["stance"].get(entry["result"], "")
            if narrative:
                completed_lines.append(f"- {narrative}{stance}")
        elif status == STATUS_AGREED:
            agreed_lines.append(f"- 你已经答应{definition['label']}，但这件事**还没发生**，你现在还没体验过。")

    if not completed_lines and not agreed_lines:
        return ""

    parts = ["\n【已经发生的事｜决定你现在的心态】"]
    parts.extend(completed_lines)
    if agreed_lines:
        parts.append("【还没发生的事】")
        parts.extend(agreed_lines)
        parts.append("规则：没发生的事你不能描述细节、不能编造体验；学员说到相关话题时，你只能说还没去/还在等。")
    if completed_lines:
        parts.append("规则：已经发生的事你要记得，不要反问学员「什么时候去」，也不要再说「我还没去过」。")
    return "\n".join(parts)


def render_system_notice(milestone_id: str, outcome: str) -> str:
    """对话里插入的灰色提示文案。"""
    definition = MILESTONES.get(milestone_id)
    if definition is None:
        return ""
    label = OUTCOME_LABELS.get(outcome, outcome)
    return f"⏩ 时间推进 · {definition['label']}已完成（{label}）"
