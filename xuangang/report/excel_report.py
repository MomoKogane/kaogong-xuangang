"""生成 Excel 报告（多 sheet，可直接筛选）。"""

from __future__ import annotations

from pathlib import Path

import xlsxwriter

from ..models import ReportRow
from .common import (
    failed_text,
    history_text,
    status_reason,
    tier_label,
    unknown_text,
    warnings_text,
)

TIER_COLORS = {
    "保": "#C6EFCE",
    "稳": "#BDD7EE",
    "冲": "#FFEB9C",
    "风险": "#FFC7CE",
}
STATUS_COLORS = {"符合": "#C6EFCE", "存疑": "#FFEB9C", "不符合": "#D9D9D9"}

BASE_COLUMNS = [
    ("序号", 6),
    ("分档", 6),
    ("指数", 7),
    ("预测进面分", 11),
    ("预测分制", 8),
    ("历史年数", 9),
    ("置信度", 8),
    ("热度", 7),
    ("选岗优势", 24),
    ("部门", 26),
    ("用人司局", 26),
    ("职位名称", 26),
    ("职位代码", 16),
    ("招考人数", 9),
    ("学历", 12),
    ("学位", 10),
    ("专业", 30),
    ("政治面貌", 12),
    ("基层经历", 10),
    ("应届", 12),
    ("证书要求", 18),
    ("工作地点", 16),
    ("备注", 40),
    ("匹配理由", 50),
    ("岗位id", 34),
]


def _make_formats(workbook) -> dict:
    header = workbook.add_format(
        {"bold": True, "font_color": "#FFFFFF", "bg_color": "#1F4E79", "border": 1, "text_wrap": True, "valign": "vcenter"}
    )
    title = workbook.add_format({"bold": True, "font_size": 14, "font_color": "#1F4E79"})
    text = workbook.add_format({"border": 1, "valign": "top", "text_wrap": True})
    plain = workbook.add_format({"border": 1, "valign": "top"})
    number = workbook.add_format({"border": 1, "valign": "top", "num_format": "0.0"})
    center = workbook.add_format({"border": 1, "valign": "top", "align": "center"})
    warning = workbook.add_format({"border": 1, "valign": "top", "font_color": "#9C0006"})
    formats = {
        "header": header,
        "title": title,
        "text": text,
        "plain": plain,
        "number": number,
        "center": center,
        "warning": warning,
    }
    for label, color in TIER_COLORS.items():
        formats[f"tier_{label}"] = workbook.add_format(
            {"border": 1, "valign": "top", "align": "center", "bg_color": color, "bold": True}
        )
    for label, color in STATUS_COLORS.items():
        formats[f"status_{label}"] = workbook.add_format(
            {"border": 1, "valign": "top", "align": "center", "bg_color": color}
        )
    return formats


def _write_rows(worksheet, headers, widths, rows, formats, wrap_columns=(), start_row=1):
    for column, (header, width) in enumerate(zip(headers, widths)):
        worksheet.set_column(column, column, width)
        worksheet.write(start_row - 1, column, header, formats["header"])
    worksheet.freeze_panes(start_row, 0)
    if rows:
        worksheet.autofilter(start_row - 1, 0, start_row - 1 + len(rows), len(headers) - 1)
    for offset, row in enumerate(rows):
        excel_row = start_row + offset
        for column, value in enumerate(row):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                worksheet.write_number(excel_row, column, value, formats["number"])
            else:
                fmt = formats["text"] if column in wrap_columns else formats["plain"]
                worksheet.write_string(excel_row, column, "" if value is None else str(value), fmt)


def _row_cells(row: ReportRow, index: int) -> list:
    position = row.position
    evaluation = row.evaluation
    advantage = []
    if evaluation.preference == 1.0:
        advantage.append(f"意向地区:{evaluation.preference_label}")
    advantage.extend(evaluation.barrier_tags)
    return [
        index,
        tier_label(evaluation),
        evaluation.index,
        evaluation.predicted if evaluation.predicted is not None else "",
        evaluation.predicted_scale if evaluation.predicted is not None else "",
        len(evaluation.history),
        evaluation.confidence,
        evaluation.heat_label,
        "、".join(advantage),
        position.dept,
        position.unit,
        position.post_name,
        position.post_code,
        position.headcount,
        position.education_raw,
        position.degree_raw,
        position.major_raw,
        position.politics_raw,
        position.grassroots_raw,
        position.fresh_raw,
        position.cert_raw,
        position.work_place,
        position.remark,
        status_reason(row) + (f"（{history_text(evaluation)}）" if evaluation.history else ""),
        position.id,
    ]


