"""对话账本：让扮演家长的一方"记得"自己问过什么、对方答了什么。

问题背景
--------
实时对练里 AI 扮演家长，每轮只拿到最近 10 条消息与一份**静态**人设提示词。
人设里的"顾虑/痛点"每轮都会重新出现在 prompt 里，而"这个顾虑已经被答复过"
这件事没有任何地方记录，于是模型会反复问同一件事（例如"试听课怎么安排"）。

做法
----
不增加 LLM 调用，用关键词主题表把整段对话回放一遍，得到一份结构化账本：

- 家长问过哪些**主题**（试听/价格/课时/师资/校区/效果/退费/班型/教材/报名）
- 每个主题是哪一轮问的、销售有没有答复、答复了什么
- 家长已经自述过的信息（来自对练推进模型抽取的槽位）

再把账本渲染成一小段提示词注入 system prompt，明确告诉模型：
"这些已经问过并得到答复，不要再问第二遍"。
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# 主题表：键是稳定 id，值是中文标签 + 命中关键词
TOPIC_DEFS: dict[str, tuple[str, tuple[str, ...]]] = {
    "trial": ("试听安排", ("试听", "体验课", "旁听", "来听一节课")),
    "price": ("价格费用", ("价格", "多少钱", "费用", "学费", "报价", "收费", "贵不贵", "一学期多少")),
    "schedule": ("上课时间", ("上课时间", "课时", "几点", "时间安排", "排课", "周末上", "平日晚上")),
    "teacher": ("师资情况", ("老师", "师资", "教师", "谁教", "教龄", "在职老师")),
    "campus": ("校区位置", ("校区", "地址", "在哪", "离得远", "远不远", "哪个校区")),
    "effect": ("提分效果", ("效果", "提分", "能提高", "管用", "有用吗", "进步")),
    "refund": ("退费规则", ("退费", "退款", "不满意", "不想学了")),
    "format": ("班型设置", ("班型", "一对一", "小班", "大班", "几个人")),
    "material": ("教材资料", ("教材", "资料", "讲义", "练习册")),
    "enroll": ("报名流程", ("报名", "怎么报", "流程", "缴费", "定金")),
}

TOPIC_LABELS = {key: value[0] for key, value in TOPIC_DEFS.items()}

# 中文疑问信号：有这些词或问号才算"提问"
QUESTION_MARKERS = (
    "?", "？", "怎么", "如何", "多少", "什么", "哪", "谁", "有没有", "能不能",
    "可以吗", "多久", "几个", "是不是", "几节", "几次",
)

_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub("", text or "")


def is_question(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    return any(marker in normalized for marker in QUESTION_MARKERS)


# 销售"反问/索取信息"的信号：这类回复不算答复了上一个问题
INFO_REQUEST_MARKERS = (
    "？", "?", "说说", "您先", "方便", "请问", "能不能先", "先了解", "介绍一下",
    "几年级", "多大", "哪个学校",
)


def is_info_request(text: str) -> bool:
    """销售这句是在问信息，而不是在回答，因此不能算作"已答复"。"""
    normalized = _normalize(text)
    if not normalized:
        return True
    return any(marker in normalized for marker in INFO_REQUEST_MARKERS)


def detect_topics(text: str) -> list[str]:
    """返回文本命中的主题 id，按 TOPIC_DEFS 顺序。"""
    normalized = _normalize(text)
    if not normalized:
        return []
    found = []
    for topic, (_, words) in TOPIC_DEFS.items():
        if any(word in normalized for word in words):
            found.append(topic)
    return found


def _clip(text: str, limit: int = 80) -> str:
    text = _WHITESPACE.sub(" ", (text or "").strip())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_ledger(context: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """回放整段对话，生成主题账本。

    ``context`` 里 ``user`` 是销售员，``ai``/``assistant`` 是扮演的家长。
    返回 ``{"asked": [...], "unanswered": [...], "rounds": int}``。
    """
    asked: list[dict[str, Any]] = []
    by_topic: dict[str, dict[str, Any]] = {}
    round_number = 0
    # 家长刚问过问题、还没等到销售的下一句
    awaiting_reply = False
    # 最近一次家长提问的主题（用于本轮提醒）
    last_asked: dict[str, Any] | None = None

    for row in context or []:
        role = row.get("role")
        content = str(row.get("content") or "").strip()
        if not content:
            continue

        if role == "user":  # 销售员发言
            round_number += 1
            sales_topics = set(detect_topics(content))
            # 紧接着家长提问的第一句销售回复，只要不是在反问信息，就算答复
            answers_pending = awaiting_reply and not is_info_request(content)
            for topic, record in by_topic.items():
                if record["answered"]:
                    continue
                if topic in sales_topics or answers_pending:
                    record["answered"] = True
                    record["answer"] = _clip(content)
                    record["answer_round"] = round_number
            awaiting_reply = False
            continue

        if role not in ("ai", "assistant"):
            continue

        if not is_question(content):
            continue
        topics = detect_topics(content)
        if topics:
            awaiting_reply = True
        for topic in topics:
            record = by_topic.get(topic)
            if record is None:
                record = {
                    "topic": topic,
                    "label": TOPIC_LABELS.get(topic, topic),
                    "question": _clip(content, 60),
                    "asked_round": round_number,
                    "answered": False,
                    "answer": "",
                    "answer_round": 0,
                    "times_asked": 1,
                }
                by_topic[topic] = record
                asked.append(record)
            elif not record["answered"]:
                # 没得到答复前又问一次：累计次数，更新话术
                record["times_asked"] += 1
                record["question"] = _clip(content, 60)
            else:
                # 已经答复过又问一遍 —— 正是要治理的"重复提问"
                record["times_asked"] += 1
                record["repeat_after_answer"] = True
                record["last_repeat_round"] = round_number
            last_asked = record

    unanswered = [
        {"topic": record["topic"], "label": record["label"], "question": record["question"]}
        for record in asked
        if not record["answered"]
    ]
    return {
        "asked": asked,
        "unanswered": unanswered,
        "rounds": round_number,
        "last_asked": last_asked,
    }


def latest_answered_topic(ledger: dict[str, Any]) -> dict[str, Any] | None:
    """最近一次"刚问过且已被答复"的主题，用于本轮强提醒。"""
    answered = [record for record in ledger.get("asked", []) if record.get("answered")]
    if not answered:
        return None
    return max(answered, key=lambda record: record.get("answer_round", 0))


def render_ledger(
    ledger: dict[str, Any],
    *,
    customer_facts: dict[str, str] | None = None,
    max_answered: int = 6,
) -> str:
    """渲染成注入 system prompt 的中文片段；没有内容时返回空串。"""
    answered = [record for record in ledger.get("asked", []) if record.get("answered")]
    unanswered = ledger.get("unanswered", [])
    facts = {key: value for key, value in (customer_facts or {}).items() if value}

    if not answered and not unanswered and not facts:
        return ""

    lines: list[str] = ["\n【对话账本｜避免重复的关键】"]

    if answered:
        lines.append("以下话题你已经问过，销售也已经答复，**绝对不要再问一遍**：")
        for record in answered[-max_answered:]:
            lines.append(
                f"- {record['label']}（第{record['asked_round']}轮问）→ 销售答：{record['answer']}"
            )

    if unanswered:
        labels = "、".join(item["label"] for item in unanswered)
        lines.append(f"你问过但对方还没答复的：{labels}（可以继续追问，但换个说法）")

    if facts:
        fact_text = "；".join(f"{label}={value}" for label, value in facts.items())
        lines.append(f"你已经告诉过对方的信息：{fact_text}（不要重复介绍自己）")

    lines.append(
        "规则：已答复的话题别再问第二遍；确实想深入，就追问答复里没讲清楚的具体细节"
        "（例如对方已经说「周六上午有试听」，你可以问「周六上午几点、多长」），"
        "而不是把原问题重问一次。"
        "如果所有疑问都清楚了，就顺着对方的话往下聊，或者直接表态（报名/再考虑/不需要）。"
    )
    return "\n".join(lines)


def render_turn_reminder(ledger: dict[str, Any]) -> str:
    """本轮强提醒：优先针对"刚问过且已经被答复"的话题。"""
    last = ledger.get("last_asked")
    if isinstance(last, dict) and last.get("answered"):
        if last.get("repeat_after_answer"):
            return (
                f"\n【本轮特别提醒｜你刚才又重复问了】「{last['label']}」这个问题你在第"
                f"{last['asked_round']}轮就问过，销售当时已经答复：{last['answer']}。"
                "**这一轮绝对不能再问同一个问题**：要么追问那个答复里没讲清楚的具体细节"
                "（时间、时长、人数、费用构成），要么推进到下一个话题，或者直接表态。"
            )
        return (
            f"\n【本轮特别提醒】你上一轮刚问过「{last['label']}」，销售已经答复"
            f"（{last['answer']}）。这一轮绝不要再问同一个问题；"
            "要么就他的答复追问细节，要么推进到下一个话题。"
        )

    # 家长还有没被答复的疑问时，不需要防重复提醒
    if isinstance(last, dict) and not last.get("answered"):
        return ""

    record = latest_answered_topic(ledger)
    if not record:
        return ""
    return (
        f"\n【本轮特别提醒】你已经问过「{record['label']}」，销售已经答复"
        f"（{record['answer']}）。不要再问同一个问题；"
        "要么就他的答复追问细节，要么推进到下一个话题。"
    )


def is_repeat_question(candidate: str, ledger: dict[str, Any]) -> bool:
    """判断候选回复是否在重复已答复过的问题（用于日志与回归测试）。"""
    normalized = _normalize(candidate)
    if not normalized or not is_question(candidate):
        return False
    topics = set(detect_topics(candidate))
    if not topics:
        return False
    answered = {
        record["topic"]
        for record in ledger.get("asked", [])
        if record.get("answered")
    }
    return bool(topics & answered)


def facts_from_deal_state(state: dict[str, Any] | None) -> dict[str, str]:
    """把对练推进模型收集到的槽位转成"家长已自述"的事实。"""
    if not state:
        return {}
    from app.services.conversation.deal_templates import get_template

    slots = state.get("slots") or {}
    labels = {slot["key"]: slot["label"] for slot in get_template(state.get("template_id"))["slots"]}
    facts: dict[str, str] = {}
    for key, entry in slots.items():
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        if isinstance(value, str) and value.strip():
            facts[labels.get(key, key)] = value.strip()[:40]
    return facts
