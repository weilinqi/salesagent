"""Excel/CSV analysis for dynamic customer tables.

The model is deliberately not fixed. Each upload produces its own columns and
cell values. LLM reasoning is bounded and only decides column labels/types;
the bulk normalization is deterministic.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_DATA_ROWS = 5000
MAX_COLUMNS = 80
MAX_SAMPLE_ROWS = 8
ALLOWED_TYPES = {
    "text", "phone", "email", "date", "datetime", "amount", "number",
    "percentage", "identifier", "url", "status", "person", "company",
    "address", "note",
}
TYPE_LABELS = {
    "phone": "电话", "email": "邮箱", "date": "日期", "datetime": "时间",
    "amount": "金额", "number": "数值", "percentage": "百分比",
    "identifier": "编号", "url": "网址", "status": "状态", "person": "联系人",
    "company": "公司", "address": "地址", "note": "备注", "text": "文本",
}
HEADER_KEYWORDS = (
    "日期", "时间", "姓名", "客户", "联系人", "电话", "手机", "邮箱", "公司",
    "单位", "地址", "行业", "备注", "状态", "负责人", "金额", "单价", "价格",
    "数量", "销量", "编号", "订单", "书店", "图书", "账期", "含税", "未税",
)
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?86[\s-]?)?(?:1[3-9]\d{9}|0\d{2,3}[\s-]?\d{7,8})(?!\d)"
)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
URL_RE = re.compile(r"^https?://", re.I)
DATE_PATTERNS = (
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日",
    "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
)
EMBEDDED_FIELD_PATTERNS = {
    "客户姓名": re.compile(r"(?:客户姓名|姓名)\s*[:：]\s*"),
    "客户电话": re.compile(r"(?:客户电话|联系电话|联系方式|手机号码|手机号|手机|电话)\s*[:：]\s*"),
    "客户身份/职业": re.compile(r"(?:客户身份|身份|职业|职位)\s*[:：]\s*"),
}


class CustomerTableError(ValueError):
    """A user-facing parse or normalization error."""


@dataclass
class ParsedTable:
    title: str
    sheet_name: str
    header_row: Optional[int]
    headers: list[str]
    data_rows: list[list[str]]
    original_rows: list[list[str]]


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.time() == datetime.min.time():
            return value.date().isoformat()
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return text


def _strip_accents(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", value) if not unicodedata.combining(ch))


def _clean_header(value: str, fallback: str) -> str:
    text = re.sub(r"\s+", " ", normalize_text(value)).strip(" :：_-\n\t")
    return text[:80] or fallback


def _dedupe_headers(headers: Iterable[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for index, header in enumerate(headers, start=1):
        base = _clean_header(header, f"未命名列 {index}")
        count = seen.get(base, 0) + 1
        seen[base] = count
        result.append(base if count == 1 else f"{base}（{count}）")
    return result


def _nearest_title(rows: list[list[str]], header_row: Optional[int], filename: str) -> str:
    if header_row is not None:
        candidates = [[value for value in row if value] for row in rows[:header_row]]
        candidates = [values for values in candidates if values]
        if candidates:
            single_cell_rows = [values for values in candidates if len(values) == 1]
            if single_cell_rows:
                return max(single_cell_rows, key=lambda values: len(values[0]))[0][:120]
            return max(candidates, key=lambda values: max(len(value) for value in values))[0][:120]
    return Path(filename).stem[:120] or "客户表格"

def _row_nonempty(row: list[str]) -> int:
    return sum(bool(value.strip()) for value in row)


def _looks_like_strong_value(value: str) -> bool:
    return bool(PHONE_RE.search(value) or EMAIL_RE.match(value) or URL_RE.match(value)) or _parse_date(value) is not None


def _header_score(rows: list[list[str]], index: int) -> float:
    row = rows[index]
    values = [value.strip() for value in row if value.strip()]
    if len(values) < 2:
        return -100.0
    if any(_looks_like_strong_value(value) for value in values):
        return -50.0
    unique_ratio = len(set(values)) / len(values)
    short_text = sum(len(value) <= 30 for value in values) / len(values)
    keyword_hits = sum(any(keyword in value for keyword in HEADER_KEYWORDS) for value in values)
    nonempty_ratio = len(values) / max(1, len(row))
    following = rows[index + 1:index + 4]
    following_nonempty = sum(_row_nonempty(item) for item in following) / max(1, len(following))
    score = keyword_hits * 4 + unique_ratio * 2 + short_text * 2 + nonempty_ratio
    score += min(3.0, following_nonempty / max(1, len(values)))
    if keyword_hits == 0:
        score -= 1.5
    return score


def _detect_header(rows: list[list[str]]) -> Optional[int]:
    candidates = range(min(15, len(rows)))
    scored = [(_header_score(rows, index), index) for index in candidates]
    scored.sort(reverse=True)
    if not scored:
        return None
    score, index = scored[0]
    if score < 2.6:
        return None
    return index


def _parse_date(value: str) -> Optional[date]:
    text = value.strip()
    if not text:
        return None
    for pattern in DATE_PATTERNS:
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed.date()
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.date()
    except ValueError:
        return None


def _numeric_value(value: str) -> Optional[float]:
    text = value.strip().replace(",", "").replace("，", "")
    text = re.sub(r"^(?:CNY|RMB|¥|￥)\s*", "", text, flags=re.I)
    text = re.sub(r"\s*(?:元|万元)$", "", text)
    try:
        return float(text)
    except ValueError:
        return None


def _header_type(header: str) -> Optional[str]:
    text = header.lower()
    if any(word in text for word in ("电话", "手机", "联系方式")):
        return "phone"
    if "邮箱" in text or "email" in text or "e-mail" in text:
        return "email"
    if any(word in text for word in ("日期", "月份")) or "date" in text:
        return "date"
    if any(word in text for word in ("金额", "单价", "价格", "小计", "合计", "收入", "费用")):
        return "amount"
    if any(word in text for word in ("百分比", "比例", "率")):
        return "percentage"
    if any(word in text for word in ("编号", "订单号", "序号")):
        return "identifier"
    if any(word in text for word in ("数量", "销量", "库存")):
        return "number"
    if any(word in text for word in ("网址", "链接", "url")):
        return "url"
    if any(word in text for word in ("状态", "阶段")):
        return "status"
    if any(word in text for word in ("姓名", "联系人")):
        return "person"
    if any(word in text for word in ("公司", "单位")):
        return "company"
    if any(word in text for word in ("地址", "地区", "区域")):
        return "address"
    if any(word in text for word in ("备注", "说明", "需求")):
        return "note"
    return None


def infer_column_type(header: str, values: list[str]) -> tuple[str, float]:
    nonempty = [value for value in values if value.strip()]
    if not nonempty:
        return "text", 0.2
    header_type = _header_type(header)
    sample = nonempty[:50]
    checks = {
        "phone": sum(bool(PHONE_RE.search(value)) for value in sample) / len(sample),
        "email": sum(bool(EMAIL_RE.match(value.strip())) for value in sample) / len(sample),
        "date": sum(_parse_date(value) is not None for value in sample) / len(sample),
        "url": sum(bool(URL_RE.match(value.strip())) for value in sample) / len(sample),
    }
    for kind, ratio in checks.items():
        if ratio >= 0.8:
            return kind, min(0.99, 0.82 + ratio * 0.15)
    numeric = [_numeric_value(value) for value in sample]
    numeric_ratio = sum(value is not None for value in numeric) / len(sample)
    if numeric_ratio >= 0.8:
        if all("%" in value for value in sample):
            return "percentage", 0.9
        if header_type == "identifier":
            return "identifier", 0.85
        if header_type == "amount":
            return "amount", 0.9
        if header_type == "number":
            return "number", 0.9
        if header_type:
            return header_type, 0.75
        return "number", 0.72
    if header_type:
        return header_type, 0.8
    if sample and all(len(value) <= 12 and not re.search(r"\d", value) for value in sample[:10]):
        return "text", 0.52
    return "text", 0.42


def _build_columns(headers: list[str], data_rows: list[list[str]]) -> list[dict[str, Any]]:
    width = max([len(headers)] + [len(row) for row in data_rows] + [0])
    headers = _dedupe_headers(headers + [""] * (width - len(headers)))
    columns: list[dict[str, Any]] = []
    for index, header in enumerate(headers):
        values = [row[index] if index < len(row) else "" for row in data_rows]
        semantic_type, confidence = infer_column_type(header, values)
        source_header = header if header and not header.startswith("未命名列") else None
        label = header
        if not source_header:
            base = TYPE_LABELS.get(semantic_type, f"未命名列 {index + 1}")
            label = base
        columns.append({
            "key": f"col_{index + 1}",
            "label": label,
            "source_header": source_header,
            "semantic_type": semantic_type,
            "confidence": round(confidence, 3),
        })
    return _dedupe_column_labels(columns)


def _dedupe_column_labels(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, int] = {}
    for column in columns:
        base = _clean_header(str(column.get("label", "")), "未命名列")
        count = seen.get(base, 0) + 1
        seen[base] = count
        column["label"] = base if count == 1 else f"{base}（{count}）"
    return columns


def _parse_embedded_value(value: str, field_names: list[str]) -> dict[str, str]:
    matches: list[tuple[int, int, str]] = []
    for field_name in field_names:
        pattern = EMBEDDED_FIELD_PATTERNS[field_name]
        for match in pattern.finditer(value):
            matches.append((match.start(), match.end(), field_name))
    if not matches:
        return {}
    matches.sort(key=lambda item: item[0])
    result: dict[str, str] = {}
    prefix = value[:matches[0][0]].strip(" \n\t:：")
    for index, (_, content_start, field_name) in enumerate(matches):
        content_end = matches[index + 1][0] if index + 1 < len(matches) else len(value)
        segment = value[content_start:content_end].strip(" \n\t|,，;；")
        if field_name == "客户电话":
            phones = PHONE_RE.findall(segment)
            if phones:
                result[field_name] = phones[0]
                remainder = PHONE_RE.sub("", segment).strip(" \n\t|,，;；")
                if remainder and "客户身份/职业" not in result:
                    result["客户身份/职业"] = remainder
            else:
                result[field_name] = segment
        else:
            result[field_name] = segment
    if prefix and "客户姓名" not in result and "客户身份/职业" not in result:
        result["客户身份/职业"] = prefix
    return result


def _expand_embedded_columns(
    columns: list[dict[str, Any]], data_rows: list[list[str]], original_rows: list[list[str]]
) -> tuple[list[dict[str, Any]], list[list[str]], list[list[str]]]:
    """Split a column such as '客户姓名：... 客户电话：...' when labels repeat."""
    if not columns:
        return columns, data_rows, original_rows
    for column_index, column in enumerate(columns):
        values = [row[column_index] if column_index < len(row) else "" for row in data_rows]
        nonempty = [value for value in values if value.strip()]
        if len(nonempty) < 2:
            continue
        detected: set[str] = set()
        covered = 0
        for value in nonempty:
            matched = {name for name, pattern in EMBEDDED_FIELD_PATTERNS.items() if pattern.search(value)}
            if matched:
                covered += 1
                detected.update(matched)
        if len(detected) < 2 or covered / len(nonempty) < 0.5:
            continue
        ordered_fields = [name for name in EMBEDDED_FIELD_PATTERNS if name in detected]
        new_columns = []
        for field_name in ordered_fields:
            semantic = "phone" if field_name == "客户电话" else ("person" if field_name == "客户姓名" else "text")
            new_columns.append({
                "key": "",
                "label": field_name,
                "source_header": column.get("source_header"),
                "semantic_type": semantic,
                "confidence": 0.9 if semantic == "phone" else 0.72,
            })
        expanded_data_rows: list[list[str]] = []
        expanded_original_rows: list[list[str]] = []
        for row_index in range(len(data_rows)):
            data_row = list(data_rows[row_index])
            original_row = list(original_rows[row_index]) if row_index < len(original_rows) else list(data_row)
            raw = data_row[column_index] if column_index < len(data_row) else ""
            parsed = _parse_embedded_value(raw, ordered_fields)
            replacement = [parsed.get(field, "") for field in ordered_fields]
            expanded_data_rows.append(data_row[:column_index] + replacement + data_row[column_index + 1:])
            expanded_original_rows.append(original_row[:column_index] + replacement + original_row[column_index + 1:])
        columns = columns[:column_index] + new_columns + columns[column_index + 1:]
        data_rows = expanded_data_rows
        original_rows = expanded_original_rows
        break
    return columns, data_rows, original_rows


def _assign_column_keys(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, column in enumerate(columns, start=1):
        column["key"] = f"col_{index}"
    return _dedupe_column_labels(columns)


def _mask_sample(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    phone = PHONE_RE.search(text)
    if phone:
        raw = phone.group(0)
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 7:
            return f"{digits[:3]}****{digits[-2:]}"
    if EMAIL_RE.match(text):
        local, domain = text.split("@", 1)
        return f"{local[:1]}***@{domain}"
    if len(text) > 32:
        return text[:14] + "..." + text[-6:]
    return text
def _template_map(template_columns: Optional[list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    if not template_columns:
        return {}
    result = {}
    for column in template_columns:
        source = _strip_accents(str(column.get("source_header") or column.get("label") or "")).lower().strip()
        if source:
            result[source] = column
    return result


def _apply_template(columns: list[dict[str, Any]], template_columns: Optional[list[dict[str, Any]]]) -> int:
    templates = _template_map(template_columns)
    matches = 0
    for column in columns:
        source = _strip_accents(str(column.get("source_header") or column.get("label") or "")).lower().strip()
        template = templates.get(source)
        if not template:
            continue
        column["label"] = template.get("label") or column["label"]
        if template.get("semantic_type") in ALLOWED_TYPES:
            column["semantic_type"] = template["semantic_type"]
        column["confidence"] = max(float(column.get("confidence") or 0), 0.9)
        matches += 1
    return matches


def _extract_json_object(text: str) -> Optional[dict[str, Any]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(cleaned[start:end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _apply_llm_plan(columns: list[dict[str, Any]], plan: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    planned = plan.get("columns")
    if not isinstance(planned, list):
        return columns, ["columns 必须是数组"]
    by_key = {str(item.get("key")): item for item in planned if isinstance(item, dict)}
    for column in columns:
        item = by_key.get(column["key"])
        if not item:
            continue
        label = _clean_header(str(item.get("label") or ""), column["label"])
        semantic_type = str(item.get("semantic_type") or column["semantic_type"])
        if semantic_type not in ALLOWED_TYPES:
            errors.append(f"{column['key']} 的类型不合法")
            semantic_type = column["semantic_type"]
        try:
            confidence = float(item.get("confidence", column["confidence"]))
        except (TypeError, ValueError):
            confidence = column["confidence"]
        column["label"] = label[:80]
        column["semantic_type"] = semantic_type
        column["confidence"] = round(max(0.0, min(1.0, confidence)), 3)
    if not by_key:
        errors.append("未返回任何列识别结果")
    return _dedupe_column_labels(columns), errors


async def _refine_with_llm(
    columns: list[dict[str, Any]], rows: list[list[str]], table_name: str, sheet_name: str
) -> list[dict[str, Any]]:
    """Run a bounded plan -> validate -> repair loop using the configured LLM."""
    try:
        from app.services.llm import get_minimax_service
        service = get_minimax_service()
    except Exception:
        return columns

    payload = {
        "table_name": table_name,
        "sheet_name": sheet_name,
        "columns": [
            {
                "key": column["key"],
                "header": column.get("source_header") or "",
                "suggested_label": column.get("label", ""),
                "suggested_type": column.get("semantic_type", "text"),
                "confidence": column.get("confidence", 0),
                "samples": [
                    _mask_sample(row[index] if index < len(row) else "")
                    for row in rows[:MAX_SAMPLE_ROWS]
                ],
            }
            for index, column in enumerate(columns)
        ],
    }
    messages = [
        {"role": "system", "content": "你是销售客户表格结构识别器。只输出严格 JSON，不要输出解释或 Markdown。"},
        {"role": "user", "content": json.dumps({
            "task": "根据列名和脱敏样值，为每列给出更准确的网页列名和数据类型。保留原列数量，不增删列。",
            "allowed_types": sorted(ALLOWED_TYPES),
            "output_schema": {"columns": [{"key": "col_1", "label": "列名", "semantic_type": "phone", "confidence": 0.95}]},
            "data": payload,
        }, ensure_ascii=False)},
    ]
    last_errors: list[str] = []
    for _attempt in range(2):
        try:
            response = await asyncio.wait_for(
                service.chat(messages, temperature=0.0, max_tokens=1800), timeout=45
            )
            plan = _extract_json_object(response)
            if not plan:
                last_errors = ["模型没有返回有效 JSON"]
            else:
                refined, errors = _apply_llm_plan(columns, plan)
                columns = refined
                if not errors:
                    return columns
                last_errors = errors
        except Exception:
            return columns
        if last_errors:
            messages.append({"role": "user", "content": json.dumps({
                "repair": "上一次结果存在问题，请修正后重新输出完整 JSON。",
                "errors": last_errors,
            }, ensure_ascii=False)})
    return columns


def _read_csv(contents: bytes, filename: str) -> ParsedTable:
    decoded = None
    for encoding in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            decoded = contents.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise CustomerTableError("CSV 编码无法识别，请另存为 UTF-8 后重试")
    rows = [[normalize_text(cell) for cell in row] for row in csv.reader(io.StringIO(decoded))]
    header_row = _detect_header(rows)
    title = _nearest_title(rows, header_row, filename)
    return _build_parsed_table(rows, filename, title, header_row, "")


def _read_xlsx(contents: bytes, filename: str) -> ParsedTable:
    try:
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(contents), data_only=True)
    except Exception as exc:
        raise CustomerTableError("Excel 文件无法读取，请确认文件未损坏") from exc
    best: Optional[ParsedTable] = None
    best_score = -1.0
    try:
        for sheet in workbook.worksheets:
            rows: list[list[str]] = []
            for row in sheet.iter_rows(values_only=True):
                rows.append([normalize_text(cell) for cell in row])
                if len(rows) > MAX_DATA_ROWS + 30:
                    break
            if not rows:
                continue
            header_row = _detect_header(rows)
            score = _header_score(rows, header_row) if header_row is not None else max(_row_nonempty(row) for row in rows[:3]) / 2
            if score > best_score:
                best_score = score
                title = _nearest_title(rows, header_row, filename)
                best = _build_parsed_table(rows, filename, title, header_row, sheet.title)
        if best is None:
            raise CustomerTableError("文件中没有可读取的数据表")
        return best
    finally:
        workbook.close()


def _build_parsed_table(
    rows: list[list[str]], filename: str, title: str, header_row: Optional[int], sheet_name: Optional[str] = None
) -> ParsedTable:
    if not rows:
        raise CustomerTableError("表格为空")
    if header_row is not None:
        headers = rows[header_row]
        data_rows = rows[header_row + 1:]
        original_rows = data_rows
    else:
        width = max((len(row) for row in rows[:3]), default=0)
        headers = [""] * width
        data_rows = rows
        original_rows = rows
    cleaned_rows: list[list[str]] = []
    for row in data_rows:
        if not any(value.strip() for value in row):
            continue
        cleaned_rows.append([normalize_text(value) for value in row][:MAX_COLUMNS])
        if len(cleaned_rows) >= MAX_DATA_ROWS:
            break
    if not cleaned_rows:
        raise CustomerTableError("表格里没有数据行")
    max_width = max(len(row) for row in cleaned_rows)
    truncated_headers = list(headers[:MAX_COLUMNS])
    if len(truncated_headers) < max_width:
        truncated_headers.extend([""] * (max_width - len(truncated_headers)))
    return ParsedTable(
        title=title or Path(filename).stem,
        sheet_name=sheet_name or "",
        header_row=header_row + 1 if header_row is not None else None,
        headers=truncated_headers,
        data_rows=cleaned_rows,
        original_rows=[list(row) for row in cleaned_rows],
    )


def parse_uploaded_table(filename: str, contents: bytes) -> ParsedTable:
    if len(contents) > MAX_UPLOAD_BYTES:
        raise CustomerTableError("文件不能超过 10 MB")
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return _read_csv(contents, filename)
    if suffix in (".xlsx", ".xlsm"):
        return _read_xlsx(contents, filename)
    if suffix == ".xls":
        raise CustomerTableError("暂不支持旧版 .xls，请另存为 .xlsx 后上传")
    raise CustomerTableError("只支持 .xlsx、.xlsm 和 .csv 文件")


def _cell_issue(column: dict[str, Any], value: str) -> Optional[str]:
    semantic_type = column.get("semantic_type", "text")
    if semantic_type == "phone" and not PHONE_RE.search(value):
        return "该值不符合已识别列的电话格式"
    if semantic_type == "email" and not EMAIL_RE.match(value.strip()):
        return "该值不符合已识别列的邮箱格式"
    if semantic_type in ("date", "datetime") and _parse_date(value) is None:
        return "该值无法按已识别列的日期格式解析"
    if semantic_type in ("amount", "number", "percentage") and _numeric_value(value.replace("%", "")) is None:
        return "该值无法按已识别列的数值格式解析"
    return None


def _build_row_records(
    columns: list[dict[str, Any]], data_rows: list[list[str]], original_rows: list[list[str]]
) -> list[dict[str, Any]]:
    records = []
    for row_index, row in enumerate(data_rows):
        cells = {}
        original_cells = {}
        uncertain = []
        for column_index, column in enumerate(columns):
            key = column["key"]
            value = row[column_index] if column_index < len(row) else ""
            original = (
                original_rows[row_index][column_index]
                if row_index < len(original_rows) and column_index < len(original_rows[row_index])
                else value
            )
            cells[key] = value
            original_cells[key] = original
            confidence = float(column.get("confidence") or 0)
            issue = _cell_issue(column, value) if value.strip() else None
            if value.strip() and (confidence < 0.65 or issue):
                uncertain.append({
                    "column_key": key,
                    "label": column.get("label") or column.get("source_header") or "未确认内容",
                    "value": value,
                    "reason": issue or "AI 对该列含义的置信度较低，需要人工确认",
                    "reviewed": False,
                })
        records.append({
            "position": row_index + 1,
            "cells": cells,
            "original_cells": original_cells,
            "uncertain": uncertain,
        })
    return records

async def analyze_table(
    filename: str,
    contents: bytes,
    template_columns: Optional[list[dict[str, Any]]] = None,
    use_ai: bool = True,
) -> dict[str, Any]:
    parsed = parse_uploaded_table(filename, contents)
    columns = _build_columns(parsed.headers, parsed.data_rows)
    columns, data_rows, original_rows = _expand_embedded_columns(
        columns, parsed.data_rows, parsed.original_rows
    )
    columns = _assign_column_keys(columns)
    _apply_template(columns, template_columns)
    if use_ai:
        columns = await _refine_with_llm(columns, data_rows, parsed.title, parsed.sheet_name)
        _apply_template(columns, template_columns)
    rows = _build_row_records(columns, data_rows, original_rows)
    return {
        "name": parsed.title,
        "source_filename": filename,
        "source_sheet": parsed.sheet_name,
        "header_row": parsed.header_row,
        "columns": columns,
        "rows": rows,
    }