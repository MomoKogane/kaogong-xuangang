"""从「备注 / 职位简介 / 职位属性」里抽取附加要求。

官方岗位表把大量关键条件塞在备注里：限男性、限本省户籍、须有法律职业资格 A 证、
服务期满考核合格、最低服务年限 5 年……这里用一组保守的正则规则抽取，
抽不出来的类别会在匹配阶段标成「存疑」，提示人工核对。

用户可以在 ``config/notes_patterns.toml`` 里追加规则：

    [[rule]]
    id = "my_rule"
    dimension = "cert"
    kind = "hard"
    pattern = "具有(X)证书"
    group = 1
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..config import load_toml, project_root
from ..models import NoteRule


@dataclass
class Rule:
    rule_id: str
    dimension: str
    kind: str  # hard | soft
    pattern: re.Pattern
    group: int = 0
    value_template: str | None = None
    message: str = ""
    extras: dict = field(default_factory=dict)


def _rule(
    rule_id: str,
    dimension: str,
    kind: str,
    pattern: str,
    group: int = 0,
    value_template: str | None = None,
    message: str = "",
) -> Rule:
    return Rule(
        rule_id=rule_id,
        dimension=dimension,
        kind=kind,
        pattern=re.compile(pattern),
        group=group,
        value_template=value_template,
        message=message,
    )


BUILTIN_RULES: list[Rule] = [
    # 性别
    _rule(
        "gender_limit", "gender", "hard",
        r"(?:限|仅限|须为|要求为|须是|须)(男性|女性)",
        group=1,
        message="职位限制性别",
    ),
    _rule(
        "gender_bare", "gender", "hard",
        r"(?:^|[；;，,。])\s*(男性|女性)\s*(?:$|[；;，,。])",
        group=1,
        message="职位限制性别",
    ),
    _rule("gender_priority", "gender", "soft", r"(男性|女性)优先", group=1, message="性别优先（非硬条件）"),
    # 政治面貌
    _rule(
        "politics_or_league", "politics", "hard",
        r"中共党员[^，。；]{0,4}或[^，。；]{0,4}共青团员",
        message="政治面貌：中共党员或共青团员",
    ),
    _rule(
        "politics_party", "politics", "hard",
        r"(中共党员|中共预备党员|共产党员)(?!优先)",
        group=1,
        message="政治面貌要求党员",
    ),
    _rule("politics_priority", "politics", "soft", r"(中共党员|党员)[^，。；]{0,4}优先", message="党员优先（非硬条件）"),
    # 民族
    _rule("ethnicity_minority", "ethnicity", "hard", r"(?:限|仅限)(少数民族)", group=1, message="限少数民族"),
    _rule("ethnicity_group", "ethnicity", "hard", r"(?:限|仅限)([\u4e00-\u9fa5]{2,8}族)", group=1, message="限特定民族"),
    # 户籍 / 生源
    _rule(
        "hukou_limit", "hukou", "hard",
        r"(?:限|仅限|要求|须为|具有)(本省|本市|本县|本地|当地)?[^，。；]{0,12}?(?:户籍|生源)",
        message="户籍/生源限制",
    ),
    _rule("hukou_short", "hukou", "hard", r"(?:限|仅限)(本省|本市|本县|本地|当地)户籍", group=1, message="户籍限制"),
    # 基层工作
    _rule(
        "grassroots_years", "grassroots", "hard",
        r"(?:具有|须具有|需具有|要求|应有)?\s*([一二两三四五六七八九十\d]+)\s*年以上基层工作(?:经历|年限)",
        group=1,
        message="基层工作年限要求",
    ),
    _rule(
        "grassroots_project", "projects", "hard",
        r"(服务基层项目人员|服务基层项目|大学生村官|三支一扶|西部计划|特岗教师|选调生)",
        message="服务基层项目要求",
    ),
    _rule("grassroots_completed", "projects", "hard", r"服务期满(?:且)?考核合格", message="须服务期满且考核合格"),
    _rule("veteran", "special", "hard", r"(退役大学生士兵|退役军人|退役士兵)", message="退役士兵专项"),
    _rule("disabled", "special", "hard", r"残疾人|定向招录残疾人", message="残疾人专项"),
    # 院校
    _rule("school_tags", "school", "hard", r"(双一流|985|211)", group=1, message="院校层次要求"),
    _rule("school_fulltime", "school", "hard", r"全日制(?:普通)?(?:高校|院校|本科|学历)", message="要求全日制"),
    # 年龄
    _rule("age_limit", "age", "hard", r"(\d{2})周岁(?:及)?以下", group=1, message="年龄上限"),
    # 服务期（软提醒）
    _rule(
        "service_years", "service", "soft",
        r"(?:最低)?服务(?:年限|期)\s*(?:为|不少于)?\s*([一二两三四五六七八九十\d]+)\s*年",
        group=1,
        message="最低服务年限",
    ),
    # 工作强度 / 其他提醒
    _rule("work_hardship", "warning", "soft", r"(经常出差|出差|值夜班|夜班|一线执法|基层一线|野外作业|倒班|驻外|加班)", group=1),
    _rule("physical", "warning", "soft", r"(体能测评|体能测试|体检标准|心理测试)", group=1),
    _rule("review", "warning", "soft", r"(政治考核|考察|政审)", group=1),
    # 专业 / 学历的补充说明
    _rule("major_detail", "major_note", "soft", r"专业(?:要求)?详见(?:备注|专业目录|附件)", group=0),
]


CATEGORY_KEYWORDS: dict[str, str] = {
    "politics": r"党员|政治面貌",
    "ethnicity": r"少数民族|[\u4e00-\u9fa5]{2}族",
    "hukou": r"户籍|生源",
    "fresh": r"应届",
    "grassroots": r"基层工作",
    "projects": r"服务基层项目|三支一扶|大学生村官|西部计划|特岗",
    "cert": r"资格证|执业资格|职业资格|证书",
    "gender": r"男性|女性",
    "age": r"周岁|年龄",
    "school": r"双一流|985|211|院校",
    "service": r"服务年限|服务期",
    "special": r"退役|残疾人|定向",
    "warning": r"出差|夜班|体能|体检",
}


def load_extra_rules() -> list[Rule]:
    """读取 config/notes_patterns.toml 追加规则。"""
    path = project_root() / "config" / "notes_patterns.toml"
    data = load_toml(path)
    rules: list[Rule] = []
    for index, item in enumerate(data.get("rule") or []):
        pattern = item.get("pattern")
        if not pattern:
            continue
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"notes_patterns.toml 第 {index + 1} 条规则正则错误：{exc}") from exc
        rules.append(
            Rule(
                rule_id=str(item.get("id") or f"extra_{index + 1}"),
                dimension=str(item.get("dimension") or "warning"),
                kind=str(item.get("kind") or "soft"),
                pattern=compiled,
                group=int(item.get("group") or 0),
                value_template=item.get("value"),
                message=str(item.get("message") or ""),
            )
        )
    return rules


def all_rules() -> list[Rule]:
    return list(BUILTIN_RULES) + load_extra_rules()


def _evidence(text: str, start: int, end: int, span: int = 24) -> str:
    left = max(0, start - span)
    right = min(len(text), end + span)
    snippet = text[left:right].strip()
    if left > 0:
        snippet = "…" + snippet
    if right < len(text):
        snippet = snippet + "…"
    return snippet


def extract_requirements(text: str, rules: list[Rule] | None = None) -> list[NoteRule]:
    """抽取备注中的附加要求；返回按规则去重后的列表。"""
    text = (text or "").strip()
    if not text:
        return []
    rules = rules if rules is not None else all_rules()
    found: list[NoteRule] = []
    seen: set[tuple[str, str]] = set()
    for rule in rules:
        for match in rule.pattern.finditer(text):
            try:
                value = match.group(rule.group) if rule.group else match.group(0)
            except IndexError:
                value = match.group(0)
            value = (value or "").strip()
            if not value:
                value = match.group(0)
            key = (rule.rule_id, value)
            if key in seen:
                continue
            seen.add(key)
            found.append(
                NoteRule(
                    rule_id=rule.rule_id,
                    dimension=rule.dimension,
                    kind=rule.kind,
                    value=value,
                    evidence=_evidence(text, match.start(), match.end()),
                )
            )
    return found


def mentioned_dimensions(text: str) -> set[str]:
    text = (text or "").strip()
    if not text:
        return set()
    return {
        dimension
        for dimension, pattern in CATEGORY_KEYWORDS.items()
        if re.search(pattern, text)
    }
