"""读取 Excel / CSV，统一成「sheet 名 + 字符串二维表」。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .values import clean_text


@dataclass
class RawSheet:
    name: str
    rows: list[list[str]]


def read_table(path: Path) -> list[RawSheet]:
    """读取一个表格文件，返回所有 sheet。"""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return _read_xlsx(path)
    if suffix == ".xls":
        from .xls import read_xls

        return read_xls(path)
    if suffix == ".csv":
        return _read_csv(path)
    raise ValueError(f"不支持的文件类型：{path.name}（支持 .xlsx / .xlsm / .xls / .csv）")


def _fill_merged(ws, grid: list[list[str]]) -> None:
    """把合并单元格的值填到整个合并区域，避免表头下半行全是空。"""
    try:
        merged = list(ws.merged_cells.ranges)
    except AttributeError:
        return
    if not merged:
        return
    min_row = ws.min_row or 1
    min_col = ws.min_column or 1
    for rng in merged:
        top_row = rng.min_row - min_row
        left_col = rng.min_col - min_col
        if top_row < 0 or left_col < 0 or top_row >= len(grid):
            continue
        row_values = grid[top_row]
        if left_col >= len(row_values):
            continue
        value = row_values[left_col]
        if not value:
            continue
        for row_offset in range(rng.max_row - rng.min_row + 1):
            target_row = top_row + row_offset
            if target_row >= len(grid):
                break
            target = grid[target_row]
            for col_offset in range(rng.max_col - rng.min_col + 1):
                target_col = left_col + col_offset
                if target_col >= len(target):
                    break
                target[target_col] = value


def _trim(grid: list[list[str]]) -> list[list[str]]:
    """去掉尾部全空的行和列。"""
    while grid and not any(cell.strip() for cell in grid[-1]):
        grid.pop()
    if not grid:
        return grid
    max_cols = max(len(row) for row in grid)
    last_col = -1
    for row in grid:
        for index, cell in enumerate(row):
            if cell.strip():
                last_col = max(last_col, index)
    if last_col < 0:
        return []
    trimmed: list[list[str]] = []
    for row in grid:
        padded = list(row) + [""] * (max_cols - len(row))
        trimmed.append(padded[: last_col + 1])
    return trimmed


def _read_xlsx(path: Path) -> list[RawSheet]:
    import openpyxl

    workbook = openpyxl.load_workbook(path, data_only=True, read_only=False)
    sheets: list[RawSheet] = []
    try:
        for ws in workbook.worksheets:
            grid: list[list[str]] = []
            for row in ws.iter_rows(values_only=True):
                grid.append([clean_text(cell) for cell in row])
            _fill_merged(ws, grid)
            grid = _trim(grid)
            if grid:
                sheets.append(RawSheet(name=ws.title, rows=grid))
    finally:
        workbook.close()
    return sheets


def _read_csv(path: Path) -> list[RawSheet]:
    text = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError(f"无法识别 CSV 编码：{path.name}（请另存为 UTF-8）")
    sample = "\n".join(text.splitlines()[:20])
    delimiter = ","
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in sample else ","
    rows = [[clean_text(cell) for cell in row] for row in csv.reader(text.splitlines(), delimiter=delimiter)]
    rows = _trim(rows)
    return [RawSheet(name=path.stem, rows=rows)] if rows else []
