"""教培行业对练信息模型：按学段细分的必问槽位（slot）模板。

设计原则
--------
1. 槽位是唯一事实源，覆盖率与缺口都由 schema 计算，不依赖 LLM 记忆。
2. 模板按学段细分（小学 / 初中 / 高中），换行业只需新增一份模板。
3. 每个槽位带 ``ask`` 追问话术与 ``hint`` 抽取提示，前端可直接展示。

契约
----
``level``: ``required`` 计入覆盖率分母，``recommended`` 只提示不计分。
``stage``: 该槽位通常在哪个阶段收集，用于缺口排序。
"""

from __future__ import annotations

from typing import Any, TypedDict

REQUIRED = "required"
RECOMMENDED = "recommended"

# 对话阶段（顺序即推进方向）
STAGE_ORDER = ["opening", "discovery", "diagnosis", "solution", "objection", "closing"]

STAGE_LABELS = {
    "opening": "开场建联",
    "discovery": "需求探询",
    "diagnosis": "现状诊断",
    "solution": "课程方案",
    "objection": "异议处理",
    "closing": "成交收尾",
}


class SlotDef(TypedDict, total=False):
    key: str
    label: str
    level: str
    stage: str
    ask: str
    hint: str


def _slot(key: str, label: str, level: str, stage: str, ask: str, hint: str = "") -> SlotDef:
    return {
        "key": key,
        "label": label,
        "level": level,
        "stage": stage,
        "ask": ask,
        "hint": hint or label,
    }


# ---------------------------------------------------------------------------
# 通用槽位（所有学段都问）
# ---------------------------------------------------------------------------

COMMON_SLOTS: list[SlotDef] = [
    _slot("parent_role", "家长身份", RECOMMENDED, "opening",
          "您是孩子妈妈吧？平时主要是您管学习吗？", "爸爸/妈妈/祖辈/其他监护人"),
    _slot("student_grade", "孩子年级", REQUIRED, "discovery",
          "孩子现在初几了？", "年级或年级段，如 小学三年级 / 初二 / 高二"),
    _slot("student_school", "就读学校", REQUIRED, "discovery",
          "孩子在哪个学校？公办还是民办的？", "学校名称，以及公办/民办"),
    _slot("weak_subjects", "薄弱科目", REQUIRED, "discovery",
          "目前哪几科最吃力？", "学科名称，多个用顿号分隔"),
    _slot("target_subject", "想补的科目", REQUIRED, "discovery",
          "这学期主要想补哪科？", "家长明确说要补的科目"),
    _slot("current_score", "当前成绩", REQUIRED, "diagnosis",
          "这次月考大概多少分？班里排多少名？", "具体分数或排名，保留原始数字"),
    _slot("pain_point", "家长最头痛的点", REQUIRED, "diagnosis",
          "最让您着急的是哪一点？", "家长原话中的核心焦虑"),
    _slot("target_goal", "目标分数或学校", REQUIRED, "diagnosis",
          "您希望期末提到多少分？还是冲某个高中？", "分数目标、名次目标或目标学校"),
    _slot("existing_tutoring", "是否已在别处补", REQUIRED, "discovery",
          "现在有在外面补课吗？", "机构名、科目，或明确说没有"),
    _slot("decision_maker", "谁拍板", REQUIRED, "solution",
          "这个事是您定还是需要和孩子爸爸商量？", "谁做最终决定"),
    _slot("budget_range", "预算区间", REQUIRED, "solution",
          "您这边一学期大概考虑多少预算？", "金额区间，保留原始数字"),
    _slot("preferred_format", "班型偏好", REQUIRED, "solution",
          "您倾向一对一还是小班？", "一对一 / 小班 / 大班"),
    _slot("schedule", "可上课时间", REQUIRED, "solution",
          "周末有空还是平日晚上？", "可上课的具体时段"),
    _slot("trial_intent", "试听意向", REQUIRED, "closing",
          "要不要先安排一节试听？", "愿意 / 不愿意 / 待定"),
    _slot("school_type", "公办民办", RECOMMENDED, "discovery",
          "学校是公办还是民办的？", "公办/民办/国际学校"),
    _slot("score_trend", "成绩趋势", RECOMMENDED, "diagnosis",
          "跟上次比是进步了还是退了？", "上升/下降/波动"),
    _slot("learning_habit", "学习习惯", RECOMMENDED, "diagnosis",
          "平时作业是他自己安排还是要盯着？", "自驱/需督促/拖延"),
    _slot("campus_pref", "校区偏好", RECOMMENDED, "solution",
          "哪个校区离您近？", "校区名或区域"),
    _slot("teacher_pref", "师资要求", RECOMMENDED, "solution",
          "对老师有什么要求？在职老师还是机构老师？", "师资类型偏好"),
]


