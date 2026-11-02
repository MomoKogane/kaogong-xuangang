"""岗位身份的归一与相似度。

跨年职位代码会整体变化，民间分数线表又常常缺代码、部门写法不一，
所以用「归一后的部门 / 用人司局 / 职位名称 / 职位属性」做实体键，
再用 difflib 做模糊打分。
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..ingest.values import clean_text, normalize_key

_DEPT_SUFFIXES = (
    "（参照公务员法管理）",
    "(参照公务员法管理)",
    "（参公）",
    "(参公)",
    "参照公务员法管理",
    "（本级）",
    "(本级)",
    "（本级机关）",
    "(本级机关)",
    "（机关）",
    "(机关)",
)

_CODE_IN_TEXT = re.compile(r"(?:职位|岗位|职位代码|岗位代码)?\s*代码?\s*[:：]?\s*(\d{6,})")


def strip_suffixes(text: str) -> str:
    result = text
    for suffix in _DEPT_SUFFIXES:
        result = result.replace(suffix, "")
    return result


def norm_dept(value) -> str:
    return normalize_key(strip_suffixes(clean_text(value)))


def norm_unit(value) -> str:
    return normalize_key(strip_suffixes(clean_text(value)))


def norm_post(value) -> str:
    text = clean_text(value)
    text = re.sub(r"[\[\(（【]\s*\d{6,}\s*[\]\)）】]", "", text)
    text = re.sub(r"(职位|岗位)?代码\s*[:：]?\s*\d{6,}", "", text)
    return normalize_key(text)


def norm_attr(value) -> str:
    return normalize_key(value)


def entity_key(dept, unit, post_name, post_attr="") -> str:
    return "|".join([norm_dept(dept), norm_unit(unit), norm_post(post_name), norm_attr(post_attr)])


def similarity(left: str, right: str) -> float:
    """0..1 相似度；一方为空返回 0。"""
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def extract_post_code(text) -> str:
    """从职位名称/备注里兜底抽职位代码。"""
    match = _CODE_IN_TEXT.search(clean_text(text))
    return match.group(1) if match else ""


def compact_province(text: str) -> str:
    text = clean_text(text)
    for suffix in ("省", "市", "自治区", "特别行政区"):
        text = text.replace(suffix, "")
    return text
