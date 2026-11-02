"""民族要求匹配（主要出现在省考和民族自治地方）。"""

from __future__ import annotations

import re
from typing import Optional

from ..ingest.values import clean_text
from ..models import Check, Profile


def check_ethnicity(position, profile: Profile) -> Optional[Check]:
    texts = [clean_text(position.ethnicity_raw)]
    texts += [
        note.value for note in position.notes if note.dimension == "ethnicity" and note.kind == "hard"
    ]
    text = "；".join(item for item in texts if item)
    if not text:
        return None
    if "不限" in text:
        return Check("民族", True, "民族不限", text)

    mine = clean_text(profile.ethnicity)
    if not mine:
        return Check("民族", None, "个人条件里没有填写民族", text)

    if "少数民族" in text:
        if "汉族" not in mine:
            return Check("民族", True, f"你属于少数民族（{mine}），满足「限少数民族」", text)
        return Check("民族", False, f"职位限少数民族，你是「{mine}」", text)

    match = re.search(r"(?:限|仅限)?([\u4e00-\u9fa5]{2,10}族)", text)
    if match:
        required = match.group(1)
        if mine in required or required in mine:
            return Check("民族", True, f"民族匹配（{mine}）", text)
        return Check("民族", False, f"职位要求{required}，你是「{mine}」", text)

    return Check("民族", None, f"民族要求无法解析：{text}", text)
