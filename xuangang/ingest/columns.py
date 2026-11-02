"""列名映射：把官方表格里五花八门的表头对到标准字段。

匹配顺序：精确归一 > 表头包含别名 > 别名包含表头。
``import --inspect`` 会打印这里的诊断结果，方便把新列名沉淀成预设。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .values import clean_text, normalize_key

FIELD_DISPLAY = {
    "dept_code": "部门代码",
    "dept": "部门名称",
    "unit": "用人司局/单位",
    "org_type": "机构性质",
    "post_name": "职位名称",
    "post_code": "职位代码",
    "post_attr": "职位属性",
    "post_distribution": "职位分布",
    "post_desc": "职位简介",
    "headcount": "招考人数",
    "interview_count": "进面人数",
    "major": "专业",
    "education": "学历",
    "degree": "学位",
    "politics": "政治面貌",
    "grassroots": "基层工作经历",
    "grassroots_projects": "服务基层项目",
    "fresh": "应届要求",
    "cert": "资格证书",
    "hukou": "户籍要求",
    "ethnicity": "民族要求",
    "gender": "性别要求",
    "service_years": "最低服务年限",
    "exam_category": "考试类别",
    "interview_ratio": "面试比例",
    "work_place": "工作地点",
    "settle_place": "落户地点",
    "remark": "备注/其他条件",
    "year": "年份",
    "min_score": "最低进面分",
    "max_score": "最高进面分",
    "applicants": "报名人数",
    "ratio": "竞争比",
    "kind": "分数类型",
    "scale": "分数制式",
}


_MULTI_FIELDS = {"major"}
_BAD_SUFFIXES = (
    "网站", "电话", "邮箱", "传真", "地址", "邮编", "简介", "描述",
    "代码", "编码", "分布", "属性", "层级", "类别", "类型", "说明", "链接",
)


@dataclass
class HeaderMatch:
    mapping: dict[str, list[int]]
    header_row: int
    headers: list[str]
    unknown: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    required_hits: list[str] = field(default_factory=list)
    score: float = 0.0
    mapping_confidence: dict[str, float] = field(default_factory=dict)


class ColumnMapper:
    """一套「标准字段 -> 别名列表」的匹配器。"""

    def __init__(self, fields: dict[str, list[str]], required: list[str] | None = None, max_header_scan: int = 10):
        self.raw_fields = {key: list(value) for key, value in fields.items() if value}
        self.fields: dict[str, list[str]] = {
            key: [normalize_key(alias) for alias in values if normalize_key(alias)]
            for key, values in self.raw_fields.items()
        }
        self.required = [item for item in (required or []) if item]
        self.max_header_scan = max(1, int(max_header_scan or 10))
        self._index: list[tuple[str, str, int]] = []
        for field_name, aliases in self.fields.items():
            for order, alias in enumerate(aliases):
                self._index.append((alias, field_name, order))

    def match_header(self, header) -> tuple[str, float] | None:
        text = normalize_key(header)
        if not text:
            return None
        best: tuple[str, float] | None = None
        for alias, field_name, order in self._index:
            if not alias:
                continue
            if text == alias:
                score = 1.0 - order * 0.001
            elif len(alias) >= 2 and alias in text and len(text) <= len(alias) + 4:
                # 太短的别名（如「部门」「职位」）容易误命中「部门网站」「职位代码」
                if len(alias) <= 2 and any(text.endswith(suffix) for suffix in _BAD_SUFFIXES):
                    continue
                score = 0.85 - order * 0.001
            else:
                continue
            if best is None or score > best[1]:
                best = (field_name, score)
        return best

    def match_exact_fields(self, header) -> list[tuple[str, float]]:
        """一个表头可能同时是多个字段的精确别名（如「单位名称」既是部门也是单位）。"""
        text = normalize_key(header)
        if not text:
            return []
        fields: dict[str, float] = {}
        for alias, field_name, order in self._index:
            if alias and alias == text:
                fields[field_name] = max(fields.get(field_name, 0.0), 1.0 - order * 0.001)
        return list(fields.items())

    def map_headers(self, headers: list) -> tuple[dict[str, list[int]], list[str], dict[str, float]]:
        matches: dict[str, list[tuple[float, int]]] = {}
        unknown: list[str] = []
        for index, header in enumerate(headers):
            exact = self.match_exact_fields(header)
            if exact:
                for field_name, score in exact:
                    matches.setdefault(field_name, []).append((score, index))
                continue
            matched = self.match_header(header)
            if not matched:
                if not clean_text(header):
                    continue
                unknown.append(clean_text(header))
                continue
            field_name, score = matched
            matches.setdefault(field_name, []).append((score, index))

        mapping: dict[str, list[int]] = {}
        confidence: dict[str, float] = {}
        for field_name, items in matches.items():
            if field_name in _MULTI_FIELDS:
                selected = [item for item in items]
            else:
                selected = [max(items, key=lambda item: (item[0], -item[1]))]
            indexes = sorted({index for _score, index in selected})
            mapping[field_name] = indexes
            confidence[field_name] = max(score for score, _index in selected)
        return mapping, unknown, confidence

    def detect_header(self, rows: list[list[str]]) -> HeaderMatch | None:
        """在前若干行里选命中已知列最多的一行作为表头。"""
        best: HeaderMatch | None = None
        for row_index in range(min(self.max_header_scan, len(rows))):
            row = rows[row_index]
            if not any(clean_text(cell) for cell in row):
                continue
            mapping, unknown, confidence = self.map_headers(row)
            if not mapping:
                continue
            hits = [item for item in self.required if item in mapping]
            score = float(len(mapping) + 2 * len(hits))
            match = HeaderMatch(
                mapping=mapping,
                header_row=row_index,
                headers=[clean_text(cell) for cell in row],
                unknown=unknown,
                missing_required=[item for item in self.required if item not in mapping],
                required_hits=hits,
                score=score,
                mapping_confidence=confidence,
            )
            if best is None or score > best.score:
                best = match
        return best

    def field_label(self, field_name: str) -> str:
        return FIELD_DISPLAY.get(field_name, field_name)


def cell_text(row: list[str], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    return clean_text(row[index])


def read_field(row: list[str], mapping: dict[str, list[int]], field_name: str, join: str = "；") -> str:
    indexes = mapping.get(field_name) or []
    values = [cell_text(row, index) for index in indexes]
    values = [value for value in values if value]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return join.join(values)


def read_field_levels(row: list[str], mapping: dict[str, list[int]], headers: list[str]) -> dict[str, str]:
    """专业按学历拆列时（如广东省考），按表头里的学历层级分组。"""
    indexes = mapping.get("major") or []
    groups: dict[str, list[str]] = {}
    for index in indexes:
        header = clean_text(headers[index]) if index < len(headers) else ""
        value = cell_text(row, index)
        if not value:
            continue
        level = "all"
        if any(token in header for token in ("研究生", "硕士", "博士")):
            level = "研究生"
        elif "本科" in header:
            level = "本科"
        elif any(token in header for token in ("大专", "专科", "高职")):
            level = "大专"
        groups.setdefault(level, []).append(value)
    return {level: "；".join(values) for level, values in groups.items()}
