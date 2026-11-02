"""上传文件自动诊断：表头、列映射、年份与分数制式建议。

网页端上传后立刻调用，让用户不用手写 manifest、不用选年份。
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from ..config import default_preset, load_preset
from ..rules.extras import PROVINCES, _SHORT
from .columns import FIELD_DISPLAY, read_field
from .excel import read_table
from .history import detect_year_from_rows, resolve_score_column
from .positions import build_mapper
from .values import clean_text, infer_score_scale, parse_int, parse_score_range

_YEAR_RE = re.compile(r"(20\d{2})")


def guess_exam_province(filename: str, default_exam: str, default_province: str) -> tuple[str, str]:
    name = clean_text(filename)
    province = default_province or ""
    for full in sorted(PROVINCES, key=len, reverse=True):
        short = _SHORT.get(full, full)
        if full in name or (short and short in name):
            province = full
            break
    exam = default_exam or "guokao"
    if "国考" in name or "中央机关" in name or "中央党群" in name:
        exam = "guokao"
    elif "省考" in name or province:
        exam = "shengkao"
    return exam, province


def guess_year_from_name(filename: str) -> Optional[int]:
    match = _YEAR_RE.search(clean_text(filename))
    return int(match.group(1)) if match else None


def inspect_file(
    path: Path,
    kind: str,
    *,
    default_exam: str = "guokao",
    default_province: str = "",
    default_year: Optional[int] = None,
) -> dict[str, Any]:
    path = Path(path)
    exam, province = guess_exam_province(path.name, default_exam, default_province)
    preset_name = default_preset(exam, province)
    preset = load_preset(preset_name)
    mapper = build_mapper(preset, "positions" if kind == "positions" else "history")

    sheets_raw = read_table(path)
    sheets: list[dict[str, Any]] = []
    warnings: list[str] = []
    score_values: list[float] = []
    year_values: list[int] = []
    detected_kind: Optional[str] = None
    total_rows = 0

    for raw_sheet in sheets_raw:
        header = mapper.detect_header(raw_sheet.rows)
        if header is None:
            warnings.append(f"sheet「{raw_sheet.name}」没有识别出表头")
            continue
        data_rows = max(0, len(raw_sheet.rows) - header.header_row - 1)
        total_rows += data_rows
        mapping: dict[str, Any] = {}
        for field_name, indexes in header.mapping.items():
            columns = [
                header.headers[index] for index in indexes if index < len(header.headers)
            ]
            mapping[field_name] = {
                "label": FIELD_DISPLAY.get(field_name, field_name),
                "columns": columns,
                "confidence": round(header.mapping_confidence.get(field_name, 0.0), 2),
            }
        missing = [FIELD_DISPLAY.get(item, item) for item in header.missing_required]
        if missing and kind == "positions":
            warnings.append(f"sheet「{raw_sheet.name}」缺少关键列：" + "、".join(missing))
        sheets.append(
            {
                "name": raw_sheet.name,
                "header_row": header.header_row + 1,
                "rows": data_rows,
                "mapping": mapping,
                "missing": missing,
                "unknown": header.unknown[:15],
            }
        )

        if kind != "history":
            continue
        column = resolve_score_column(header.mapping, header.headers, raw_sheet, header.header_row)
        if column is None:
            warnings.append(f"sheet「{raw_sheet.name}」没有识别出进面分数列")
            continue
        detected_kind = detected_kind or column.get("kind")
        for row in raw_sheet.rows[header.header_row + 1 :]:
            if len(score_values) < 500:
                index = column["index"]
                if index < len(row):
                    value, _max, _kind = parse_score_range(row[index])
                    if value is not None and 0 < value <= 1000:
                        score_values.append(value)
            if "year" in header.mapping:
                year_value = parse_int(read_field(row, header.mapping, "year"))
                if year_value:
                    year_values.append(year_value)
        if column["field"] == "fallback":
            warnings.append(
                f"sheet「{raw_sheet.name}」的分数列按「{column['header']}」兜底识别，建议核对"
            )

    if not sheets:
        warnings.append("文件里没有识别到任何表头，可能不是岗位表/分数线表")

    suggested_year = None
    if year_values:
        suggested_year = Counter(year_values).most_common(1)[0][0]
    if suggested_year is None and sheets_raw:
        suggested_year = detect_year_from_rows(sheets_raw[0].rows[:4]) or guess_year_from_name(path.name)
    if suggested_year is None:
        suggested_year = default_year

    suggested_scale = None
    if kind == "history" and score_values:
        suggested_scale = infer_score_scale(score_values)
        if suggested_scale == 200 and score_values:
            low_share = sum(1 for value in score_values if value < 85) / len(score_values)
            if low_share >= 0.05:
                # 国考里铁路公安/银保监等使用 100 分制合成成绩，和普通职位混排
                suggested_scale = None
                warnings.append("分数制式疑似混用（如 200 分制 + 100 分制），默认按部门自动推断")
        elif suggested_scale == 300 and score_values:
            low_share = sum(1 for value in score_values if value < 150) / len(score_values)
            if low_share >= 0.05:
                suggested_scale = None
                warnings.append("分数制式疑似混用，默认按部门自动推断")

    suggested: dict[str, Any] = {
        "exam": exam,
        "province": province,
        "year": suggested_year,
        "scale": suggested_scale,
        "kind": detected_kind or "笔试最低进面分",
        "preset": preset_name,
    }
    return {
        "ok": True,
        "kind": kind,
        "name": path.name,
        "sheets": sheets,
        "suggested": suggested,
        "total_rows": total_rows,
        "warnings": warnings[:20],
    }
