"""学历 / 学位要求的解析与比较。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..ingest.values import clean_text
from ..models import Check, Profile

LEVELS = {
    "高中": 1,
    "中专": 1,
    "中职": 1,
    "技校": 1,
    "大专": 3,
    "专科": 3,
    "高职": 3,
    "本科": 4,
    "学士": 4,
    "硕士": 5,
    "硕士研究生": 5,
    "研究生": 5,
    "博士": 6,
    "博士研究生": 6,
    "博士后": 7,
}

_UPWARD = ("及以上", "以上")
_OR = ("或",)
_EXPLICIT = ("仅限", "只限", "限招", "限")
_FULLTIME = "全日制"


@dataclass
class LevelRequirement:
    unlimited: bool = False
    allowed: set[int] = field(default_factory=set)
    min_level: Optional[int] = None
    max_level: Optional[int] = None
    exact: bool = False
    explicit: bool = False
    bare: bool = False
    full_time: bool = False
    raw: str = ""


def _extract_levels(text: str) -> set[int]:
    remaining = text
    levels: set[int] = set()
    for name in sorted(LEVELS, key=len, reverse=True):
        if name in remaining:
            levels.add(LEVELS[name])
            remaining = remaining.replace(name, " ")
    return levels


def profile_education_level(value: str) -> Optional[int]:
    text = clean_text(value)
    if not text:
        return None
    levels = _extract_levels(text)
    if not levels:
        return None
    return max(levels)


def parse_education(value) -> Optional[LevelRequirement]:
    text = clean_text(value)
    if not text:
        return None
    if "不限" in text or "无要求" in text or text in {"无", "—", "-"}:
        return LevelRequirement(unlimited=True, raw=text)
    levels = _extract_levels(text)
    if not levels:
        return None
    req = LevelRequirement(raw=text, full_time=_FULLTIME in text)
    req.explicit = any(token in text for token in _EXPLICIT)
    if any(token in text for token in _UPWARD):
        req.min_level = min(levels)
        req.allowed = set(range(req.min_level, 8))
        req.exact = False
    elif any(token in text for token in _OR):
        req.allowed = set(levels)
        req.exact = False
    else:
        req.allowed = set(levels)
        req.exact = True
        req.bare = not req.explicit
    if req.allowed:
        req.min_level = req.min_level if req.min_level is not None else min(req.allowed)
        req.max_level = req.max_level if req.max_level is not None else max(req.allowed)
    return req


DEGREE_LEVELS = {"无": 0, "不限": 9, "学士": 4, "硕士": 5, "博士": 6}


def parse_degree(value) -> Optional[LevelRequirement]:
    text = clean_text(value)
    if not text:
        return None
    if "不限" in text or "无要求" in text or text in {"无", "—", "-"}:
        return LevelRequirement(unlimited=True, raw=text)
    levels: set[int] = set()
    if "博士" in text:
        levels.add(6)
    if "硕士" in text or "研究生" in text:
        levels.add(5)
    if "学士" in text or "本科" in text:
        levels.add(4)
    if not levels:
        return None
    req = LevelRequirement(raw=text)
    req.explicit = any(token in text for token in _EXPLICIT)
    if "以上" in text:
        req.min_level = min(levels)
        req.allowed = set(range(req.min_level, 7))
        req.exact = False
    else:
        req.allowed = set(levels)
        req.exact = True
        req.bare = not req.explicit
    req.min_level = req.min_level if req.min_level is not None else min(req.allowed)
    req.max_level = req.max_level if req.max_level is not None else max(req.allowed)
    return req


def profile_degree_level(value: str) -> Optional[int]:
    text = clean_text(value)
    if not text or text in {"无", "无学位", "—", "-"}:
        return 0
    if "博士" in text:
        return 6
    if "硕士" in text:
        return 5
    if "学士" in text:
        return 4
    return None


def check_education(position, profile: Profile) -> Optional[Check]:
    req = parse_education(position.education_raw)
    if req is None:
        return Check("学历", None, f"学历要求无法解析：{position.education_raw or '（空）'}", position.education_raw)
    if req.unlimited:
        return Check("学历", True, "学历不限", position.education_raw)
    bob = profile_education_level(profile.education_level)
    if bob is None:
        return Check("学历", None, f"你的学历「{profile.education_level}」无法识别", "")
    if bob in req.allowed:
        if req.full_time and not profile.full_time:
            return Check("学历", False, "该职位要求全日制学历，你的学历不是全日制", position.education_raw)
        return Check("学历", True, f"学历满足（{position.education_raw}）", position.education_raw)
    if req.full_time and not profile.full_time:
        return Check("学历", False, "该职位要求全日制学历，你的学历不是全日制", position.education_raw)
    if req.exact and not req.bare and bob > max(req.allowed):
        return Check("学历", False, f"职位要求{position.education_raw}，你的学历高于要求", position.education_raw)
    if req.bare and bob > max(req.allowed):
        return Check(
            "学历",
            None,
            f"职位学历列只写「{position.education_raw}」，是否接受更高学历需核对当年公告",
            position.education_raw,
        )
    return Check("学历", False, f"职位要求{position.education_raw}，你的学历不满足", position.education_raw)


def check_degree(position, profile: Profile) -> Optional[Check]:
    req = parse_degree(position.degree_raw)
    if req is None:
        return None
    if req.unlimited:
        return Check("学位", True, "学位不限", position.degree_raw)
    bob = profile_degree_level(profile.degree)
    if bob is None:
        return Check("学位", None, f"你的学位「{profile.degree}」无法识别", "")
    if bob in req.allowed:
        return Check("学位", True, f"学位满足（{position.degree_raw}）", position.degree_raw)
    if req.exact and not req.bare and bob > max(req.allowed):
        return Check("学位", False, f"职位要求{position.degree_raw}", position.degree_raw)
    if req.bare and bob > max(req.allowed):
        return Check("学位", None, f"职位学位列只写「{position.degree_raw}」，需核对", position.degree_raw)
    return Check("学位", False, f"职位要求{position.degree_raw}，你的学位不满足", position.degree_raw)
