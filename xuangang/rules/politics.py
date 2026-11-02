"""政治面貌匹配。"""

from __future__ import annotations

from typing import Optional

from ..ingest.values import clean_text
from ..models import Check, Profile

PARTY = "中共党员"
PROBATIONARY = "中共预备党员"
LEAGUE = "共青团员"
MASSES = "群众"
DEMOCRATIC = "民主党派"
NON_PARTY = "无党派人士"

ALL_STATUS = {PARTY, PROBATIONARY, LEAGUE, MASSES, DEMOCRATIC, NON_PARTY}


def bob_status(value: str) -> set[str]:
    text = clean_text(value)
    if not text:
        return set()
    result: set[str] = set()
    if "预备" in text:
        result.add(PROBATIONARY)
    elif "党员" in text or "中共党员" in text:
        result.add(PARTY)
    if "共青团员" in text or "团员" in text:
        result.add(LEAGUE)
    if "民主党派" in text:
        result.add(DEMOCRATIC)
    if "无党派" in text:
        result.add(NON_PARTY)
    if "群众" in text:
        result.add(MASSES)
    if not result and text in ALL_STATUS:
        result.add(text)
    return result


def _allowed_from_text(text: str) -> set[str]:
    allowed: set[str] = set()
    if "中共党员" in text or "党员" in text or "预备党员" in text:
        allowed.update({PARTY, PROBATIONARY})
    if "共青团员" in text or "团员" in text:
        allowed.add(LEAGUE)
    if "民主党派" in text:
        allowed.add(DEMOCRATIC)
    if "无党派" in text:
        allowed.add(NON_PARTY)
    if "群众" in text:
        allowed.add(MASSES)
    return allowed


def check_politics(position, profile: Profile) -> Optional[Check]:
    column = clean_text(position.politics_raw)
    hard_notes = [
        note.value for note in position.notes if note.dimension == "politics" and note.kind == "hard"
    ]
    text = "；".join([column] + hard_notes)
    if not text.strip() or (("不限" in column or not column) and not hard_notes):
        if "不限" in column and not hard_notes:
            return Check("政治面貌", True, "政治面貌不限", column)
        return None
    if "不限" in column and not hard_notes:
        return Check("政治面貌", True, "政治面貌不限", column)
    allowed = _allowed_from_text(text)
    if not allowed:
        return Check("政治面貌", None, f"政治面貌要求无法解析：{text}", text)

    mine = bob_status(profile.politics)
    if not mine:
        return Check("政治面貌", None, f"你的政治面貌「{profile.politics}」无法识别", "")
    if mine & allowed:
        return Check("政治面貌", True, f"政治面貌满足（{text}）", text)
    return Check("政治面貌", False, f"职位要求{text}，你的政治面貌是「{profile.politics}」", text)
