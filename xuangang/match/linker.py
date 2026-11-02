"""把分数线记录对应到当年岗位。

优先用职位代码；没有代码就比「部门 + 用人司局 + 职位名称」；
仍然对不上就按部门分组做模糊打分，低于阈值记为未匹配；
人工 ``manual_links.csv`` 优先级最高。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ingest.values import normalize_code
from ..models import Link, Position, ScoreRecord
from .identity import compact_province, norm_dept, norm_post, norm_unit, similarity
from .overrides import Override, lookup_override


@dataclass
class LinkOptions:
    accept: float = 0.92
    review: float = 0.78
    margin: float = 0.02


@dataclass
class LinkStats:
    total: int = 0
    code: int = 0
    exact: int = 0
    fuzzy: int = 0
    manual: int = 0
    review: int = 0
    unmatched: int = 0

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "code": self.code,
            "exact": self.exact,
            "fuzzy": self.fuzzy,
            "manual": self.manual,
            "review": self.review,
            "unmatched": self.unmatched,
        }


def _compatible(record: ScoreRecord, position: Position) -> bool:
    if record.exam and position.exam and record.exam != position.exam:
        return False
    record_province = compact_province(record.province)
    position_province = compact_province(position.province)
    if record_province and position_province and record_province != position_province:
        if "全国" not in (record.province, position.province):
            return False
    return True


def link_records(
    positions: list[Position],
    records: list[ScoreRecord],
    overrides: dict | None = None,
    options: LinkOptions | None = None,
) -> tuple[list[Link], LinkStats]:
    options = options or LinkOptions()
    by_code: dict[str, list[Position]] = {}
    by_dept: dict[str, list[Position]] = {}
    by_post: dict[str, list[Position]] = {}
    position_by_id = {position.id: position for position in positions}
    for position in positions:
        code = normalize_code(position.post_code)
        if code:
            by_code.setdefault(code, []).append(position)
        by_dept.setdefault(norm_dept(position.dept), []).append(position)
        by_post.setdefault(norm_post(position.post_name), []).append(position)

    groups: dict[tuple, list[ScoreRecord]] = {}
    for record in records:
        key = (
            record.year,
            record.exam,
            record.province,
            normalize_code(record.post_code),
            norm_dept(record.dept),
            norm_unit(record.unit),
            norm_post(record.post_name),
        )
        groups.setdefault(key, []).append(record)

    resolved: dict[tuple, tuple[str, str, float, bool, str]] = {}
    stats = LinkStats()
    dept_keys = [key for key in by_dept if key]

    for key, group in groups.items():
        sample = group[0]
        resolution = _resolve_one(
            sample,
            position_by_id,
            by_code,
            by_dept,
            by_post,
            dept_keys,
            overrides or {},
            options,
        )
        resolved[key] = resolution
        position_id, link_type, score, accepted, _note = resolution
        stats.total += len(group)
        if not position_id:
            stats.unmatched += len(group)
        elif link_type == "manual":
            stats.manual += len(group)
        elif link_type == "code":
            stats.code += len(group)
        elif link_type == "exact":
            stats.exact += len(group)
        elif link_type == "fuzzy":
            if accepted:
                stats.fuzzy += len(group)
            else:
                stats.review += len(group)

    links: list[Link] = []
    for record in records:
        key = (
            record.year,
            record.exam,
            record.province,
            normalize_code(record.post_code),
            norm_dept(record.dept),
            norm_unit(record.unit),
            norm_post(record.post_name),
        )
        position_id, link_type, score, accepted, note = resolved[key]
        links.append(
            Link(
                history_key=f"{record.year}|{record.source}|{record.sheet}|{record.row}",
                position_id=position_id,
                link_type=link_type,
                score=score,
                accepted=accepted,
                note=note,
            )
        )
    return links, stats


def _code_similarity(left: str, right: str) -> float:
    """职位代码年际变化时，公共前缀往往能区分同部门下的不同岗位。"""
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    prefix = 0
    for a, b in zip(left, right):
        if a != b:
            break
        prefix += 1
    prefix_ratio = prefix / min(len(left), len(right))
    base_ratio = similarity(left, right)
    return max(prefix_ratio, base_ratio)


def _dept_candidates(dept_key: str, by_dept: dict[str, list[Position]], dept_keys: list[str]) -> list[Position]:
    """省考里同一单位可能写成「雷州市」或「湛江市雷州市」，允许包含关系。"""
    if not dept_key:
        return []
    matched = [
        key
        for key in dept_keys
        if key and (dept_key in key or key in dept_key)
    ]
    if not matched:
        return []
    matched.sort(key=lambda key: abs(len(key) - len(dept_key)))
    candidates: list[Position] = []
    seen: set[str] = set()
    for key in matched[:20]:
        for position in by_dept.get(key, []):
            if position.id not in seen:
                seen.add(position.id)
                candidates.append(position)
    return candidates


def _resolve_one(
    record: ScoreRecord,
    position_by_id: dict[str, Position],
    by_code: dict[str, list[Position]],
    by_dept: dict[str, list[Position]],
    by_post: dict[str, list[Position]],
    dept_keys: list[str],
    overrides: dict,
    options: LinkOptions,
) -> tuple[str, str, float, bool, str]:
    manual: Override | None = lookup_override(
        overrides, record.source, record.year, record.dept, record.post_name
    )
    if manual:
        if manual.action == "ignore":
            return "", "manual", 1.0, False, "人工标记为忽略"
        if manual.position_id in position_by_id:
            return manual.position_id, "manual", 1.0, True, manual.note or "人工指定对应关系"
        return "", "manual", 1.0, False, f"人工指定的岗位不存在：{manual.position_id}"

    code = normalize_code(record.post_code)
    if code and code in by_code:
        candidates = [item for item in by_code[code] if _compatible(record, item)]
        if len(candidates) == 1:
            return candidates[0].id, "code", 1.0, True, "职位代码一致"
        if len(candidates) > 1:
            # 职位代码在源表里可能重复（尤其仿真表/多系统拆分表），
            # 再用部门、职位名、单位确认具体是哪一个岗位。
            record_dept = norm_dept(record.dept)
            record_post = norm_post(record.post_name)
            record_unit = norm_unit(record.unit)
            ranked = []
            for item in candidates:
                dept_score = 1.0 if record_dept and norm_dept(item.dept) == record_dept else (0.5 if not record_dept else 0.0)
                name_score = similarity(record_post, norm_post(item.post_name))
                unit_score = 1.0 if not record_unit else similarity(record_unit, norm_unit(item.unit))
                score = 0.45 * dept_score + 0.35 * name_score + 0.2 * unit_score
                ranked.append((score, dept_score, name_score, unit_score, item))
            ranked.sort(key=lambda item: item[0], reverse=True)
            best = ranked[0]
            second = ranked[1][0] if len(ranked) > 1 else 0.0
            if record_dept and best[1] >= 1.0 and best[2] >= 0.9 and (not record_unit or best[3] >= 0.8) and best[0] - second >= options.margin:
                return best[4].id, "code", 1.0, True, "职位代码一致（同代码多岗位，按部门/职位名区分）"
            if record_dept and best[1] >= 1.0 and best[2] >= options.review:
                return best[4].id, "code", 1.0, False, "职位代码对应多个岗位，已按部门/职位名挑出最接近的，需人工确认"
            # 部门完全对不上时，代码可能不可靠，交给后面的名称匹配

    dept_key = norm_dept(record.dept)
    post_key = norm_post(record.post_name)
    unit_key = norm_unit(record.unit)

    if not dept_key and post_key:
        candidates = [item for item in by_post.get(post_key, []) if _compatible(record, item)]
        if len(candidates) == 1:
            return candidates[0].id, "fuzzy", 0.8, False, "分数线缺部门，仅按职位名称唯一匹配"
        if len(candidates) > 1:
            return "", "fuzzy", 0.5, False, "分数线缺部门且职位名称不唯一，无法对应"
        return "", "fuzzy", 0.0, False, "分数线缺部门，且岗位表中没有同名职位"

    candidates = by_dept.get(dept_key, [])
    if not candidates and dept_key:
        candidates = _dept_candidates(dept_key, by_dept, dept_keys)
    if not candidates:
        return "", "none", 0.0, False, "岗位表中没有相同部门"

    scored: list[tuple[float, Position]] = []
    record_code = normalize_code(record.post_code)
    for position in candidates:
        if not _compatible(record, position):
            continue
        name_score = similarity(post_key, norm_post(position.post_name))
        if name_score < 0.5:
            continue
        position_code = normalize_code(position.post_code)
        code_score = _code_similarity(record_code, position_code) if record_code and position_code else 0.0
        if unit_key:
            unit_score = similarity(unit_key, norm_unit(position.unit))
        else:
            unit_score = 1.0
        if record_code and position_code:
            score = 0.4 * name_score + 0.25 * unit_score + 0.1 * 1.0 + 0.25 * code_score
        else:
            score = 0.5 * name_score + 0.35 * unit_score + 0.15 * 1.0
        scored.append((score, position))

    if not scored:
        return "", "none", 0.0, False, "同部门下没有名称相近的岗位"
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if len(scored) == 1:
        # 部门（允许包含关系）和职位名都对上，且只有一个候选时，即使职位代码
        # 跨年完全变化也可以建立对应；代码只用于多候选时区分。
        if similarity(post_key, norm_post(best.post_name)) >= 0.9 and (
            not unit_key or similarity(unit_key, norm_unit(best.unit)) >= 0.8
        ):
            return best.id, "fuzzy", round(max(best_score, 0.9), 3), True, "部门/职位名唯一匹配"
    ambiguity = best_score - second < options.margin

    if best_score >= options.accept and not ambiguity:
        if norm_unit(record.unit) and norm_unit(record.unit) == norm_unit(best.unit) and post_key == norm_post(best.post_name):
            return best.id, "exact", 0.95, True, "部门/用人司局/职位名称一致"
        return best.id, "fuzzy", round(best_score, 3), True, "模糊匹配（部门+职位名称相似）"
    if best_score >= options.review:
        reason = "存在多个相近岗位" if ambiguity else "相似度不足，需人工确认"
        return best.id, "fuzzy", round(best_score, 3), False, reason
    return "", "none", round(best_score, 3), False, "相似度低于阈值"
