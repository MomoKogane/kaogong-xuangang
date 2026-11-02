"""一次完整分析的编排：读取 → 对应 → 判定 → 评分 → 输出。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import project_root
from .ingest.history import HistorySpec, load_history
from .ingest.majors import MajorCatalog
from .ingest.positions import PositionSpec, load_positions
from .match.linker import LinkOptions, LinkStats, link_records
from .match.overrides import load_overrides
from .models import Evaluation, Issue, Link, MatchOutcome, Position, Profile, ReportRow, ScoreRecord
from .rules import certs as certs_module
from .rules.composite import evaluate
from .scoring import ScoringOptions, build_year_distributions, evaluate_position, options_from_config

STATUS_ORDER = {"符合": 0, "存疑": 1, "不符合": 2}


@dataclass
class RunConfig:
    positions: list[PositionSpec]
    history: list[HistorySpec]
    profile: Profile
    preset: str = "guokao"
    manual_links: Path | None = None
    major_catalog: Path | None = None
    top: int = 0
    out_dir: Path | None = None


@dataclass
class RunResult:
    positions: list[Position] = field(default_factory=list)
    records: list[ScoreRecord] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    outcomes: dict[str, MatchOutcome] = field(default_factory=dict)
    evaluations: dict[str, Evaluation] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    rows: list[ReportRow] = field(default_factory=list)
    link_stats: LinkStats = field(default_factory=LinkStats)
    profile: Profile | None = None


def run(config: RunConfig) -> RunResult:
    result = RunResult(profile=config.profile)
    issues = result.issues

    result.positions = load_positions(config.positions, issues)
    result.records = load_history(config.history, issues)

    manual_path = config.manual_links
    if manual_path is None:
        manual_path = project_root() / "data" / "manual_links.csv"
    overrides = load_overrides(Path(manual_path)) if Path(manual_path).exists() else {}

    result.links, result.link_stats = link_records(
        result.positions,
        result.records,
        overrides,
        LinkOptions(),
    )

    record_by_history_key = {
        f"{record.year}|{record.source}|{record.sheet}|{record.row}": record for record in result.records
    }
    accepted: dict[str, list[ScoreRecord]] = {}
    review_count: dict[str, int] = {}
    for link in result.links:
        record = record_by_history_key.get(link.history_key)
        if link.accepted and link.position_id and record is not None:
            accepted.setdefault(link.position_id, []).append(record)
        elif not link.accepted and link.position_id:
            review_count[link.position_id] = review_count.get(link.position_id, 0) + 1

    distributions = build_year_distributions(result.records)
    catalog = MajorCatalog.load(config.profile.major_level, config.major_catalog)
    cert_registry = certs_module.registry()
    scoring_options = options_from_config()

    for position in result.positions:
        outcome = evaluate(position, config.profile, catalog, cert_registry)
        evaluation = evaluate_position(
            position,
            accepted.get(position.id, []),
            distributions,
            config.profile,
            scoring_options,
            outcome=outcome,
        )
        if position.id in review_count:
            evaluation.notes.append(
                f"有 {review_count[position.id]} 条分数线匹配存疑，未计入历史分（见 links_review.csv）"
            )
        result.outcomes[position.id] = outcome
        result.evaluations[position.id] = evaluation
        result.rows.append(
            ReportRow(
                position=position,
                outcome=outcome,
                evaluation=evaluation,
                score=evaluation.index,
            )
        )

    result.rows.sort(key=lambda row: (STATUS_ORDER.get(row.outcome.status, 9), -row.score))
    result.stats = _build_stats(result)
    return result


def _build_stats(result: RunResult) -> dict:
    status_counts = {"符合": 0, "存疑": 0, "不符合": 0}
    tiers = {"保": 0, "稳": 0, "冲": 0, "风险": 0}
    with_history = 0
    for row in result.rows:
        status_counts[row.outcome.status] = status_counts.get(row.outcome.status, 0) + 1
        if row.evaluation.history:
            with_history += 1
        if row.outcome.status == "符合" and row.evaluation.tier:
            tiers[row.evaluation.tier] = tiers.get(row.evaluation.tier, 0) + 1
    issue_counts = {"error": 0, "warn": 0, "info": 0}
    for issue in result.issues:
        issue_counts[issue.level] = issue_counts.get(issue.level, 0) + 1
    return {
        "positions": len(result.positions),
        "records": len(result.records),
        "links": result.link_stats.to_dict(),
        "status": status_counts,
        "tiers": tiers,
        "with_history": with_history,
        "without_history": len(result.positions) - with_history,
        "issues": issue_counts,
    }


def summarize_text(result: RunResult, top: int = 10) -> str:
    stats = result.stats
    lines = [
        f"岗位数：{stats['positions']}    分数线记录：{stats['records']}",
        "匹配情况："
        + "，".join(f"{key} {value}" for key, value in stats["links"].items()),
        f"判定结果：符合 {stats['status']['符合']}，存疑 {stats['status']['存疑']}，不符合 {stats['status']['不符合']}",
        f"历史分覆盖：{stats['with_history']} 个岗位有历史分，{stats['without_history']} 个没有",
    ]
    if any(stats["tiers"].values()):
        lines.append(
            "分档：" + "，".join(f"{key} {value}" for key, value in stats["tiers"].items() if value)
        )
    lines.append(
        "数据质量：error {}，warn {}，info {}".format(
            stats["issues"]["error"], stats["issues"]["warn"], stats["issues"]["info"]
        )
    )
    recommended = [row for row in result.rows if row.outcome.status == "符合"]
    if top and recommended:
        lines.append("")
        lines.append(f"符合条件的前 {min(top, len(recommended))} 个岗位：")
        lines.append("序号  分档  指数  预测分  历史年数  岗位")
        for index, row in enumerate(recommended[:top], start=1):
            position = row.position
            evaluation = row.evaluation
            predicted = "—" if evaluation.predicted is None else f"{evaluation.predicted:g}/{evaluation.predicted_scale}"
            tier = evaluation.tier or "—"
            name = f"{position.dept}/{position.post_name}".strip("/")
            lines.append(
                f"{index:>3}  {tier:<4}  {evaluation.index:>5}  {predicted:>6}  {len(evaluation.history):>6}  {name}"
            )
    return "\n".join(lines)
