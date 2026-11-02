"""把中间结果写成 CSV，方便用 Excel 手工核对。"""

from __future__ import annotations

import csv
from pathlib import Path

from ..models import ScoreRecord

POSITION_FIELDS = [
    "id", "year", "exam", "province", "dept_code", "dept", "unit", "post_name", "post_code",
    "org_type", "post_attr", "exam_category", "headcount", "major", "education", "degree",
    "politics", "grassroots", "grassroots_projects", "fresh", "cert", "hukou", "ethnicity",
    "gender", "service_years", "interview_ratio", "work_place", "settle_place", "remark",
    "source", "sheet", "row", "entity_key",
]

HISTORY_FIELDS = [
    "year", "exam", "province", "dept", "unit", "post_name", "post_code", "min_score",
    "max_score", "scale", "kind", "headcount", "interview_count", "applicants", "ratio",
    "source", "sheet", "row",
]

ISSUE_FIELDS = ["level", "file", "sheet", "row", "message", "action", "field"]


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_csv_outputs(result, out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    normalized = out_dir / "normalized"
    written: list[Path] = []

    position_rows = []
    for position in result.positions:
        position_rows.append(
            {
                "id": position.id,
                "year": position.year,
                "exam": position.exam,
                "province": position.province,
                "dept_code": position.dept_code,
                "dept": position.dept,
                "unit": position.unit,
                "post_name": position.post_name,
                "post_code": position.post_code,
                "org_type": position.org_type,
                "post_attr": position.post_attr,
                "exam_category": position.exam_category,
                "headcount": position.headcount,
                "major": position.major_raw,
                "education": position.education_raw,
                "degree": position.degree_raw,
                "politics": position.politics_raw,
                "grassroots": position.grassroots_raw,
                "grassroots_projects": position.grassroots_projects_raw,
                "fresh": position.fresh_raw,
                "cert": position.cert_raw,
                "hukou": position.hukou_raw,
                "ethnicity": position.ethnicity_raw,
                "gender": position.gender_raw,
                "service_years": "",
                "interview_ratio": position.interview_ratio,
                "work_place": position.work_place,
                "settle_place": position.settle_place,
                "remark": position.remark,
                "source": position.source,
                "sheet": position.sheet,
                "row": position.row,
                "entity_key": position.entity_key,
            }
        )
    path = normalized / "positions.csv"
    _write_csv(path, POSITION_FIELDS, position_rows)
    written.append(path)

    record_rows = [_record_row(record) for record in result.records]
    path = normalized / "history.csv"
    _write_csv(path, HISTORY_FIELDS, record_rows)
    written.append(path)

    link_rows = [
        {
            "history_key": link.history_key,
            "position_id": link.position_id,
            "link_type": link.link_type,
            "score": link.score,
            "accepted": link.accepted,
            "note": link.note,
        }
        for link in result.links
    ]
    path = out_dir / "links.csv"
    _write_csv(path, ["history_key", "position_id", "link_type", "score", "accepted", "note"], link_rows)
    written.append(path)

    path = out_dir / "links_review.csv"
    _write_csv(
        path,
        ["history_key", "position_id", "link_type", "score", "accepted", "note"],
        [row for row in link_rows if not row["accepted"] and row["position_id"]],
    )
    written.append(path)

    path = out_dir / "links_unmatched.csv"
    _write_csv(
        path,
        ["history_key", "position_id", "link_type", "score", "accepted", "note"],
        [row for row in link_rows if not row["position_id"]],
    )
    written.append(path)

    outcome_rows = []
    for position in result.positions:
        outcome = result.outcomes.get(position.id)
        if outcome is None:
            continue
        outcome_rows.append(
            {
                "position_id": position.id,
                "status": outcome.status,
                "failed": "、".join(check.dimension for check in outcome.checks if check.ok is False),
                "unknown": "、".join(check.dimension for check in outcome.checks if check.ok is None),
                "warnings": "；".join(outcome.warnings),
                "checks": "；".join(
                    f"{check.dimension}:{'Y' if check.ok is True else ('N' if check.ok is False else '?')}:{check.detail}"
                    for check in outcome.checks
                ),
            }
        )
    path = out_dir / "outcomes.csv"
    _write_csv(path, ["position_id", "status", "failed", "unknown", "warnings", "checks"], outcome_rows)
    written.append(path)

    evaluation_rows = []
    for position in result.positions:
        evaluation = result.evaluations.get(position.id)
        if evaluation is None:
            continue
        evaluation_rows.append(
            {
                "position_id": position.id,
                "predicted": evaluation.predicted,
                "predicted_200": evaluation.predicted_200,
                "confidence": evaluation.confidence,
                "heat": evaluation.heat,
                "heat_label": evaluation.heat_label,
                "capacity": evaluation.capacity,
                "margin": evaluation.margin,
                "tier": evaluation.tier,
                "index": evaluation.index,
                "notes": "；".join(evaluation.notes),
                "history": " / ".join(
                    f"{point.year}:{point.min_score}" for point in evaluation.history if point.min_score is not None
                ),
            }
        )
    path = out_dir / "evaluations.csv"
    _write_csv(
        path,
        ["position_id", "predicted", "predicted_200", "confidence", "heat", "heat_label", "capacity", "margin", "tier", "index", "notes", "history"],
        evaluation_rows,
    )
    written.append(path)

    path = out_dir / "issues.csv"
    _write_csv(path, ISSUE_FIELDS, [issue.to_dict() for issue in result.issues])
    written.append(path)

    return written


def _record_row(record: ScoreRecord) -> dict:
    return {
        "year": record.year,
        "exam": record.exam,
        "province": record.province,
        "dept": record.dept,
        "unit": record.unit,
        "post_name": record.post_name,
        "post_code": record.post_code,
        "min_score": record.min_score,
        "max_score": record.max_score,
        "scale": record.scale,
        "kind": record.kind,
        "headcount": record.headcount,
        "interview_count": record.interview_count,
        "applicants": record.applicants,
        "ratio": record.ratio,
        "source": record.source,
        "sheet": record.sheet,
        "row": record.row,
    }
