"""Endpoints for preparing an editable customer follow-up draft."""
import json
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database import get_db
from app.models.customer_table import CustomerTable, CustomerTableRow
from app.models.user import User
from app.services.llm import get_minimax_service

router = APIRouter(prefix="/follow-ups", tags=["回访与跟进"])


class FollowUpProfile(BaseModel):
    customer_name: str = ""
    identity: str = ""
    product: str = ""
    history_summary: str = ""
    current_progress: str = ""
    expectation: str = ""


class OrganizeRequest(BaseModel):
    description: str = Field(default="", max_length=5000)
    table_id: Optional[str] = None
    row_id: Optional[str] = None


class OrganizeResponse(BaseModel):
    profile: FollowUpProfile
    scripts: list[str] = Field(default_factory=list)
    source_text: str = ""


def _cell(columns: list[dict], cells: dict, keywords: tuple[str, ...]) -> str:
    for column in columns:
        label = str(column.get("label") or column.get("source_header") or "")
        if any(keyword in label for keyword in keywords):
            value = str(cells.get(column.get("key"), "")).strip()
            if value:
                return value
    return ""


def _fallback(columns: list[dict], cells: dict, description: str) -> FollowUpProfile:
    name = _cell(columns, cells, ("客户姓名", "姓名", "联系人", "客户名"))
    identity = _cell(columns, cells, ("职务", "职位", "身份", "岗位"))
    product = _cell(columns, cells, ("产品", "方案", "服务", "项目", "套餐"))
    history = "；".join(value for value in (
        _cell(columns, cells, ("需求", "痛点", "备注", "到访备注")),
        _cell(columns, cells, ("到访日期", "联系日期", "跟进日期")),
        description.strip(),
    ) if value)
    progress = "；".join(value for value in (
        _cell(columns, cells, ("客户等级", "等级", "状态", "阶段")),
        _cell(columns, cells, ("下次跟进", "下一步")),
    ) if value)
    return FollowUpProfile(customer_name=name, identity=identity, product=product,
                           history_summary=history, current_progress=progress)


def _parse_profile(raw: str) -> Optional[FollowUpProfile]:
    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw).strip()
    match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw) or re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return None
    try:
        data = json.loads(match.group(1) if match.lastindex else match.group(0))
        return FollowUpProfile(**{field: str(data.get(field, "") or "").strip() for field in FollowUpProfile.model_fields})
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _scripts(profile: FollowUpProfile) -> list[str]:
    name = profile.customer_name or "您"
    product = profile.product or "之前沟通的方案"
    progress = profile.current_progress or "上次沟通后的最新情况"
    expectation = profile.expectation or "确认下一步安排"
    return [
        f"{name}，您好，想跟进一下您上次提到的 {product}，现在方便聊两分钟吗？",
        f"上次我们了解到 {progress}，这段时间情况有没有新的变化？",
        f"如果本次能先把 {expectation} 确认下来，您觉得下一步怎样安排最合适？",
    ]


@router.post("/organize", response_model=OrganizeResponse)
async def organize_follow_up(
    request: OrganizeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return an editable six-field draft from free text or an owned table row."""
    columns: list[dict] = []
    cells: dict = {}
    unconfirmed_keys: set[str] = set()
    if bool(request.table_id) != bool(request.row_id):
        raise HTTPException(status_code=422, detail="表格和客户记录必须同时提供")
    if request.table_id:
        table = db.query(CustomerTable).filter(
            CustomerTable.id == request.table_id, CustomerTable.user_id == current_user.id
        ).first()
        if table is None:
            raise HTTPException(status_code=404, detail="客户表格不存在")
        row = db.query(CustomerTableRow).filter(
            CustomerTableRow.id == request.row_id, CustomerTableRow.table_id == table.id
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="客户记录不存在")
        columns, cells = list(table.columns or []), dict(row.cells or {})
        unconfirmed_keys = {
            str(item.get("column_key")) for item in (row.uncertain or [])
            if not item.get("reviewed") and item.get("column_key")
        }
    if not request.description.strip() and not cells:
        raise HTTPException(status_code=422, detail="请描述客户情况，或从客户列表选择一位客户")

    source_lines = [f"{item.get('label') or item.get('key')}: {cells.get(item.get('key'), '')}" for item in columns if cells.get(item.get('key'))]
    if request.description.strip():
        source_lines.append(request.description.strip())
    source_text = "\n".join(source_lines)
    fallback = _fallback(columns, cells, request.description)
    profile = fallback
    try:
        service = get_minimax_service()
        if service.api_key:
            prompt = """将下列资料整理为回访档案。只输出 JSON；不得补造未提供的具体事实。字段必须为 customer_name、identity、product、history_summary、current_progress、expectation；未知字段留空。\n\n""" + source_text
            if unconfirmed_keys:
                unconfirmed_labels = [str(item.get("label") or item.get("key")) for item in columns if item.get("key") in unconfirmed_keys]
                prompt += "\n\n以下字段尚未人工确认：" + "、".join(unconfirmed_labels) + "。它们可作为暂定线索，但不要写成确定事实。"
            organized = _parse_profile(await service.chat([
                {"role": "system", "content": "你是严谨的销售回访助手，只根据输入资料归纳。"},
                {"role": "user", "content": prompt},
            ], model="MiniMax-M3", temperature=0.2, max_tokens=700))
            if organized:
                profile = FollowUpProfile(**{
                    field: getattr(organized, field) or getattr(fallback, field)
                    for field in FollowUpProfile.model_fields
                })
    except Exception:
        # A usable, editable draft is preferable to blocking the sales workflow.
        pass
    return OrganizeResponse(profile=profile, scripts=_scripts(profile), source_text=source_text)
