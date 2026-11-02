"""读取往年进面分数线（多为民间整理，字段不统一，容错优先）。"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ..config import load_preset
from ..ingest.columns import read_field
from ..ingest.excel import read_table
from ..ingest.values import (
    clean_text,
    infer_score_scale,
    normalize_code,
    normalize_key,
    parse_float,
    parse_int,
    parse_ratio,
    parse_score_range,
)
from ..match.identity import extract_post_code, norm_dept, norm_unit
from ..models import Issue, ScoreRecord
from .positions import build_mapper

_YEAR_RE = re.compile(r"(20\d{2})\s*年?")


@dataclass
class HistorySpec:
    path: Path
    exam: str = "guokao"
    province: str = ""
    year: int | None = None
    kind: str = "笔试最低进面分"
    scale: int | None = None
    preset: str = "guokao"


def load_history(specs: list[HistorySpec], issues: list[Issue]) -> list[ScoreRecord]:
    records: list[ScoreRecord] = []
    preset_cache: dict[str, dict] = {}

    for spec in specs:
        preset_name = spec.preset or "guokao"
        if preset_name not in preset_cache:
            preset_cache[preset_name] = load_preset(preset_name)
        preset = preset_cache[preset_name]
        mapper = build_mapper(preset, "history")
        source_name = Path(spec.path).name

        try:
            sheets = read_table(spec.path)
        except (ValueError, OSError) as exc:
            issues.append(Issue("error", source_name, "", 0, str(exc), "跳过该文件"))
            continue
        if not sheets:
            issues.append(Issue("warn", source_name, "", 0, "文件里没有可读的数据", "跳过该文件"))
            continue

        file_built = 0
        parse_fail = 0
        skipped_kind = 0
        missing_dept = 0
        missing_year = 0
        skipped_sheets: list[str] = []
        no_score_sheets: list[str] = []
        fallback_sheets: list[str] = []
        years: set[int] = set()

        for raw_sheet in sheets:
            header = mapper.detect_header(raw_sheet.rows)
            if header is None:
                skipped_sheets.append(raw_sheet.name)
                continue
            mapping = header.mapping
            title_year = detect_year_from_rows(raw_sheet.rows[:5]) or _year_from_text(raw_sheet.name)
            sheet_year = title_year or spec.year or _year_from_text(source_name)
            if title_year:
                years.add(int(title_year))

            # 分数线表的关键是「岗位名称/代码 + 分数」，其他列（专业、学历等）不参与
            if "post_name" not in mapping and "post_code" not in mapping:
                skipped_sheets.append(raw_sheet.name)
                continue

            score_column = resolve_score_column(mapping, header.headers, raw_sheet, header.header_row)
            if score_column is None:
                no_score_sheets.append(raw_sheet.name)
                continue
            if score_column["field"] != "min_score":
                fallback_sheets.append(f"{raw_sheet.name}（{score_column['header']}）")

            for row_index in range(header.header_row + 1, len(raw_sheet.rows)):
                row = raw_sheet.rows[row_index]
                if not any(clean_text(cell) for cell in row):
                    continue
                post_name = read_field(row, mapping, "post_name")
                post_code = normalize_code(read_field(row, mapping, "post_code"))
                if not post_name and not post_code:
                    continue
                if not post_code:
                    post_code = extract_post_code(post_name)

                score_text = clean_text(row[score_column["index"]]) if score_column["index"] < len(row) else ""
                min_score, max_score, score_kind = parse_score_range(score_text)
                if min_score is None or min_score < 20 or min_score > 1000:
                    parse_fail += 1
                    continue
                if score_kind != "range":
                    column_max = parse_float(read_field(row, mapping, "max_score"))
                    if column_max is not None and column_max >= min_score:
                        max_score = column_max

                dept = read_field(row, mapping, "dept")
                if not dept:
                    missing_dept += 1

                year_value = parse_int(read_field(row, mapping, "year")) or sheet_year
                if year_value:
                    years.add(int(year_value))
                else:
                    missing_year += 1

                kind_value = read_field(row, mapping, "kind") or score_column["kind"] or spec.kind
                if kind_value not in {"笔试最低进面分", "笔试成绩"}:
                    skipped_kind += 1
                    continue
                if kind_value == "笔试成绩":
                    kind_value = "笔试最低进面分"
                scale_value = parse_int(read_field(row, mapping, "scale")) or spec.scale or 0

                records.append(
                    ScoreRecord(
                        year=int(year_value or 0),
                        exam=spec.exam,
                        province=spec.province,
                        source=source_name,
                        sheet=raw_sheet.name,
                        row=row_index + 1,
                        dept=dept,
                        unit=read_field(row, mapping, "unit"),
                        post_name=post_name,
                        post_code=post_code,
                        min_score_raw=score_text,
                        min_score=min_score,
                        max_score=max_score,
                        headcount=parse_int(read_field(row, mapping, "headcount")),
                        interview_count=parse_int(read_field(row, mapping, "interview_count")),
                        applicants=parse_int(read_field(row, mapping, "applicants")),
                        ratio=parse_ratio(read_field(row, mapping, "ratio")),
                        scale=int(scale_value or 0),
                        kind=kind_value or "笔试最低进面分",
                    )
                )
                file_built += 1

        if skipped_sheets:
            issues.append(
                Issue(
                    "info", source_name, "", 0,
                    f"跳过 {len(skipped_sheets)} 个非明细 sheet：{'、'.join(skipped_sheets[:5])}"
                    + ("…" if len(skipped_sheets) > 5 else ""),
                    "这些 sheet 没有岗位名称/代码列，可能是说明、汇总或职位表",
                )
            )
        if no_score_sheets:
            issues.append(
                Issue(
                    "info", source_name, "", 0,
                    f"跳过 {len(no_score_sheets)} 个没有进面分数列的 sheet：{'、'.join(no_score_sheets[:5])}"
                    + ("…" if len(no_score_sheets) > 5 else ""),
                    "分数线表只需要岗位和分数两列；其他 sheet 会被忽略",
                )
            )
        if fallback_sheets:
            issues.append(
                Issue(
                    "info", source_name, "", 0,
                    f"{len(fallback_sheets)} 个 sheet 的分数列是兜底识别的：{'、'.join(fallback_sheets[:3])}",
                    "建议用 import --inspect 核对列名",
                )
            )
        if parse_fail:
            level = "info" if parse_fail > max(1000, file_built * 3) else "warn"
            issues.append(
                Issue(
                    level, source_name, "", 0,
                    f"{parse_fail} 行没有可用的进面分（空值、「未公布」、明显异常等）",
                    "已跳过；若整表都这样，检查分数列是否选对（常见于把职位表也放进了分数线文件）",
                )
            )
        if skipped_kind:
            issues.append(
                Issue(
                    "info", source_name, "", 0,
                    f"{skipped_kind} 行是面试/综合成绩，未计入进面分",
                    "历史分只使用笔试最低进面分",
                )
            )
        if missing_dept:
            issues.append(
                Issue(
                    "warn", source_name, "", 0,
                    f"{missing_dept} 行缺少部门名称",
                    "只能按职位名称/代码匹配，置信度可能降低",
                )
            )
        if missing_year:
            issues.append(
                Issue(
                    "warn", source_name, "", 0,
                    f"{missing_year} 行没有识别出年份",
                    "这些记录不会参与历史分统计；可在网页上手动指定年份",
                )
            )
        if len(years) > 1 or (spec.year and years and int(spec.year) not in years):
            issues.append(
                Issue(
                    "info", source_name, "", 0,
                    f"识别到多个年份：{'、'.join(str(item) for item in sorted(years))}",
                    "已按各 sheet 的标题/名称/年份列分别处理",
                )
            )
        if file_built == 0:
            issues.append(
                Issue(
                    "warn", source_name, "", 0,
                    "这个文件没有解析出任何分数记录",
                    "请用 import --inspect 检查表头和分数列",
                )
            )

    records = _dedupe(records, issues)
    _fill_scales(records, issues)
    return records


def _year_from_text(text: str) -> int | None:
    match = _YEAR_RE.search(clean_text(text))
    return int(match.group(1)) if match else None


def detect_year_from_rows(rows: list[list[str]]) -> int | None:
    for row in rows:
        for cell in row:
            text = clean_text(cell)
            match = _YEAR_RE.search(text)
            if match and ("年" in text or "分数" in text):
                return int(match.group(1))
    return None


def resolve_score_column(
    mapping: dict[str, list[int]],
    headers: list[str],
    raw_sheet,
    header_row: int,
) -> dict | None:
    """优先用映射到的 min_score 列；否则按表头关键词兜底。"""
    indexes = mapping.get("min_score") or []
    if indexes:
        index = indexes[0]
        header = headers[index] if index < len(headers) else ""
        kind = _kind_from_header(header)
        return {"index": index, "header": header, "field": "min_score", "kind": kind}

    priority_groups = (
        ("进面", "入面", "最低进面", "最低分", "进面分"),
        ("笔试成绩", "笔试分数", "笔试总成绩", "笔试"),
        ("综合", "总成绩"),
        ("面试",),
        ("分数",),
    )
    for keywords in priority_groups:
        for index, header in enumerate(headers):
            text = clean_text(header)
            if any(keyword in text for keyword in keywords):
                return {"index": index, "header": text, "field": "fallback", "kind": _kind_from_header(text)}
    # 最后兜底：找第一列在数据行里能解析出 30~400 之间数字的列
    for index in range(len(headers)):
        values = []
        for row in raw_sheet.rows[header_row + 1 : header_row + 8]:
            if index < len(row):
                value = parse_float(row[index])
                if value is not None:
                    values.append(value)
        if len(values) >= 3 and all(30 <= value <= 400 for value in values):
            return {"index": index, "header": headers[index], "field": "fallback", "kind": None}
    return None


def _kind_from_header(header: str) -> str | None:
    text = clean_text(header)
    if "综合" in text or "总成绩" in text:
        return "综合成绩"
    if "面试" in text and "进面" not in text:
        return "面试成绩"
    if "笔试" in text or "进面" in text or "入面" in text or "最低分" in text:
        return "笔试最低进面分"
    return None


def _dedupe(records: list[ScoreRecord], issues: list[Issue]) -> list[ScoreRecord]:
    seen: dict[tuple, ScoreRecord] = {}
    duplicates = 0
    for record in records:
        key = (
            record.year,
            record.exam,
            record.province,
            clean_text(record.dept),
            clean_text(record.unit),
            clean_text(record.post_name),
            record.post_code,
            record.min_score,
            record.max_score,
        )
        if key in seen:
            duplicates += 1
            continue
        seen[key] = record
    if duplicates:
        issues.append(
            Issue("info", "", "", 0, f"分数线表内重复记录 {duplicates} 条，已去重", "按年份+部门+职位+分数去重")
        )
    return list(seen.values())


def _fill_scales(records: list[ScoreRecord], issues: list[Issue]) -> None:
    """推断分数制式。

    国考同一份分数线里可能混用 200 分制（普通职位）和 100 分制（铁路公安、
    银保监等合成成绩），所以先按「部门/单位」分组推断，再按年份兜底。
    """
    unknown = [record for record in records if not record.scale and record.min_score is not None]
    if not unknown:
        return
    unknown_ids = {id(record) for record in unknown}

    dept_groups: dict[tuple, list[ScoreRecord]] = {}
    for record in unknown:
        key = (
            record.exam,
            record.province,
            norm_dept(record.dept) or norm_unit(record.unit) or normalize_key(record.post_name)[:12],
        )
        dept_groups.setdefault(key, []).append(record)

    inferred_records: list[ScoreRecord] = []
    unresolved: list[ScoreRecord] = []
    for _key, group in dept_groups.items():
        values = [record.min_score for record in group if record.min_score is not None]
        if not values:
            unresolved.extend(group)
            continue
        inferred = infer_score_scale(values)
        if len(values) < 3:
            # 小样本时用分数绝对值辅助判断
            if all(value < 85 for value in values):
                inferred = 100
            elif all(value > 150 for value in values):
                inferred = 300
        if inferred:
            for record in group:
                record.scale = inferred
            inferred_records.extend(group)
        else:
            unresolved.extend(group)

    year_known: dict[tuple, Counter] = {}
    for record in records:
        if record.scale:
            year_known.setdefault((record.exam, record.province, record.year, record.kind), Counter())[record.scale] += 1
    for record in unresolved:
        key = (record.exam, record.province, record.year, record.kind)
        counter = year_known.get(key)
        if counter:
            record.scale = counter.most_common(1)[0][0]
        else:
            record.scale = 200
        inferred_records.append(record)

    # 国考只有 200 分制（普通职位）和 100 分制（铁路公安/银保监等合成成绩），
    # 同一部门也可能混排；用分数绝对值再校正一次，避免把 100 分制误判成 150。
    for record in inferred_records:
        if record.exam != "guokao" or id(record) not in unknown_ids or record.min_score is None:
            continue
        if record.min_score < 85:
            record.scale = 100
        elif record.min_score >= 90:
            record.scale = 200

    counts: Counter = Counter(record.scale for record in inferred_records)
    if counts:
        detail = "、".join(f"{scale} 分制 {count} 条" for scale, count in sorted(counts.items()))
        issues.append(
            Issue(
                "info", "", "", 0,
                f"分数制式按部门/年份自动推断：{detail}",
                "同一场考试可能混用制式；需要固定时在网页选择满分或在 manifest 写 scale",
            )
        )

    mixed_years: dict[tuple, set[int]] = {}
    for record in records:
        if record.scale:
            mixed_years.setdefault((record.exam, record.province, record.year, record.kind), set()).add(record.scale)
    for (exam, province, year, kind), scales in mixed_years.items():
        if len(scales) > 1:
            issues.append(
                Issue(
                    "info", "", "", 0,
                    f"{exam}/{province or '全国'}/{year}/{kind} 混用了多种分数制式：{sorted(scales)}",
                    "预测时会先折算到 200 分制再比较",
                )
            )
