"""Customer management API with dynamic, per-upload table schemas."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import PureWindowsPath
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database import get_db
from app.models.customer_table import CustomerTable, CustomerTableRow
from app.models.user import User
from app.services.customer_tables import (
    ALLOWED_TYPES,
    MAX_UPLOAD_BYTES,
    CustomerTableError,
    analyze_table,
)

router = APIRouter(prefix="/customer-tables", tags=["客户管理"])


class CustomerColumnResponse(BaseModel):
    key: str
    label: str
    source_header: Optional[str] = None
    semantic_type: str = "text"
    confidence: float = 0.0


class UncertainItemResponse(BaseModel):
    column_key: str
    label: str
    value: str
    reason: str
    reviewed: bool = False


class CustomerRowResponse(BaseModel):
    id: str
    position: int
    cells: dict[str, str]
    original_cells: dict[str, str]
    uncertain: list[UncertainItemResponse]


class CustomerTableSummary(BaseModel):
    id: str
    name: str
    source_filename: Optional[str]
    source_sheet: Optional[str]
    header_row: Optional[int]
    columns: list[CustomerColumnResponse]
    row_count: int
    uncertain_count: int
    created_at: Any
    updated_at: Any


class CustomerTableDetail(CustomerTableSummary):
    rows: list[CustomerRowResponse]
    total: int
    page: int
    page_size: int


class RowUpdateRequest(BaseModel):
    cells: dict[str, str] = Field(default_factory=dict)
    confirm_keys: list[str] = Field(default_factory=list)
    confirm_all: bool = False


class AddColumnRequest(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    semantic_type: str = "text"
    initial_value: str = ""


class RenameColumnRequest(BaseModel):
    label: str = Field(min_length=1, max_length=80)


class AddRowRequest(BaseModel):
    cells: dict[str, str] = Field(default_factory=dict)


class BatchConfirmResponse(BaseModel):
    confirmed_count: int
    remaining_count: int


class BatchDeleteRequest(BaseModel):
    row_ids: list[str] = Field(min_length=1, max_length=200)


class BatchDeleteResponse(BaseModel):
    deleted_count: int
    remaining_rows: int



def _owned_table(db: Session, table_id: str, user_id: str) -> CustomerTable:
    table = db.query(CustomerTable).filter(
        CustomerTable.id == table_id,
        CustomerTable.user_id == user_id,
    ).first()
    if table is None:
        raise HTTPException(status_code=404, detail="客户表格不存在")
    return table


def _owned_row(db: Session, table_id: str, row_id: str, user_id: str) -> CustomerTableRow:
    _owned_table(db, table_id, user_id)
    row = db.query(CustomerTableRow).filter(
        CustomerTableRow.id == row_id,
        CustomerTableRow.table_id == table_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="客户记录不存在")
    return row


def _uncertain_count(table: CustomerTable) -> int:
    return sum(
        1
        for row in table.rows
        for item in (row.uncertain or [])
        if not item.get("reviewed", False)
    )


def _summary(table: CustomerTable) -> CustomerTableSummary:
    return CustomerTableSummary(
        id=table.id,
        name=table.name,
        source_filename=table.source_filename,
        source_sheet=table.source_sheet,
        header_row=table.header_row,
        columns=table.columns or [],
        row_count=table.row_count or 0,
        uncertain_count=_uncertain_count(table),
        created_at=table.created_at,
        updated_at=table.updated_at,
    )


def _row_response(row: CustomerTableRow) -> CustomerRowResponse:
    return CustomerRowResponse(
        id=row.id,
        position=row.position,
        cells=row.cells or {},
        original_cells=row.original_cells or {},
        uncertain=row.uncertain or [],
    )


def _detail(table: CustomerTable, page: int, page_size: int, search: str = "") -> CustomerTableDetail:
    rows = list(table.rows)
    needle = search.strip().casefold()
    if needle:
        rows = [row for row in rows if needle in json.dumps(row.cells or {}, ensure_ascii=False).casefold()]
    total = len(rows)
    start = (page - 1) * page_size
    selected = rows[start:start + page_size]
    return CustomerTableDetail(
        **_summary(table).model_dump(),
        rows=[_row_response(row) for row in selected],
        total=total,
        page=page,
        page_size=page_size,
    )


def _validate_cells(table: CustomerTable, cells: dict[str, str]) -> dict[str, str]:
    column_keys = {str(column.get("key")) for column in (table.columns or [])}
    unknown = set(cells) - column_keys
    if unknown:
        raise HTTPException(status_code=422, detail="包含不存在的列")
    return {str(key): str(value) for key, value in cells.items()}


def _confirm_all_uncertain(db: Session, table: CustomerTable) -> int:
    confirmed_count = 0
    for row in table.rows:
        updated_items = []
        for item in (row.uncertain or []):
            value = dict(item)
            if not value.get("reviewed", False):
                value["reviewed"] = True
                confirmed_count += 1
            updated_items.append(value)
        row.uncertain = updated_items
    table.updated_at = datetime.utcnow()
    db.commit()
    return confirmed_count


def _batch_delete_rows(db: Session, table: CustomerTable, row_ids: list[str]) -> BatchDeleteResponse:
    unique_ids = list(dict.fromkeys(row_ids))
    rows = db.query(CustomerTableRow).filter(
        CustomerTableRow.table_id == table.id,
        CustomerTableRow.id.in_(unique_ids),
    ).all()
    if len(rows) != len(unique_ids):
        raise HTTPException(status_code=404, detail="部分客户记录不存在或不属于当前表格")
    deleted_count = len(rows)
    for row in rows:
        db.delete(row)
    table.row_count = max(0, (table.row_count or deleted_count) - deleted_count)
    table.updated_at = datetime.utcnow()
    db.commit()
    return BatchDeleteResponse(deleted_count=deleted_count, remaining_rows=table.row_count)


@router.get("", response_model=list[CustomerTableSummary])
async def list_customer_tables(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tables = db.query(CustomerTable).filter(
        CustomerTable.user_id == current_user.id
    ).order_by(CustomerTable.updated_at.desc(), CustomerTable.created_at.desc()).all()
    return [_summary(table) for table in tables]


@router.post("/import", response_model=CustomerTableDetail, status_code=status.HTTP_201_CREATED)
async def import_customer_table(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filename = PureWindowsPath(file.filename or "").name
    if not filename:
        raise HTTPException(status_code=400, detail="请选择要上传的表格文件")
    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件不能超过 10 MB")

    latest = db.query(CustomerTable).filter(
        CustomerTable.user_id == current_user.id
    ).order_by(CustomerTable.updated_at.desc()).first()
    template_columns = latest.columns if latest else None
    try:
        analyzed = await analyze_table(filename, contents, template_columns=template_columns)
    except CustomerTableError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="表格分析失败，请稍后重试") from exc

    table = CustomerTable(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        name=analyzed["name"],
        source_filename=analyzed["source_filename"],
        source_sheet=analyzed["source_sheet"],
        header_row=analyzed["header_row"],
        columns=analyzed["columns"],
        row_count=len(analyzed["rows"]),
    )
    for item in analyzed["rows"]:
        table.rows.append(CustomerTableRow(
            id=str(uuid.uuid4()),
            position=item["position"],
            cells=item["cells"],
            original_cells=item["original_cells"],
            uncertain=item["uncertain"],
        ))
    db.add(table)
    db.commit()
    db.refresh(table)
    return _detail(table, page=1, page_size=50)


@router.get("/{table_id}", response_model=CustomerTableDetail)
async def get_customer_table(
    table_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str = Query("", max_length=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = _owned_table(db, table_id, current_user.id)
    return _detail(table, page=page, page_size=page_size, search=search)


@router.patch("/{table_id}/rows/{row_id}", response_model=CustomerRowResponse)
async def update_customer_row(
    table_id: str,
    row_id: str,
    payload: RowUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = _owned_table(db, table_id, current_user.id)
    row = _owned_row(db, table_id, row_id, current_user.id)
    cells = dict(row.cells or {})
    cells.update(_validate_cells(table, payload.cells))
    row.cells = cells

    reviewed_keys = set(payload.confirm_keys)
    uncertain = []
    for item in (row.uncertain or []):
        value = dict(item)
        if payload.confirm_all or value.get("column_key") in reviewed_keys:
            value["reviewed"] = True
        uncertain.append(value)
    row.uncertain = uncertain
    db.commit()
    db.refresh(row)
    return _row_response(row)


@router.delete("/{table_id}/rows/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer_row(
    table_id: str,
    row_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = _owned_table(db, table_id, current_user.id)
    row = _owned_row(db, table_id, row_id, current_user.id)
    db.delete(row)
    table.row_count = max(0, (table.row_count or 1) - 1)
    db.commit()
    return None


@router.post("/{table_id}/uncertain/confirm-all", response_model=BatchConfirmResponse)
async def confirm_all_uncertain_items(
    table_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = _owned_table(db, table_id, current_user.id)
    confirmed_count = _confirm_all_uncertain(db, table)
    db.refresh(table)
    return BatchConfirmResponse(
        confirmed_count=confirmed_count,
        remaining_count=_uncertain_count(table),
    )


@router.post("/{table_id}/rows/batch-delete", response_model=BatchDeleteResponse)
async def delete_customer_rows_batch(
    table_id: str,
    payload: BatchDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = _owned_table(db, table_id, current_user.id)
    return _batch_delete_rows(db, table, payload.row_ids)


@router.post("/{table_id}/rows", response_model=CustomerRowResponse, status_code=status.HTTP_201_CREATED)
async def add_customer_row(
    table_id: str,
    payload: AddRowRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = _owned_table(db, table_id, current_user.id)
    cells = {str(column.get("key")): "" for column in (table.columns or [])}
    cells.update(_validate_cells(table, payload.cells))
    next_position = max((row.position for row in table.rows), default=0) + 1
    row = CustomerTableRow(
        id=str(uuid.uuid4()),
        table_id=table.id,
        position=next_position,
        cells=cells,
        original_cells={},
        uncertain=[],
    )
    db.add(row)
    table.row_count = (table.row_count or 0) + 1
    db.commit()
    db.refresh(row)
    return _row_response(row)


@router.post("/{table_id}/columns", response_model=CustomerTableDetail, status_code=status.HTTP_201_CREATED)
async def add_customer_column(
    table_id: str,
    payload: AddColumnRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = _owned_table(db, table_id, current_user.id)
    if len(table.columns or []) >= 80:
        raise HTTPException(status_code=422, detail="单张表最多支持 80 列")
    semantic_type = payload.semantic_type if payload.semantic_type in ALLOWED_TYPES else "text"
    key = f"col_{uuid.uuid4().hex[:12]}"
    columns = list(table.columns or [])
    columns.append({
        "key": key,
        "label": payload.label.strip(),
        "source_header": None,
        "semantic_type": semantic_type,
        "confidence": 1.0,
        "is_extra": True,
    })
    table.columns = columns
    for row in table.rows:
        cells = dict(row.cells or {})
        cells[key] = payload.initial_value
        row.cells = cells
    db.commit()
    db.refresh(table)
    return _detail(table, page=1, page_size=200)


@router.patch("/{table_id}/columns/{column_key}", response_model=CustomerTableSummary)
async def rename_customer_column(
    table_id: str,
    column_key: str,
    payload: RenameColumnRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = _owned_table(db, table_id, current_user.id)
    columns = list(table.columns or [])
    for column in columns:
        if column.get("key") == column_key:
            column["label"] = payload.label.strip()
            table.columns = columns
            db.commit()
            db.refresh(table)
            return _summary(table)
    raise HTTPException(status_code=404, detail="列不存在")


@router.delete("/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer_table(
    table_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = _owned_table(db, table_id, current_user.id)
    db.delete(table)
    db.commit()
    return None