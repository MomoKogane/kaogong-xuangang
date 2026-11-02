"""报告里到处用到的派生文本。"""

from __future__ import annotations

from ..models import Evaluation, MatchOutcome, Profile, ReportRow


def status_reason(row: ReportRow, limit: int = 3) -> str:
    outcome = row.outcome
    if outcome.status == "不符合":
        items = [check.detail for check in outcome.checks if check.ok is False]
        return "；".join(items[:limit]) if items else "存在不满足的硬条件"
    if outcome.status == "存疑":
        items = [check.detail for check in outcome.checks if check.ok is None]
        return "；".join(items[:limit]) if items else "有需要人工确认的条件"
    items = [check.detail for check in outcome.checks if check.ok is True]
    return "；".join(items[:limit]) if items else "条件满足"


def failed_text(outcome: MatchOutcome) -> str:
    return "、".join(check.dimension for check in outcome.checks if check.ok is False) or ""


def unknown_text(outcome: MatchOutcome) -> str:
    return "、".join(check.dimension for check in outcome.checks if check.ok is None) or ""


def checks_text(outcome: MatchOutcome) -> str:
    parts = []
    for check in outcome.checks:
        mark = "✓" if check.ok is True else ("✗" if check.ok is False else "?")
        parts.append(f"[{mark}] {check.dimension}：{check.detail}")
    return "\n".join(parts)


def warnings_text(outcome: MatchOutcome) -> str:
    return "；".join(outcome.warnings)


def history_text(evaluation: Evaluation) -> str:
    parts = []
    for point in evaluation.history:
        if point.min_score is None:
            continue
        text = f"{point.year}:{point.min_score:g}"
        if point.max_score is not None and point.max_score != point.min_score:
            text += f"~{point.max_score:g}"
        parts.append(text)
    return " / ".join(parts)


def tier_label(evaluation: Evaluation) -> str:
    if evaluation.tier:
        return evaluation.tier
    return "—"


def profile_text(profile: Profile) -> str:
    parts = [
        f"{profile.name}",
        f"学历：{profile.education_level}",
        f"学位：{profile.degree}",
        f"专业：{profile.major or '—'}",
    ]
    if profile.major_code:
        parts.append(f"专业代码：{profile.major_code}")
    parts.append(f"政治面貌：{profile.politics}")
    parts.append(f"民族：{profile.ethnicity}")
    parts.append(f"应届状态：{profile.fresh_status}")
    parts.append(f"基层工作：{profile.grassroots_years} 年")
    if profile.preferred_regions:
        parts.append("意向地区：" + "、".join(profile.preferred_regions))
    if profile.prefer_hometown:
        parts.append("含户籍/生源所在地")
    if profile.certificates:
        parts.append("证书：" + "、".join(profile.certificates))
    if profile.estimated_score is not None:
        parts.append(f"预估分：{profile.estimated_score:g}（满分 {profile.score_scale}）")
    return " ｜ ".join(parts)


def row_payload(row: ReportRow) -> dict:
    position = row.position
    evaluation = row.evaluation
    outcome = row.outcome
    return {
        "id": position.id,
        "dept": position.dept,
        "unit": position.unit,
        "post": position.post_name,
        "code": position.post_code,
        "category": position.exam_category,
        "headcount": position.headcount,
        "education": position.education_raw,
        "degree": position.degree_raw,
        "major": position.major_raw,
        "politics": position.politics_raw,
        "fresh": position.fresh_raw,
        "grassroots": position.grassroots_raw,
        "cert": position.cert_raw,
        "hukou": position.hukou_raw,
        "gender": position.gender_raw,
        "workplace": position.work_place,
        "remark": position.remark,
        "source": position.source,
        "sheet": position.sheet,
        "row": position.row,
        "status": outcome.status,
        "failed": failed_text(outcome),
        "unknown": unknown_text(outcome),
        "warnings": warnings_text(outcome),
        "reason": status_reason(row, limit=4),
        "checks": [
            {"dim": check.dimension, "ok": check.ok, "detail": check.detail, "evidence": check.evidence}
            for check in outcome.checks
        ],
        "tier": evaluation.tier,
        "index": evaluation.index,
        "predicted": evaluation.predicted,
        "predicted_200": evaluation.predicted_200,
        "predicted_scale": evaluation.predicted_scale,
        "confidence": evaluation.confidence,
        "heat": evaluation.heat,
        "heat_label": evaluation.heat_label,
        "capacity": evaluation.capacity,
        "margin": evaluation.margin,
        "preference": evaluation.preference,
        "preference_label": evaluation.preference_label,
        "barrier": evaluation.barrier,
        "barrier_tags": list(evaluation.barrier_tags),
        "advantage_tags": (
            ([{"text": f"意向:{evaluation.preference_label}", "kind": "pref"}] if evaluation.preference == 1.0 else [])
            + [{"text": tag, "kind": "barrier"} for tag in evaluation.barrier_tags]
        ),
        "history": [
            {
                "year": point.year,
                "min": point.min_score,
                "max": point.max_score,
                "scale": point.scale,
                "source": point.source,
            }
            for point in evaluation.history
        ],
        "notes": list(evaluation.notes),
    }


def payload(result) -> dict:
    stats = result.stats
    rows = [row_payload(row) for row in result.rows]
    return {
        "stats": stats,
        "rows": rows,
        "profile": profile_text(result.profile) if result.profile else "",
        "profile_data": _profile_dict(result.profile) if result.profile else {},
        "generated": _now(),
    }


def _profile_dict(profile: Profile) -> dict:
    from dataclasses import asdict

    data = asdict(profile)
    data.pop("cert_objs", None)
    return data


def _now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
