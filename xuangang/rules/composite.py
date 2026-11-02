"""把各维度判定汇总成「符合 / 存疑 / 不符合」。"""

from __future__ import annotations

import re
from typing import Optional

from ..ingest.majors import MajorCatalog
from ..ingest.values import clean_text, split_tokens
from ..models import Check, MatchOutcome, Profile
from . import certs as certs_module
from .education import check_degree, check_education
from .ethnicity import check_ethnicity
from .extras import check_age, check_gender, check_hukou, check_school, check_special, collect_warnings
from .fresh import check_fresh
from .grassroots import check_grassroots
from .notes import extract_requirements, mentioned_dimensions
from .politics import check_politics

_LEVEL_LABEL = re.compile(r"^(研究生|硕士|博士|本科|大专|专科)\s*[:：]?\s*")

DIMENSION_LABELS = {
    "politics": "政治面貌",
    "ethnicity": "民族",
    "hukou": "户籍",
    "fresh": "应届",
    "grassroots": "基层经验",
    "projects": "基层经验",
    "cert": "执业资格",
    "gender": "性别",
    "age": "年龄",
    "school": "院校",
    "special": "特殊身份",
    "service": "最低服务年限",
    "warning": "备注提醒",
    "major_note": "专业",
}


def _profile_major_level(profile: Profile) -> str:
    level = clean_text(profile.major_level)
    if "研究生" in level or "硕士" in level or "博士" in level:
        return "研究生"
    if "大专" in level or "专科" in level:
        return "大专"
    return "本科"


def _major_text_for_profile(position, profile: Profile) -> str:
    """国考的专业列常写成「本科：…；研究生：…」，按考生学历选对应段落。"""
    level = _profile_major_level(profile)
    if position.major_by_level:
        direct = position.major_by_level.get(level)
        if direct:
            return direct
    text = clean_text(position.major_raw)
    if not text:
        return text
    clauses = [item for item in re.split(r"[；;]", text) if item.strip()]
    buckets: dict[str, list[str]] = {}
    for clause in clauses:
        match = _LEVEL_LABEL.match(clause.strip())
        if match:
            label = match.group(1)
            bucket = "研究生" if label in {"研究生", "硕士", "博士"} else ("大专" if label in {"大专", "专科"} else "本科")
            buckets.setdefault(bucket, []).append(re.sub(r"^\s*[:：]\s*", "", clause.strip()[match.end():]))
        else:
            buckets.setdefault("common", []).append(clause.strip())
    if buckets.get(level):
        return "；".join(buckets[level])
    if buckets.get("common"):
        return "；".join(buckets["common"])
    return text


def check_major(position, profile: Profile, catalog: MajorCatalog) -> Check:
    text = _major_text_for_profile(position, profile)
    tokens = split_tokens(text)
    ok, detail = catalog.match(tokens, profile.major, profile.major_code)
    return Check("专业", ok, detail, text)


def evaluate(
    position,
    profile: Profile,
    catalog: Optional[MajorCatalog] = None,
    cert_registry: Optional[certs_module.CertRegistry] = None,
) -> MatchOutcome:
    if catalog is None:
        catalog = MajorCatalog.load(profile.major_level)
    if cert_registry is None:
        cert_registry = certs_module.registry()
    if not position.notes and clean_text(position.text_blob()):
        position.notes = extract_requirements(position.text_blob())

    checks: list[Check] = [check_major(position, profile, catalog)]
    for func in (
        check_education,
        check_degree,
        check_politics,
        check_ethnicity,
        check_fresh,
        check_grassroots,
        check_hukou,
        check_gender,
        check_age,
        check_school,
        check_special,
    ):
        result = func(position, profile)
        if result is not None:
            checks.append(result)
    cert_check = cert_registry.check(position, profile)
    if cert_check is not None:
        checks.append(cert_check)

    covered = {check.dimension for check in checks}
    skip_unknown = {"学历", "学位", "专业", "最低服务年限", "备注提醒"}
    for dimension in mentioned_dimensions(position.text_blob()):
        label = DIMENSION_LABELS.get(dimension)
        if not label or label in covered or label in skip_unknown:
            continue
        checks.append(
            Check(label, None, f"备注提到「{label}」相关要求，但未能自动判定，建议电话确认", "")
        )
        covered.add(label)

    warnings = collect_warnings(position, profile)
    outcome = MatchOutcome(position_id=position.id, status="符合", checks=checks, warnings=warnings)
    if any(check.ok is False for check in checks):
        outcome.status = "不符合"
    elif any(check.ok is None for check in checks):
        outcome.status = "存疑"
    return outcome
