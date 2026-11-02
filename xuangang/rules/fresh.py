"""应届身份匹配。"""

from __future__ import annotations

import re
from typing import Optional

from ..ingest.values import clean_text
from ..models import Check, Profile

_YEAR_RE = re.compile(r"(20\d{2})\s*年?\s*(?:应届|毕业)")


def check_fresh(position, profile: Profile) -> Optional[Check]:
    text = "；".join(
        item
        for item in (clean_text(position.fresh_raw), clean_text(position.remark))
        if item
    )
    if "应届" not in text and "毕业生" not in text:
        return None
    if "不限" in text and "应届" not in text.replace("不限", ""):
        return Check("应届", True, "应届身份不限", text)
    if "不限应届" in text or "应届不限" in text:
        return Check("应届", True, "应届身份不限", text)

    status = clean_text(profile.fresh_status)
    if not status:
        return Check("应届", None, "个人条件里没有填写应届状态", text)

    year_match = _YEAR_RE.search(text)
    if year_match and "当年" not in status and "择业期" not in status:
        required_year = int(year_match.group(1))
        return Check(
            "应届",
            False,
            f"职位限 {required_year} 年应届毕业生，你的应届状态是「{status}」",
            text,
        )
    if year_match:
        required_year = int(year_match.group(1))
        if profile.graduation_year == required_year and status == "当年应届":
            return Check("应届", True, f"你是 {required_year} 年应届毕业生", text)
        return Check(
            "应届",
            False,
            f"职位限 {required_year} 年应届毕业生，你的毕业年份是 {profile.graduation_year}",
            text,
        )

    if "择业期" in text:
        if status == "择业期内" and not profile.has_employment_record:
            return Check("应届", True, "你处于择业期内且未落实工作单位", text)
        if status == "择业期内" and profile.has_employment_record:
            return Check("应届", False, "职位要求择业期内未落实工作单位，你已落实工作单位", text)
        return Check("应届", False, f"职位面向择业期内毕业生，你的应届状态是「{status}」", text)

    if "应届" in text:
        if status in {"当年应届", "择业期内"}:
            if status == "择业期内" and profile.has_employment_record:
                return Check(
                    "应届",
                    None,
                    "职位要求应届毕业生，择业期内已落实工作单位是否算应届需核对公告",
                    text,
                )
            return Check("应届", True, f"你的应届状态是「{status}」", text)
        return Check("应届", False, f"职位要求应届毕业生，你的应届状态是「{status}」", text)

    return None
