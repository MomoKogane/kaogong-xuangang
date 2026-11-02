"""读取官方岗位表，标准化成 Position。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..ingest.columns import ColumnMapper, read_field, read_field_levels, FIELD_DISPLAY
from ..ingest.excel import read_table
from ..ingest.values import (
    clean_text,
    is_blank,
    normalize_code,
    normalize_key,
    parse_int,
    split_tokens,
)
from ..match.identity import entity_key, extract_post_code, norm_dept, norm_post
from ..models import Issue, Position
from ..rules.notes import extract_requirements


@dataclass
class PositionSpec:
    path: Path
    exam: str = "guokao"
    province: str = ""
    year: int = 2027
    preset: str = "guokao"
    sheet_filter: list[str] | None = None


def build_mapper(preset: dict, section: str) -> ColumnMapper:
    config = preset.get(section) or {}
    fields = config.get("fields") or {}
    required = config.get("required") or []
    scan = int(config.get("max_header_scan", 10) or 10)
    return ColumnMapper(fields, required, scan)


def load_positions(specs: list[PositionSpec], issues: list[Issue]) -> list[Position]:
    positions: list[Position] = []
    seen_ids: dict[str, Position] = {}
    preset_cache: dict[str, dict] = {}
    duplicate_ids = 0

    for spec in specs:
        from ..config import load_preset

        preset_name = spec.preset or spec.exam
        if preset_name not in preset_cache:
            preset_cache[preset_name] = load_preset(preset_name)
        preset = preset_cache[preset_name]
        mapper = build_mapper(preset, "positions")
        source_name = Path(spec.path).name

        try:
            sheets = read_table(spec.path)
        except (ValueError, OSError) as exc:
            issues.append(Issue("error", source_name, "", 0, str(exc), "跳过该文件"))
            continue

        if not sheets:
            issues.append(Issue("warn", source_name, "", 0, "文件里没有可读的数据", "跳过该文件"))
            continue

        for raw_sheet in sheets:
            if spec.sheet_filter and raw_sheet.name not in spec.sheet_filter:
                continue
            header = mapper.detect_header(raw_sheet.rows)
            if header is None:
                issues.append(
                    Issue(
                        "warn", source_name, raw_sheet.name, 0,
                        "没有识别出表头（未命中任何已知列名）", "跳过该 sheet",
                    )
                )
                continue

            missing = header.missing_required
            critical = {"dept", "post_name", "major", "education"}
            if critical & set(missing):
                issues.append(
                    Issue(
                        "warn", source_name, raw_sheet.name, header.header_row + 1,
                        "缺少关键列：" + "、".join(FIELD_DISPLAY.get(item, item) for item in missing),
                        "仍尝试解析，结果可能不完整",
                    )
                )
            if not header.mapping:
                continue

            skipped = 0
            built = 0
            headcount_missing = 0
            for row_index in range(header.header_row + 1, len(raw_sheet.rows)):
                row = raw_sheet.rows[row_index]
                if not any(clean_text(cell) for cell in row):
                    skipped += 1
                    continue
                if _is_repeated_header(row, header.headers):
                    skipped += 1
                    continue
                position = _build_position(
                    row=row,
                    mapping=header.mapping,
                    headers=header.headers,
                    spec=spec,
                    source_name=source_name,
                    sheet_name=raw_sheet.name,
                    row_number=row_index + 1,
                    issues=issues,
                )
                if position is None:
                    skipped += 1
                    continue
                if position.headcount <= 0:
                    headcount_missing += 1
                if position.id in seen_ids:
                    existing = seen_ids[position.id]
                    if _same_position(existing, position):
                        issues.append(
                            Issue(
                                "info", source_name, raw_sheet.name, row_index + 1,
                                f"重复岗位（id={position.id}），已跳过", "保留先出现的一条",
                            )
                        )
                        skipped += 1
                        continue
                    suffix = 2
                    while f"{position.id}#{suffix}" in seen_ids:
                        suffix += 1
                    position.id = f"{position.id}#{suffix}"
                    duplicate_ids += 1
                seen_ids[position.id] = position
                positions.append(position)
                built += 1

            if built == 0:
                issues.append(Issue("warn", source_name, raw_sheet.name, 0, "该 sheet 没有解析出岗位", ""))
            if headcount_missing:
                issues.append(
                    Issue(
                        "warn", source_name, raw_sheet.name, 0,
                        f"{headcount_missing} 行「招考人数」缺失或无法解析，按 0 记",
                        "报告中会显示为 0，请核对原表",
                    )
                )
            if skipped:
                issues.append(
                    Issue("info", source_name, raw_sheet.name, 0, f"跳过 {skipped} 行（空行/重复/重复表头）", "")
                )

    if duplicate_ids:
        issues.append(
            Issue(
                "info", "", "", 0,
                f"{duplicate_ids} 个岗位的职位代码在文件内不唯一（或为空），已用部门/单位/职位名区分并加后缀",
                "对应分数线时会再按部门/职位名确认；若代码本应唯一，请核对源表",
            )
        )

    return positions


def _is_repeated_header(row: list[str], headers: list[str]) -> bool:
    if not headers:
        return False
    matches = 0
    for index, value in enumerate(row):
        if index < len(headers) and clean_text(value) and clean_text(value) == clean_text(headers[index]):
            matches += 1
    return matches >= max(3, len(headers) // 2)


def _first(row: list[str], mapping: dict[str, list[int]], field_name: str) -> str:
    indexes = mapping.get(field_name) or []
    for index in indexes:
        if index < len(row):
            value = clean_text(row[index])
            if value:
                return value
    return ""


def _build_position(
    *,
    row: list[str],
    mapping: dict[str, list[int]],
    headers: list[str],
    spec: PositionSpec,
    source_name: str,
    sheet_name: str,
    row_number: int,
    issues: list[Issue],
) -> Position | None:
    dept = read_field(row, mapping, "dept")
    post_name = read_field(row, mapping, "post_name")
    if not dept and not post_name:
        return None
    if not post_name:
        return None

    post_code = normalize_code(_first(row, mapping, "post_code"))
    if not post_code:
        post_code = extract_post_code(post_name) or extract_post_code(_first(row, mapping, "remark"))
        if post_code:
            issues.append(
                Issue(
                    "info", source_name, sheet_name, row_number,
                    f"职位代码从名称/备注中提取：{post_code}", "已用于岗位 id",
                )
            )

    headcount_raw = _first(row, mapping, "headcount")
    headcount = parse_int(headcount_raw)
    if headcount is None:
        headcount = 0

    major_by_level = read_field_levels(row, mapping, headers)
    major_raw = "；".join(value for value in major_by_level.values() if value)
    if not major_raw:
        major_raw = read_field(row, mapping, "major")

    remark = read_field(row, mapping, "remark")
    post_desc = read_field(row, mapping, "post_desc")
    cert_raw = read_field(row, mapping, "cert")
    hukou_raw = read_field(row, mapping, "hukou")
    ethnicity_raw = read_field(row, mapping, "ethnicity")
    gender_raw = read_field(row, mapping, "gender")

    position = Position(
        id="",
        year=spec.year,
        exam=spec.exam,
        province=spec.province,
        source=source_name,
        sheet=sheet_name,
        row=row_number,
        dept_code=_first(row, mapping, "dept_code"),
        dept=dept,
        unit=_first(row, mapping, "unit"),
        org_type=_first(row, mapping, "org_type"),
        post_name=post_name,
        post_code=post_code,
        post_attr=_first(row, mapping, "post_attr"),
        post_distribution=_first(row, mapping, "post_distribution"),
        post_desc=post_desc,
        headcount=headcount,
        headcount_raw=headcount_raw,
        major_raw=major_raw,
        major_by_level=major_by_level,
        education_raw=_first(row, mapping, "education"),
        degree_raw=_first(row, mapping, "degree"),
        politics_raw=_first(row, mapping, "politics"),
        grassroots_raw=_first(row, mapping, "grassroots"),
        grassroots_projects_raw=_first(row, mapping, "grassroots_projects"),
        fresh_raw=_first(row, mapping, "fresh"),
        cert_raw=cert_raw,
        hukou_raw=hukou_raw,
        ethnicity_raw=ethnicity_raw,
        gender_raw=gender_raw,
        exam_category=_first(row, mapping, "exam_category"),
        interview_ratio=_first(row, mapping, "interview_ratio"),
        work_place=_first(row, mapping, "work_place"),
        settle_place=_first(row, mapping, "settle_place"),
        remark=remark,
    )
    position.entity_key = entity_key(position.dept, position.unit, position.post_name, position.post_attr)
    if not position.dept and position.unit:
        position.dept = position.unit
    position.notes = extract_requirements(position.text_blob())

    token = normalize_code(post_code)
    if not token:
        token = f"{norm_dept(dept)[:16]}-{norm_post(post_name)[:16]}"
    position.id = f"{spec.year}-{spec.exam}-{spec.province or '全国'}-{token}"
    return position


def _same_position(left: Position, right: Position) -> bool:
    return (
        left.dept == right.dept
        and left.unit == right.unit
        and left.post_name == right.post_name
        and left.major_raw == right.major_raw
    )
