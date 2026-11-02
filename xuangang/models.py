"""项目内的数据模型。

全部用 dataclass，便于直接 ``dataclasses.asdict`` 转 JSON / CSV。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class Issue:
    """数据质量问题。"""

    level: str  # info | warn | error
    file: str
    sheet: str
    row: int
    message: str
    action: str = ""
    field: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NoteRule:
    """从「备注 / 职位简介」里抽出来的附加要求。"""

    rule_id: str
    dimension: str
    kind: str  # hard | soft
    value: str
    evidence: str


@dataclass
class Position:
    """标准化后的岗位。"""

    id: str
    year: int
    exam: str
    province: str
    source: str
    sheet: str
    row: int

    dept_code: str = ""
    dept: str = ""
    unit: str = ""
    org_type: str = ""
    post_name: str = ""
    post_code: str = ""
    post_attr: str = ""
    post_distribution: str = ""
    post_desc: str = ""
    headcount: int = 0
    headcount_raw: str = ""

    major_raw: str = ""
    major_by_level: dict[str, str] = field(default_factory=dict)
    major_tokens: list[str] = field(default_factory=list)
    education_raw: str = ""
    degree_raw: str = ""
    politics_raw: str = ""
    grassroots_raw: str = ""
    grassroots_projects_raw: str = ""
    fresh_raw: str = ""
    cert_raw: str = ""
    hukou_raw: str = ""
    ethnicity_raw: str = ""
    gender_raw: str = ""

    exam_category: str = ""
    interview_ratio: str = ""
    work_place: str = ""
    settle_place: str = ""
    remark: str = ""

    entity_key: str = ""
    notes: list[NoteRule] = field(default_factory=list)

    def text_blob(self) -> str:
        """所有可能含附加条件的文本，拼接后用于规则扫描。"""
        parts = [
            self.remark,
            self.post_desc,
            self.post_attr,
            self.exam_category,
            self.org_type,
            self.major_raw,
        ]
        return "；".join(part for part in parts if part)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["major_tokens"] = "、".join(self.major_tokens)
        data["notes"] = [asdict(note) for note in self.notes]
        return data


@dataclass
class ScoreRecord:
    """往年进面分数表中的一行。"""

    year: int
    exam: str
    province: str
    source: str
    sheet: str
    row: int

    dept: str = ""
    unit: str = ""
    post_name: str = ""
    post_code: str = ""
    min_score_raw: str = ""
    min_score: Optional[float] = None
    max_score: Optional[float] = None
    headcount: Optional[int] = None
    interview_count: Optional[int] = None
    applicants: Optional[int] = None
    ratio: Optional[float] = None
    scale: int = 200
    kind: str = "笔试最低进面分"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Certificate:
    """个人持有的证书（已归一）。"""

    cert_id: str
    level: str = ""
    raw: str = ""


@dataclass
class Profile:
    """考生个人条件。"""

    name: str = "bob"

    # 学历 / 学位
    education_level: str = "本科"
    degree: str = "学士"
    full_time: bool = True
    major: str = ""
    major_code: str = ""
    major_level: str = "本科"
    school: str = ""
    school_tags: list[str] = field(default_factory=list)

    # 身份条件
    politics: str = "群众"
    ethnicity: str = "汉族"
    gender: str = ""
    birth_year: Optional[int] = None
    fresh_status: str = "非应届"  # 当年应届 | 择业期内 | 非应届
    graduation_year: Optional[int] = None
    has_employment_record: bool = False
    veteran: bool = False
    disabled: bool = False

    # 工作经历
    grassroots_years: int = 0
    grassroots_projects: list[dict[str, Any]] = field(default_factory=list)
    certificates: list[str] = field(default_factory=list)
    cert_objs: list[Certificate] = field(default_factory=list)

    # 地域
    hukou_province: str = ""
    hometown_province: str = ""

    # 选岗偏好（影响排序，不影响硬条件）
    preferred_regions: list[str] = field(default_factory=list)
    prefer_hometown: bool = False

    # 考试偏好 / 参考
    exam: str = "guokao"
    province: str = ""
    target_year: int = 2027
    estimated_score: Optional[float] = None
    score_scale: int = 200

    def grassroots_project_names(self) -> list[str]:
        names: list[str] = []
        for item in self.grassroots_projects:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("project") or ""
                if name:
                    names.append(str(name))
        return names

    def completed_projects(self) -> list[str]:
        completed: list[str] = []
        for item in self.grassroots_projects:
            if isinstance(item, str):
                completed.append(item)
            elif isinstance(item, dict):
                if item.get("completed", True) in (True, "true", "是", 1):
                    name = item.get("name") or item.get("project") or ""
                    if name:
                        completed.append(str(name))
        return completed


@dataclass
class Check:
    """单个维度的判定结果。ok 为 None 表示无法判定（存疑）。"""

    dimension: str
    ok: Optional[bool]
    detail: str
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MatchOutcome:
    position_id: str
    status: str  # 符合 | 存疑 | 不符合
    checks: list[Check] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def failed(self) -> list[Check]:
        return [check for check in self.checks if check.ok is False]

    @property
    def unknown(self) -> list[Check]:
        return [check for check in self.checks if check.ok is None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "position_id": self.position_id,
            "status": self.status,
            "failed": [check.dimension for check in self.failed],
            "unknown": [check.dimension for check in self.unknown],
            "warnings": list(self.warnings),
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass
class Link:
    """一条「分数线记录 -> 当年岗位」的对应关系。"""

    history_key: str
    position_id: str
    link_type: str  # code | exact | fuzzy | manual
    score: float
    accepted: bool
    note: str = ""


@dataclass
class HistoryPoint:
    year: int
    min_score: Optional[float]
    max_score: Optional[float]
    scale: int
    exam: str
    province: str
    source: str
    headcount: Optional[int] = None
    applicants: Optional[int] = None
    ratio: Optional[float] = None
    link_type: str = ""
    link_score: float = 0.0
    accepted: bool = True


@dataclass
class Evaluation:
    position_id: str
    history: list[HistoryPoint] = field(default_factory=list)
    predicted: Optional[float] = None
    predicted_200: Optional[float] = None
    predicted_scale: int = 200
    confidence: str = "无"  # 高 | 中 | 低 | 无
    heat: Optional[float] = None  # 0..1，越高越热
    heat_label: str = ""
    capacity: float = 0.0
    margin: Optional[float] = None
    tier: str = ""  # 保 | 稳 | 冲 | 风险
    index: float = 0.0
    preference: Optional[float] = None  # 0/1，意向地区是否命中；None=没填偏好
    preference_label: str = ""
    barrier: float = 0.0  # 0..1，岗位限制对你形成的竞争壁垒
    barrier_tags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["history"] = [asdict(point) for point in self.history]
        return data


@dataclass
class ReportRow:
    """报告里的一行：岗位 + 判定 + 评分。"""

    position: Position
    outcome: MatchOutcome
    evaluation: Evaluation
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position.to_dict(),
            "outcome": self.outcome.to_dict(),
            "evaluation": self.evaluation.to_dict(),
            "score": self.score,
        }
