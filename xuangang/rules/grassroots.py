"""基层工作经历 / 服务基层项目匹配。"""

from __future__ import annotations

from typing import Optional

from ..ingest.values import clean_text, cn_to_int, normalize_key, parse_years
from ..models import Check, Profile

PROJECT_NAMES = ["大学生村官", "三支一扶", "西部计划", "特岗教师", "选调生"]


def _year_value(value: str) -> Optional[int]:
    text = clean_text(value)
    years = parse_years(text)
    if years is not None:
        return years
    if text.isdigit():
        return int(text)
    if text:
        return cn_to_int(text)
    return None


def check_grassroots(position, profile: Profile) -> Optional[Check]:
    years_req = _year_value(position.grassroots_raw)
    project_texts = [clean_text(position.grassroots_projects_raw)]
    for note in position.notes:
        if note.kind != "hard":
            continue
        if note.dimension == "grassroots":
            note_years = _year_value(note.value)
            if note_years is not None and (years_req is None or note_years > years_req):
                years_req = note_years
        elif note.dimension == "projects":
            project_texts.append(note.value)

    projects_text = "；".join(item for item in project_texts if item)
    projects_required: list[str] | None = None
    if projects_text and "不限" not in projects_text and "无限制" not in projects_text:
        names = [name for name in PROJECT_NAMES if name in projects_text]
        generic = "服务基层项目" in projects_text or "服务期满" in projects_text
        if names or generic:
            projects_required = names or ["服务基层项目"]

    if not years_req and not projects_required:
        return None

    problems: list[str] = []
    unknowns: list[str] = []

    if years_req:
        if profile.grassroots_years >= years_req:
            pass
        else:
            problems.append(f"要求 {years_req} 年以上基层工作经历，你只有 {profile.grassroots_years} 年")

    if projects_required:
        declared = profile.grassroots_project_names()
        completed = profile.completed_projects()
        if not declared:
            problems.append("职位要求服务基层项目人员，你的条件里没有服务基层项目经历")
        elif not completed:
            unknowns.append("你有服务基层项目经历，但没有标记「服务期满且考核合格」")
        else:
            normalized_completed = [normalize_key(item) for item in completed]
            if projects_required == ["服务基层项目"]:
                matched = bool(normalized_completed)
            else:
                matched = False
                for required in projects_required:
                    required_key = normalize_key(required)
                    for item in normalized_completed:
                        if required_key and required_key in item:
                            matched = True
                            break
                    if matched:
                        break
            if not matched:
                problems.append(
                    f"职位要求{('、'.join(projects_required))}，你的项目是{('、'.join(declared))}"
                )

    evidence = "；".join(item for item in [position.grassroots_raw, projects_text] if item)
    if problems:
        return Check("基层经验", False, "；".join(problems), evidence)
    if unknowns:
        return Check("基层经验", None, "；".join(unknowns), evidence)
    detail = []
    if years_req:
        detail.append(f"基层工作 {profile.grassroots_years} 年，满足 {years_req} 年要求")
    if projects_required:
        detail.append(f"服务基层项目满足（{projects_required}）")
    return Check("基层经验", True, "；".join(detail) or "满足", evidence)
