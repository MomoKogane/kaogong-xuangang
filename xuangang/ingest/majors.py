"""专业匹配：把职位要求的专业表述与考生专业对上。

官方岗位表的「专业」列可能写：专业全称、专业类（…类）、门类、专业代码，
或者「不限」。匹配顺序：
1. 专业不限 -> 通过
2. 名称/代码精确命中
3. 职位写的是专业类/门类 -> 用专业目录向上匹配
4. 目录查不到、表述含糊 -> 存疑，提示人工核对
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import RESOURCES
from .values import clean_text, normalize_key, split_tokens

_LEVEL_PREFIX = re.compile(r"^(研究生|本科|大专|专科|博士|硕士)\s*[:：]?\s*")
_CODE_IN_TOKEN = re.compile(r"[（(]\s*([A-Za-z]?\d{2,6})\s*[)）]")
_CODE_PREFIX = re.compile(r"^([A-Za-z]?\d{2,6})\s*")
_UNLIMITED = {"不限", "专业不限", "无限制", "无要求", "不限专业"}
_VAGUE = ("详见", "相关专业", "等专业", "专业目录", "见备注", "参考目录", "相近")


@dataclass
class MajorNode:
    name: str
    code: str
    kind: str  # major | category | discipline
    category: str = ""
    discipline: str = ""


@dataclass
class ProfileMajor:
    name: str
    code: str
    category: str = ""
    discipline: str = ""
    known: bool = False


class MajorCatalog:
    def __init__(self, data: dict, level: str = "本科"):
        self.level = level
        self.nodes: list[MajorNode] = []
        self.by_name: dict[str, list[MajorNode]] = {}
        self.by_code: dict[str, MajorNode] = {}
        self._load(data)

    @classmethod
    def load(cls, level: str = "本科", catalog_path: Path | None = None) -> "MajorCatalog":
        if catalog_path:
            return cls(_load_custom_catalog(Path(catalog_path)), level=f"{level}（自定义目录）")
        filename = "graduate.json" if "研究生" in (level or "") or "硕士" in (level or "") or "博士" in (level or "") else "undergraduate.json"
        path = RESOURCES / "majors" / filename
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data, level=data.get("level", level))

    def _load(self, data: dict) -> None:
        for discipline in data.get("disciplines") or []:
            discipline_name = clean_text(discipline.get("name"))
            discipline_code = clean_text(discipline.get("code"))
            discipline_node = MajorNode(
                name=discipline_name,
                code=discipline_code,
                kind="discipline",
                discipline=discipline_name,
            )
            self._add_node(discipline_node)
            for category in discipline.get("categories") or []:
                category_name = clean_text(category.get("name"))
                category_code = clean_text(category.get("code"))
                category_node = MajorNode(
                    name=category_name,
                    code=category_code,
                    kind="category",
                    category=category_name,
                    discipline=discipline_name,
                )
                self._add_node(category_node)
                for major in category.get("majors") or []:
                    name = clean_text(major.get("name") if isinstance(major, dict) else major)
                    code = clean_text(major.get("code")) if isinstance(major, dict) else ""
                    if not name:
                        continue
                    self._add_node(
                        MajorNode(
                            name=name,
                            code=code,
                            kind="major",
                            category=category_name,
                            discipline=discipline_name,
                        )
                    )

    def _add_node(self, node: MajorNode) -> None:
        self.nodes.append(node)
        key = normalize_key(node.name)
        if key:
            self.by_name.setdefault(key, []).append(node)
        if node.code and node.code not in self.by_code:
            self.by_code[node.code] = node

    def lookup(self, name: str, code: str = "") -> list[MajorNode]:
        if code:
            node = self.by_code.get(code)
            if node:
                return [node]
        key = normalize_key(name)
        if not key:
            return []
        candidates = list(self.by_name.get(key) or [])
        if not candidates:
            if key.endswith("类"):
                candidates = list(self.by_name.get(key[:-1]) or [])
            else:
                candidates = list(self.by_name.get(key + "类") or [])
        return candidates

    def resolve_profile_major(self, major: str, code: str = "") -> ProfileMajor:
        profile = ProfileMajor(name=clean_text(major), code=_normalize_major_code(code))
        if not profile.name and not profile.code:
            return profile
        nodes = self.lookup(profile.name, profile.code)
        for node in nodes:
            if node.kind == "major":
                profile.category = node.category
                profile.discipline = node.discipline
                profile.code = profile.code or node.code
                profile.known = True
                return profile
        for node in nodes:
            if node.kind == "category":
                profile.category = node.category
                profile.discipline = node.discipline
                profile.known = True
                return profile
        if profile.code:
            # 用代码前缀找专业类 / 门类
            for length in (4, 2):
                prefix = profile.code[:length]
                node = self.by_code.get(prefix)
                if node:
                    profile.category = node.category or node.name
                    profile.discipline = node.discipline
                    profile.known = bool(profile.category)
                    if profile.known:
                        return profile
        for node in nodes:
            if node.kind == "discipline":
                profile.discipline = node.discipline
                profile.known = True
                return profile
        return profile

    def match(self, tokens: list[str], profile_major: str, profile_code: str = "") -> tuple[Optional[bool], str]:
        """返回 (True=符合 / False=不符合 / None=存疑, 说明)。"""
        profile = self.resolve_profile_major(profile_major, profile_code)
        expanded: list[str] = []
        for token in tokens:
            if clean_text(token):
                expanded.extend(split_tokens(token))
        token_list = [token for token in expanded if clean_text(token)]
        if not token_list:
            return None, "职位「专业」列没有可解析的内容，需人工核对"

        cleaned: list[str] = []
        for token in token_list:
            text = clean_text(token)
            if not text:
                continue
            if any(vague in text for vague in _VAGUE):
                return None, f"专业表述含糊（{text}），请以招录机关解释为准"
            if normalize_key(text) in _UNLIMITED:
                return True, "职位专业不限"
            cleaned.append(text)
        if not cleaned:
            return None, "职位「专业」列没有可解析的内容"

        if not profile.name and not profile.code:
            return None, "个人条件里没有填写专业"

        unknown_tokens: list[str] = []
        ambiguous_tokens: list[str] = []
        known_no_match: list[str] = []
        for token in cleaned:
            name, code = _parse_token(token)
            if not name and not code:
                continue
            nodes = self.lookup(name, code)
            major_nodes = [node for node in nodes if node.kind == "major"]
            if major_nodes:
                # 目录里有同名「专业」时按专业解释；只有考生就是该专业才算精确匹配。
                # 同时它也可能是门类名（如「法学」），这时对不上就标存疑而不是判死。
                if profile.name and any(
                    normalize_key(node.name) == normalize_key(profile.name) for node in major_nodes
                ):
                    return True, f"专业精确匹配：{token}"
                discipline_match = profile.discipline and any(
                    node.kind == "discipline" and normalize_key(node.name) == normalize_key(profile.discipline)
                    for node in nodes
                )
                if discipline_match:
                    ambiguous_tokens.append(token)
                else:
                    known_no_match.append(token)
                continue
            for node in nodes:
                if node.kind == "category" and profile.category:
                    if normalize_key(node.name) == normalize_key(profile.category):
                        return True, f"专业类匹配：你的专业属于「{node.name}」"
                if node.kind == "discipline" and profile.discipline:
                    if normalize_key(node.name) == normalize_key(profile.discipline):
                        return True, f"专业门类匹配：你的专业属于「{node.name}」门类"
            if code and profile.code and (profile.code.startswith(code) or code.startswith(profile.code)):
                return True, f"专业代码匹配：{code}"
            if nodes:
                kinds = {node.kind for node in nodes}
                if len(kinds) > 1:
                    ambiguous_tokens.append(token)
                else:
                    known_no_match.append(token)
            else:
                unknown_tokens.append(token)

        if ambiguous_tokens:
            return None, "职位专业表述有多种理解：" + "、".join(ambiguous_tokens[:3])
        if unknown_tokens:
            if not profile.known:
                return None, f"你的专业「{profile.name}」不在内置专业目录中，建议导入本省专业目录后再匹配"
            related = [token for token in unknown_tokens if _related_to_profile(token, profile)]
            if related:
                return None, "以下专业不在内置目录中，无法判定：" + "、".join(related[:3])
            # 目录外的专业与考生专业没有名称/代码关联，可以认为不匹配
            return False, "职位专业要求与你的专业不匹配（已忽略目录外的不相关专业）"
        if not profile.known:
            return None, f"你的专业「{profile.name}」不在内置专业目录中，建议导入本省专业目录后再匹配"
        return False, "职位专业要求与你的专业不匹配"


def _related_to_profile(token: str, profile: ProfileMajor) -> bool:
    name, code = _parse_token(token)
    if code and profile.code:
        if code[:2] != profile.code[:2]:
            return False
    text = name or token
    if text.endswith("类") or "门类" in text:
        return True
    for value in (profile.name, profile.category, profile.discipline):
        if value and (value in text or text in value):
            return True
    for value in (profile.name, profile.category):
        if not value:
            continue
        for index in range(len(value) - 1):
            fragment = value[index : index + 2]
            if fragment and fragment in text:
                return True
    return False


def _parse_token(token: str) -> tuple[str, str]:
    text = clean_text(token)
    text = _LEVEL_PREFIX.sub("", text)
    code = ""
    match = _CODE_IN_TOKEN.search(text)
    if match:
        code = _normalize_major_code(match.group(1))
        text = text.replace(match.group(0), "")
    else:
        match = _CODE_PREFIX.match(text)
        if match:
            code = _normalize_major_code(match.group(1))
            text = text[match.end():]
    name = normalize_key(text)
    return name, code


def _normalize_major_code(code: str) -> str:
    """省考专业代码常带 B/A 前缀（如 B0501），比较时只留数字部分。"""
    return re.sub(r"[^0-9]", "", code or "")


_CUSTOM_ALIASES = {
    "name": ["专业名称", "专业", "学科专业", "专业名称及代码"],
    "code": ["专业代码", "学科代码", "代码"],
    "category": ["专业类", "专业类别", "学科类别", "一级学科", "类"],
    "discipline": ["门类", "学科门类", "专业门类", "大类"],
    "level": ["学历层次", "层次", "学历"],
}


def _load_custom_catalog(path: Path) -> dict:
    """从 Excel/CSV 读取用户提供的专业目录（列名尽量宽松）。"""
    from .columns import ColumnMapper, read_field
    from .excel import read_table

    mapper = ColumnMapper(_CUSTOM_ALIASES, ["name"], max_header_scan=10)
    groups: dict[tuple[str, str], dict] = {}
    for raw_sheet in read_table(path):
        header = mapper.detect_header(raw_sheet.rows)
        if not header or "name" not in header.mapping:
            continue
        for row in raw_sheet.rows[header.header_row + 1 :]:
            name = read_field(row, header.mapping, "name")
            if not name:
                continue
            category = read_field(row, header.mapping, "category") or "其他"
            discipline = read_field(row, header.mapping, "discipline") or "其他"
            code = read_field(row, header.mapping, "code")
            key = (discipline, category)
            entry = groups.setdefault(
                key,
                {"code": "", "name": category, "majors": []},
            )
            entry["majors"].append({"name": name, "code": code})
    disciplines: dict[str, dict] = {}
    for (discipline, _category), category in groups.items():
        node = disciplines.setdefault(discipline, {"code": "", "name": discipline, "categories": []})
        node["categories"].append(category)
    return {"level": "自定义", "disciplines": list(disciplines.values())}