# ---------------------------------------------------------------------------
# 学段特化槽位
# ---------------------------------------------------------------------------

PRIMARY_SLOTS: list[SlotDef] = [
    _slot("homework_supervision", "作业监督情况", REQUIRED, "diagnosis",
          "平时作业是谁在盯？", "家长盯/老人带/自己写"),
    _slot("interest_direction", "兴趣方向", RECOMMENDED, "discovery",
          "孩子平时对什么比较有兴趣？", "兴趣特长方向"),
    _slot("habit_goal", "习惯培养目标", RECOMMENDED, "diagnosis",
          "您更想先解决习惯还是先提分？", "习惯优先/提分优先"),
]

JUNIOR_SLOTS: list[SlotDef] = [
    _slot("class_rank", "班级或年级排名", REQUIRED, "diagnosis",
          "孩子在班里大概排多少名？", "排名数字，保留原始表述"),
    _slot("zhongkao_target", "中考目标校", RECOMMENDED, "diagnosis",
          "中考有没有目标学校？", "目标高中名称或层次"),
    _slot("subject_balance", "偏科情况", RECOMMENDED, "diagnosis",
          "是有一科拖后腿，还是几科都差不多？", "单科短板/整体均衡"),
]

SENIOR_SLOTS: list[SlotDef] = [
    _slot("subject_combination", "选科组合", REQUIRED, "discovery",
          "孩子选的是哪三科？", "物化生/史政地等组合"),
    _slot("gaokao_target", "高考目标校", RECOMMENDED, "diagnosis",
          "高考有目标学校或目标分数吗？", "目标院校或分数段"),
    _slot("time_pressure", "时间紧迫度", RECOMMENDED, "diagnosis",
          "离高考还有多久？现在最急的是哪科？", "年级与紧迫程度"),
]


TEMPLATES: dict[str, dict[str, Any]] = {
    "k12_primary": {
        "id": "k12_primary",
        "name": "K12 · 小学",
        "slots": COMMON_SLOTS + PRIMARY_SLOTS,
    },
    "k12_junior": {
        "id": "k12_junior",
        "name": "K12 · 初中",
        "slots": COMMON_SLOTS + JUNIOR_SLOTS,
    },
    "k12_senior": {
        "id": "k12_senior",
        "name": "K12 · 高中",
        "slots": COMMON_SLOTS + SENIOR_SLOTS,
    },
}

DEFAULT_TEMPLATE_ID = "k12_junior"


# ---------------------------------------------------------------------------
# 模板解析
# ---------------------------------------------------------------------------

_GRADE_HINTS = (
    ("k12_primary", ("小学", "一年级", "二年级", "三年级", "四年级", "五年级", "六年级", "幼小", "小升初")),
    ("k12_senior", ("高中", "高一", "高二", "高三", "高考", "中考后")),
    ("k12_junior", ("初中", "初一", "初二", "初三", "中考", "七年级", "八年级", "九年级")),
)


def resolve_template_id(*hints: str | None) -> str:
    """从年级/背景文本推断学段模板；无法判断时用初中模板。"""
    corpus = " ".join(str(hint) for hint in hints if hint)
    if not corpus:
        return DEFAULT_TEMPLATE_ID
    # 高中优先判断，避免"中考后升高中"被初中规则抢先命中
    for template_id, words in (_GRADE_HINTS[1], _GRADE_HINTS[0], _GRADE_HINTS[2]):
        if any(word in corpus for word in words):
            return template_id
    return DEFAULT_TEMPLATE_ID


def get_template(template_id: str | None) -> dict[str, Any]:
    return TEMPLATES.get(template_id or "", TEMPLATES[DEFAULT_TEMPLATE_ID])


def template_slots(template_id: str | None) -> list[SlotDef]:
    return list(get_template(template_id)["slots"])