def write_workbook(result, path: Path, profile=None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(str(path), {"nan_inf_to_errors": True})
    formats = _make_formats(workbook)
    headers = [item[0] for item in BASE_COLUMNS]
    widths = [item[1] for item in BASE_COLUMNS]
    wrap_columns = {1, 16, 22, 23}

    approved = [row for row in result.rows if row.outcome.status == "符合"]
    uncertain = [row for row in result.rows if row.outcome.status == "存疑"]
    rejected = [row for row in result.rows if row.outcome.status == "不符合"]

    sheet = workbook.add_worksheet("推荐岗位")
    _write_rows(sheet, headers, widths, [_row_cells(row, index) for index, row in enumerate(approved, start=1)], formats, wrap_columns)

    sheet = workbook.add_worksheet("全部符合")
    _write_rows(sheet, headers, widths, [_row_cells(row, index) for index, row in enumerate(approved, start=1)], formats, wrap_columns)

    sheet = workbook.add_worksheet("存疑核对")
    uncertain_headers = headers + ["待确认项", "提醒"]
    uncertain_widths = widths + [26, 30]
    rows = []
    for index, row in enumerate(uncertain, start=1):
        cells = _row_cells(row, index)
        cells.append(unknown_text(row.outcome) or "—")
        cells.append(warnings_text(row.outcome) or "—")
        rows.append(cells)
    _write_rows(sheet, uncertain_headers, uncertain_widths, rows, formats, set(wrap_columns) | {25, 26})

    sheet = workbook.add_worksheet("不符合")
    rejected_headers = headers + ["失败维度", "原因"]
    rejected_widths = widths + [22, 46]
    rows = []
    for index, row in enumerate(rejected, start=1):
        cells = _row_cells(row, index)
        cells.append(failed_text(row.outcome) or "—")
        cells.append(status_reason(row, limit=6))
        rows.append(cells)
    _write_rows(sheet, rejected_headers, rejected_widths, rows, formats, set(wrap_columns) | {25, 26})

    sheet = workbook.add_worksheet("岗位历史")
    history_headers = ["岗位id", "部门", "用人司局", "职位名称", "年份", "最低进面分", "最高进面分", "分数制式", "来源文件"]
    history_widths = [34, 26, 24, 26, 8, 12, 12, 10, 28]
    rows = []
    for row in result.rows:
        for point in row.evaluation.history:
            rows.append(
                [
                    row.position.id,
                    row.position.dept,
                    row.position.unit,
                    row.position.post_name,
                    point.year,
                    point.min_score if point.min_score is not None else "",
                    point.max_score if point.max_score is not None else "",
                    point.scale,
                    point.source,
                ]
            )
    _write_rows(sheet, history_headers, history_widths, rows, formats)

    sheet = workbook.add_worksheet("匹配链路")
    link_headers = ["历史记录key", "岗位id", "匹配方式", "置信分", "是否采用", "说明"]
    link_widths = [26, 34, 12, 9, 9, 42]
    rows = [
        [
            link.history_key,
            link.position_id,
            link.link_type,
            link.score,
            "是" if link.accepted else "否",
            link.note,
        ]
        for link in result.links
    ]
    _write_rows(sheet, link_headers, link_widths, rows, formats)

    sheet = workbook.add_worksheet("未匹配分数线")
    unmatched_headers = ["年份", "部门", "单位", "职位名称", "职位代码", "最低分", "最高分", "来源文件", "sheet", "行号", "原因"]
    unmatched_widths = [8, 26, 20, 26, 16, 10, 10, 26, 14, 8, 40]
    record_by_key = {
        f"{record.year}|{record.source}|{record.sheet}|{record.row}": record for record in result.records
    }
    rows = []
    for link in result.links:
        if link.position_id:
            continue
        record = record_by_key.get(link.history_key)
        if record is None:
            continue
        rows.append(
            [
                record.year,
                record.dept,
                record.unit,
                record.post_name,
                record.post_code,
                record.min_score if record.min_score is not None else "",
                record.max_score if record.max_score is not None else "",
                record.source,
                record.sheet,
                record.row,
                link.note,
            ]
        )
    _write_rows(sheet, unmatched_headers, unmatched_widths, rows, formats)

    sheet = workbook.add_worksheet("数据质量")
    issue_headers = ["级别", "文件", "sheet", "行号", "说明", "采取动作", "字段"]
    issue_widths = [8, 26, 16, 8, 60, 34, 14]
    rows = [[issue.level, issue.file, issue.sheet, issue.row, issue.message, issue.action, issue.field] for issue in result.issues]
    _write_rows(sheet, issue_headers, issue_widths, rows, formats)

    sheet = workbook.add_worksheet("说明")
    sheet.set_column(0, 0, 120)
    notes = [
        "考公选岗报告说明",
        "",
        "1. 本报告只做初筛：最终能否报考以招录机关解释和当年公告为准。",
        "2. 判定分为三态：符合 / 存疑（需人工核对）/ 不符合（含失败维度）。",
        "3. 分档（冲/稳/保/风险）基于你的预估分与近三年最低进面分的加权预测，是参考值，不是录取概率。",
        "4. 历史分数线来自民间整理，制式、口径可能不一致；匹配链路页给出了每条记录的对应方式和置信度。",
        "5. 人工可编辑 data/manual_links.csv 修正错配，重跑后优先级最高。",
        "6. 数据质量页记录了清洗动作，红色 warning 建议逐条核对。",
        "7. 「选岗优势」= 意向地区命中，或岗位限制（性别/户籍/民族/基层项目/证书等）对符合条件的你形成的竞争壁垒；它会提高推荐指数。",
        "8. 岗位条件来自今年岗位表；往年分数线只提取「岗位名称/代码 + 分数」，不使用往年的专业/学历等要求。",
        "",
        f"生成时间：{_now()}",
    ]
    if profile is not None:
        from .common import profile_text

        notes.insert(2, "个人条件：" + profile_text(profile))
    for index, line in enumerate(notes):
        sheet.write_string(index, 0, line, formats["title"] if index == 0 else formats["plain"])
    workbook.close()
    return path


def _now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
