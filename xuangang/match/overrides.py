"""人工岗位对应关系（manual_links.csv）。

民间分数线表与官方岗位表总有算法对不上的记录。人工只需加一行：

    history_source,history_year,dept,post_name,position_id,action,note
    2026国考进面分数.xlsx,2026,国家税务总局广东省税务局,一级行政执法员（一）,2027-guokao-全国-100110001001,link,人工核对

``action=ignore`` 表示这条记录不再参与匹配。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ..ingest.values import normalize_key
from .identity import norm_dept, norm_post

FIELDNAMES = ["history_source", "history_year", "dept", "post_name", "position_id", "action", "note"]

HEADER_COMMENT = """# 人工岗位对应表
# 用法：在下面追加一行，把「某年某岗位」的分数线手工指到某个岗位 id 上。
# history_source：分数线文件名；history_year：年份；dept/post_name：该行的部门与职位名称。
# position_id：目标岗位 id（在 out/.../positions.csv 或报告「匹配链路」页里查）。
# action：link=强制对应；ignore=忽略这条记录。
history_source,history_year,dept,post_name,position_id,action,note
"""


@dataclass
class Override:
    source: str
    year: int
    dept: str
    post_name: str
    position_id: str
    action: str
    note: str = ""


def _key(source: str, year: int, dept: str, post_name: str) -> tuple[str, int, str, str]:
    return (
        normalize_key(Path(source).stem),
        int(year or 0),
        norm_dept(dept),
        norm_post(post_name),
    )


def load_overrides(path: Path) -> dict[tuple[str, int, str, str], Override]:
    path = Path(path)
    if not path.exists():
        return {}
    overrides: dict[tuple[str, int, str, str], Override] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(row for row in handle if not row.lstrip().startswith("#"))
        for row in reader:
            source = (row.get("history_source") or "").strip()
            post_name = (row.get("post_name") or "").strip()
            if not source and not post_name:
                continue
            try:
                year = int((row.get("history_year") or "0").strip() or 0)
            except ValueError:
                year = 0
            override = Override(
                source=source,
                year=year,
                dept=(row.get("dept") or "").strip(),
                post_name=post_name,
                position_id=(row.get("position_id") or "").strip(),
                action=(row.get("action") or "link").strip().lower() or "link",
                note=(row.get("note") or "").strip(),
            )
            overrides[_key(source, year, override.dept, override.post_name)] = override
    return overrides


def lookup_override(overrides, source: str, year: int, dept: str, post_name: str) -> Override | None:
    if not overrides:
        return None
    base = Path(source).stem
    for candidate_year in (int(year or 0), 0):
        normalized = _key(base, candidate_year, dept, post_name)
        if normalized in overrides:
            return overrides[normalized]
    # 人工表里留空的部门/职位名视为通配
    source_key = normalize_key(Path(source).stem)
    dept_key = norm_dept(dept)
    post_key = norm_post(post_name)
    for override in overrides.values():
        if normalize_key(Path(override.source).stem) != source_key:
            continue
        if override.year and int(override.year) not in (int(year or 0), 0):
            continue
        if override.dept and norm_dept(override.dept) != dept_key:
            continue
        if override.post_name and norm_post(override.post_name) != post_key:
            continue
        return override
    return None


def ensure_override_file(path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(HEADER_COMMENT, encoding="utf-8")
    return path


def append_override(path: Path, override: Override) -> None:
    path = Path(path)
    ensure_override_file(path)
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writerow(
            {
                "history_source": override.source,
                "history_year": override.year,
                "dept": override.dept,
                "post_name": override.post_name,
                "position_id": override.position_id,
                "action": override.action,
                "note": override.note,
            }
        )
