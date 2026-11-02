"""历史分数线统计、预测、选岗偏好与「冲 / 稳 / 保」分档。

除了「能不能报」，选岗还包含主观偏好：
- 意向地区（籍贯 / 特定城市）；
- 岗位限制（限性别、限户籍、限项目等）对符合者形成的竞争壁垒。

这两项只影响排序，不改变硬条件判定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Optional

from .config import load_scoring_config
from .ingest.values import clean_text, normalize_key, parse_ratio, score_to_200
from .models import Evaluation, HistoryPoint, MatchOutcome, Profile, Position, ScoreRecord

DEFAULT_BARRIER_WEIGHTS = {
    "性别": 1.0,
    "民族": 1.0,
    "特殊身份": 1.0,
    "户籍": 0.8,
    "基层经验": 0.8,
    "执业资格": 0.6,
    "政治面貌": 0.5,
    "应届": 0.5,
    "专业": 0.4,
    "学历": 0.3,
    "学位": 0.2,
}

BARRIER_LABELS = {
    "性别": "性别限制",
    "民族": "民族限制",
    "特殊身份": "特殊身份门槛",
    "户籍": "户籍限制",
    "基层经验": "基层项目/年限",
    "执业资格": "证书门槛",
    "政治面貌": "政治面貌门槛",
    "应届": "应届门槛",
    "专业": "专业门槛",
    "学历": "学历门槛",
    "学位": "学位门槛",
}


@dataclass
class ScoringOptions:
    max_years: int = 3
    weights: list[float] = field(default_factory=lambda: [0.5, 0.3, 0.2])
    bao: float = 10.0
    wen: float = 4.0
    chong: float = 0.0
    w_fit: float = 45.0
    w_heat: float = 20.0
    w_capacity: float = 15.0
    w_preference: float = 10.0
    w_barrier: float = 10.0
    pref_neutral: float = 0.5
    barrier_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_BARRIER_WEIGHTS))
    headcount_full: float = 5.0
    interview_full: float = 15.0
    headcount_weight: float = 0.7
    heat_high: float = 0.75
    heat_medium: float = 0.5


def options_from_config() -> ScoringOptions:
    data = load_scoring_config()
    history = data.get("history") or {}
    tiers = data.get("tiers") or {}
    weights = data.get("weights") or {}
    capacity = data.get("capacity") or {}
    heat = data.get("heat_percentile") or {}
    preference = data.get("preference") or {}
    barrier = data.get("barrier") or {}
    return ScoringOptions(
        max_years=int(history.get("max_years", 3) or 3),
        weights=[float(item) for item in (history.get("weights") or [0.5, 0.3, 0.2])],
        bao=float(tiers.get("bao", 10.0)),
        wen=float(tiers.get("wen", 4.0)),
        chong=float(tiers.get("chong", 0.0)),
        w_fit=float(weights.get("fit", 45.0)),
        w_heat=float(weights.get("heat", 20.0)),
        w_capacity=float(weights.get("capacity", 15.0)),
        w_preference=float(weights.get("preference", 10.0)),
        w_barrier=float(weights.get("barrier", 10.0)),
        pref_neutral=float(preference.get("neutral", 0.5)),
        barrier_weights={
            key: float(value)
            for key, value in {**DEFAULT_BARRIER_WEIGHTS, **barrier}.items()
        },
        headcount_full=float(capacity.get("headcount_full", 5.0) or 5.0),
        interview_full=float(capacity.get("interview_full", 15.0) or 15.0),
        headcount_weight=float(capacity.get("headcount_weight", 0.7)),
        heat_high=float(heat.get("high", 0.75)),
        heat_medium=float(heat.get("medium", 0.5)),
    )


def build_year_distributions(records: list[ScoreRecord]) -> dict[tuple[str, str, int], list[float]]:
    """按年份收集进面分位，统一折算到 200 分制，避免 100/200 分制混排。"""
    distributions: dict[tuple[str, str, int], list[float]] = {}
    for record in records:
        if record.kind != "笔试最低进面分" or record.min_score is None or record.year <= 0:
            continue
        if not record.scale:
            continue
        value = score_to_200(record.min_score, record.scale)
        if value is None:
            continue
        key = (record.exam, record.province, record.year)
        distributions.setdefault(key, []).append(value)
    for values in distributions.values():
        values.sort()
    return distributions


def _percentile(values: list[float], target: float) -> float:
    if len(values) <= 1:
        return 0.5
    below = sum(1 for value in values if value < target)
    return max(0.0, min(1.0, below / (len(values) - 1)))


def _region_matches(region: str, place: str) -> bool:
    region = clean_text(region)
    place = clean_text(place)
    if not region or not place:
        return False
    if region in place:
        return True
    short_region = region.replace("省", "").replace("市", "").replace("自治区", "").replace("特别行政区", "")
    short_place = place.replace("省", "").replace("市", "").replace("自治区", "").replace("特别行政区", "")
    if short_region and short_region in short_place:
        return True
    return bool(short_place and short_place in short_region)


def preference_score(position: Position, profile: Profile) -> tuple[Optional[float], str]:
    """意向地区命中：1=命中，0=没命中，None=没有设置偏好。"""
    regions: list[str] = [clean_text(item) for item in (profile.preferred_regions or []) if clean_text(item)]
    if profile.prefer_hometown:
        for region in (profile.hukou_province, profile.hometown_province):
            if clean_text(region):
                regions.append(clean_text(region))
    deduped: list[str] = []
    seen: set[str] = set()
    for region in regions:
        key = normalize_key(region)
        if key and key not in seen:
            seen.add(key)
            deduped.append(region)
    if not deduped:
        return None, ""

    place = " ".join(
        item
        for item in (
            clean_text(position.work_place),
            clean_text(position.settle_place),
            clean_text(position.dept),
            clean_text(position.unit),
        )
        if item
    )
    for region in deduped:
        if _region_matches(region, place):
            return 1.0, region
    return 0.0, ""


def barrier_score(
    position: Position,
    outcome: Optional[MatchOutcome],
    options: ScoringOptions,
) -> tuple[float, list[str]]:
    """岗位限制对符合条件的考生形成的竞争壁垒，0..1。"""
    if outcome is None:
        return 0.0, []
    total = 0.0
    tags: list[str] = []
    for check in outcome.checks:
        if check.ok is not True:
            continue
        weight = options.barrier_weights.get(check.dimension)
        if not weight:
            continue
        text = f"{check.detail} {check.evidence}"
        if "不限" in text or "无限制" in text or "无要求" in text:
            continue
        total += weight
        label = BARRIER_LABELS.get(check.dimension, check.dimension)
        if label not in tags:
            tags.append(label)
    return round(min(1.0, total / 2.5), 3), tags


def evaluate_position(
    position: Position,
    linked_records: list[ScoreRecord],
    distributions: dict[tuple[str, str, int], list[float]],
    profile: Profile,
    options: Optional[ScoringOptions] = None,
    outcome: Optional[MatchOutcome] = None,
) -> Evaluation:
    options = options or options_from_config()
    evaluation = Evaluation(position_id=position.id)
    evaluation.preference, evaluation.preference_label = preference_score(position, profile)
    evaluation.barrier, evaluation.barrier_tags = barrier_score(position, outcome, options)
    if evaluation.preference == 1.0:
        evaluation.notes.append(f"命中意向地区：{evaluation.preference_label}")

    usable = [
        record
        for record in linked_records
        if record.kind == "笔试最低进面分"
        and record.min_score is not None
        and record.year > 0
        and (not profile.target_year or record.year < int(profile.target_year))
    ]
    if not usable:
        evaluation.confidence = "无"
        evaluation.index = _index_value(
            options, None, None, _capacity(position), evaluation.preference, evaluation.barrier
        )
        evaluation.notes.append("没有可用的历史进面分数")
        return evaluation

    by_year: dict[int, list[ScoreRecord]] = {}
    for record in usable:
        by_year.setdefault(record.year, []).append(record)

    points: list[HistoryPoint] = []
    for year in sorted(by_year, reverse=True)[: options.max_years]:
        group = by_year[year]
        mins = [record.min_score for record in group if record.min_score is not None]
        maxes = [record.max_score for record in group if record.max_score is not None]
        scale = max((record.scale or 0 for record in group), default=0) or 200
        points.append(
            HistoryPoint(
                year=year,
                min_score=min(mins) if mins else None,
                max_score=max(maxes) if maxes else None,
                scale=scale,
                exam=group[0].exam,
                province=group[0].province,
                source=group[0].source,
                headcount=group[0].headcount,
                applicants=group[0].applicants,
                ratio=group[0].ratio,
                link_type="",
                link_score=0.0,
                accepted=True,
            )
        )
    points.sort(key=lambda point: point.year, reverse=True)
    evaluation.history = points

    weights = options.weights or [0.5, 0.3, 0.2]
    used = 0.0
    weighted = 0.0
    for index, point in enumerate(points):
        weight = weights[index] if index < len(weights) else 0.0
        if point.min_score is None:
            continue
        value_200 = score_to_200(point.min_score, point.scale)
        weighted += weight * value_200
        used += weight
    if not used:
        evaluation.confidence = "无"
        evaluation.index = _index_value(
            options, None, None, _capacity(position), evaluation.preference, evaluation.barrier
        )
        evaluation.notes.append("历史分数无法折算")
        return evaluation

    predicted_200 = weighted / used
    base_scale = points[0].scale or 200
    predicted = round(predicted_200 / 200 * base_scale, 2)
    evaluation.predicted = predicted
    evaluation.predicted_200 = round(predicted_200, 2)
    evaluation.predicted_scale = base_scale

    percentiles: list[float] = []
    for point in points:
        if point.min_score is None:
            continue
        values = distributions.get((point.exam, point.province, point.year))
        target = score_to_200(point.min_score, point.scale)
        if values and target is not None:
            percentiles.append(_percentile(values, target))
    if percentiles:
        evaluation.heat = round(mean(percentiles), 3)
        if evaluation.heat >= options.heat_high:
            evaluation.heat_label = "高"
        elif evaluation.heat >= options.heat_medium:
            evaluation.heat_label = "中"
        else:
            evaluation.heat_label = "低"

    evaluation.capacity = _capacity(position, points)

    if profile.estimated_score is not None:
        profile_scale = profile.score_scale or base_scale
        predicted_profile = predicted_200 / 200 * profile_scale
        evaluation.margin = round(float(profile.estimated_score) - predicted_profile, 2)
        if evaluation.margin >= options.bao:
            evaluation.tier = "保"
        elif evaluation.margin >= options.wen:
            evaluation.tier = "稳"
        elif evaluation.margin >= options.chong:
            evaluation.tier = "冲"
        else:
            evaluation.tier = "风险"

    if len(points) >= 3:
        evaluation.confidence = "高"
    elif len(points) == 2:
        evaluation.confidence = "中"
    else:
        evaluation.confidence = "低"
    if any(point.min_score is None for point in points):
        evaluation.notes.append("部分年份缺少最低进面分")

    evaluation.index = _index_value(
        options, evaluation, evaluation.heat, evaluation.capacity, evaluation.preference, evaluation.barrier
    )
    return evaluation


def _capacity(position: Position, points: Optional[list[HistoryPoint]] = None) -> float:
    headcount = position.headcount or 0
    ratio = parse_ratio(position.interview_ratio) or 0.0
    if not ratio and points:
        candidate = points[0].ratio or 0.0
        # 民间表的「竞争比」可能远大于面试比例，只接受 1~10 的合理区间
        if 1.0 <= candidate <= 10.0:
            ratio = candidate
    if not ratio:
        ratio = 3.0
    interview_count = headcount * ratio
    headcount_score = min(1.0, headcount / 5.0) if headcount else 0.0
    interview_score = min(1.0, interview_count / 15.0) if interview_count else 0.0
    return round(0.7 * headcount_score + 0.3 * interview_score, 3)


def _fit_value(options: ScoringOptions, tier: str) -> float:
    return {"保": 1.0, "稳": 0.85, "冲": 0.6, "风险": 0.25}.get(tier, 0.45)


def _index_value(
    options: ScoringOptions,
    evaluation: Optional[Evaluation],
    heat: Optional[float],
    capacity: float,
    preference: Optional[float],
    barrier: float,
) -> float:
    if evaluation is None or evaluation.predicted is None:
        fit = 0.35
    else:
        fit = _fit_value(options, evaluation.tier)
    heat_component = 0.5 if heat is None else (1.0 - heat)
    preference_component = options.pref_neutral if preference is None else preference
    total = (
        options.w_fit * fit
        + options.w_heat * heat_component
        + options.w_capacity * capacity
        + options.w_preference * preference_component
        + options.w_barrier * barrier
    )
    return round(max(0.0, min(100.0, total)), 1)
