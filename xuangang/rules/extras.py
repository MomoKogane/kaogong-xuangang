"""备注类硬条件：户籍、性别、年龄、院校层次、特殊身份。"""

from __future__ import annotations

from typing import Optional

from ..ingest.values import clean_text
from ..models import Check, Profile

PROVINCES = [
    "北京市", "天津市", "河北省", "山西省", "内蒙古自治区", "辽宁省", "吉林省", "黑龙江省",
    "上海市", "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省", "河南省",
    "湖北省", "湖南省", "广东省", "广西壮族自治区", "海南省", "重庆市", "四川省",
    "贵州省", "云南省", "西藏自治区", "陕西省", "甘肃省", "青海省", "宁夏回族自治区",
    "新疆维吾尔自治区", "香港特别行政区", "澳门特别行政区", "台湾省",
]

_SHORT = {name: name.replace("省", "").replace("市", "").replace("自治区", "").replace("特别行政区", "") for name in PROVINCES}


def _note_values(position, dimension: str, kind: str = "hard") -> list[str]:
    return [note.value for note in position.notes if note.dimension == dimension and note.kind == kind]


def _extract_province(text: str) -> str:
    for province in sorted(PROVINCES, key=len, reverse=True):
        short = _SHORT[province]
        if short and short in text:
            return province
    return ""


def _matches_region(profile: Profile, province: str) -> Optional[bool]:
    short = _SHORT.get(province, province)
    candidates = [clean_text(profile.hukou_province), clean_text(profile.hometown_province)]
    candidates = [item for item in candidates if item]
    if not candidates:
        return None
    return any(short in item or item in short for item in candidates)


def check_hukou(position, profile: Profile) -> Optional[Check]:
    texts = [clean_text(position.hukou_raw)]
    texts += _note_values(position, "hukou")
    text = "；".join(item for item in texts if item)
    if not text:
        return None
    if "不限" in text:
        return Check("户籍", True, "户籍不限", text)

    province = _extract_province(text)
    if province:
        matched = _matches_region(profile, province)
        if matched is True:
            return Check("户籍", True, f"户籍/生源满足（{province}）", text)
        if matched is None:
            return Check("户籍", None, f"职位限 {province} 户籍/生源，个人条件里没填户籍", text)
        return Check("户籍", False, f"职位限 {province} 户籍/生源，你的户籍/生源不符", text)

    if "本省" in text:
        position_province = _extract_province(clean_text(position.province))
        if not position_province:
            return Check("户籍", None, f"职位要求本省户籍，但无法确定省份：{text}", text)
        matched = _matches_region(profile, position_province)
        if matched is True:
            return Check("户籍", True, f"户籍/生源满足（{position_province}）", text)
        if matched is None:
            return Check("户籍", None, f"职位限本省户籍（{position_province}），个人条件里没填户籍", text)
        return Check("户籍", False, f"职位限本省户籍（{position_province}），你的户籍/生源不符", text)

    return Check("户籍", None, f"户籍要求无法自动判定：{text}", text)


def check_gender(position, profile: Profile) -> Optional[Check]:
    texts = [clean_text(position.gender_raw)] + _note_values(position, "gender")
    text = "；".join(item for item in texts if item)
    if not text or "不限" in text:
        return None if not text else Check("性别", True, "性别不限", text)
    required = ""
    if "男" in text:
        required = "男"
    if "女" in text:
        required = "女" if not required else required
    if not required:
        return Check("性别", None, f"性别要求无法解析：{text}", text)
    mine = clean_text(profile.gender)
    if not mine:
        return Check("性别", None, "个人条件里没有填写性别", text)
    if mine.startswith(required):
        return Check("性别", True, f"性别满足（{required}）", text)
    return Check("性别", False, f"职位限{required}性，你的性别是{mine}", text)


def check_age(position, profile: Profile) -> Optional[Check]:
    values = _note_values(position, "age")
    if not values:
        return None
    max_age = None
    for value in values:
        if value.isdigit():
            max_age = int(value)
            break
    if max_age is None:
        return Check("年龄", None, f"年龄要求无法解析：{'、'.join(values)}", "、".join(values))
    if not profile.birth_year:
        return Check("年龄", None, f"职位要求 {max_age} 周岁以下，个人条件里没填出生年份", "、".join(values))
    age = int(profile.target_year) - int(profile.birth_year)
    if age <= max_age:
        return Check("年龄", True, f"年龄 {age} 岁，满足 {max_age} 周岁以下", "、".join(values))
    return Check("年龄", False, f"年龄 {age} 岁，超过 {max_age} 周岁", "、".join(values))


def check_school(position, profile: Profile) -> Optional[Check]:
    values = _note_values(position, "school")
    if not values:
        return None
    text = "、".join(values)
    if "全日制" in text and not profile.full_time:
        return Check("院校", False, "职位要求全日制学历，你的学历不是全日制", text)
    tags = {clean_text(item) for item in profile.school_tags if clean_text(item)}
    for value in values:
        for tag in ("双一流", "985", "211"):
            if tag in value:
                if tag in tags:
                    continue
                if not tags:
                    return Check("院校", None, f"职位要求{tag}院校，个人条件里没填院校标签", text)
                return Check("院校", False, f"职位要求{tag}院校，你的院校标签是{('、'.join(sorted(tags)))}", text)
    return None


def check_special(position, profile: Profile) -> Optional[Check]:
    values = _note_values(position, "special")
    if not values:
        return None
    text = "、".join(values)
    if "退役" in text:
        if profile.veteran:
            return Check("特殊身份", True, "退役士兵身份满足", text)
        return Check("特殊身份", False, "职位面向退役士兵，个人条件里没有退役士兵身份", text)
    if "残疾" in text:
        if profile.disabled:
            return Check("特殊身份", True, "残疾人身份满足", text)
        return Check("特殊身份", False, "职位面向残疾人，个人条件里没有残疾人身份", text)
    return Check("特殊身份", None, f"特殊身份要求无法自动判定：{text}", text)


def collect_warnings(position, profile: Profile) -> list[str]:
    warnings: list[str] = []
    for note in position.notes:
        if note.kind != "soft":
            continue
        if note.dimension == "warning":
            warnings.append(note.evidence)
        elif note.dimension == "service":
            warnings.append(f"最低服务年限 {note.value} 年（{note.evidence}）")
        elif note.dimension == "gender":
            warnings.append(f"性别优先：{note.value}（非硬条件）")
        elif note.dimension == "politics":
            warnings.append("中共党员优先（非硬条件）")
        elif note.dimension == "major_note":
            warnings.append("专业要求详见备注/专业目录，请人工核对")
    if profile.birth_year and not any(note.dimension == "age" for note in position.notes):
        age = int(profile.target_year) - int(profile.birth_year)
        if age > 35:
            warnings.append(f"年龄约 {age} 岁，注意 35 周岁常规上限（应届/博士等另有规定）")
    return warnings
