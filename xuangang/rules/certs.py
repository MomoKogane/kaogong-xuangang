"""执业 / 职业资格证书匹配。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..config import load_toml, project_root, resource_path
from ..ingest.values import clean_text, normalize_key
from ..models import Certificate, Check, Profile

_REQUIRE_HINT = re.compile(r"资格证|资格证书|执业资格|职业资格|证书|持证")


@dataclass
class CertSpec:
    cert_id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    levels: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class CertRequirement:
    cert_id: str
    name: str
    level: str
    raw: str
    evidence: str


class CertRegistry:
    def __init__(self, specs: list[CertSpec]):
        self.specs = specs
        self.by_id = {spec.cert_id: spec for spec in specs}
        self._alias_index: list[tuple[str, CertSpec]] = []
        self._level_index: list[tuple[str, str, CertSpec]] = []
        for spec in specs:
            for alias in spec.aliases:
                key = normalize_key(alias)
                if key:
                    self._alias_index.append((key, spec))
            for level, level_aliases in spec.levels.items():
                for alias in level_aliases:
                    key = normalize_key(alias)
                    if key:
                        self._level_index.append((key, level, spec))
        self._alias_index.sort(key=lambda item: len(item[0]), reverse=True)
        self._level_index.sort(key=lambda item: len(item[0]), reverse=True)

    @classmethod
    def load(cls) -> "CertRegistry":
        specs: dict[str, CertSpec] = {}
        paths = [resource_path("certs.toml")]
        override = project_root() / "config" / "certs.toml"
        if override.exists():
            paths.append(override)
        for path in paths:
            data = load_toml(Path(path))
            for item in data.get("cert") or []:
                cert_id = clean_text(item.get("id"))
                if not cert_id:
                    continue
                spec = specs.get(cert_id)
                if spec is None:
                    spec = CertSpec(
                        cert_id=cert_id,
                        name=clean_text(item.get("name")) or cert_id,
                        aliases=[],
                        levels={},
                    )
                    specs[cert_id] = spec
                if item.get("name"):
                    spec.name = clean_text(item.get("name"))
                for alias in item.get("aliases") or []:
                    alias = clean_text(alias)
                    if alias and alias not in spec.aliases:
                        spec.aliases.append(alias)
                for level, level_aliases in (item.get("levels") or {}).items():
                    merged = spec.levels.setdefault(clean_text(level), [])
                    for alias in level_aliases or []:
                        alias = clean_text(alias)
                        if alias and alias not in merged:
                            merged.append(alias)
        return cls(list(specs.values()))

    def _find_level(self, text: str, start: int, end: int, spec: CertSpec) -> str:
        window = text[max(0, start - 10) : min(len(text), end + 10)]
        for alias_key, level, level_spec in self._level_index:
            if level_spec.cert_id != spec.cert_id:
                continue
            if alias_key and alias_key in normalize_key(window):
                return level
        return ""

    def parse_requirement(self, text: str) -> list[CertRequirement]:
        normalized = normalize_key(text)
        if not normalized:
            return []
        results: list[CertRequirement] = []
        seen: set[tuple[str, str]] = set()
        for alias_key, spec in self._alias_index:
            start = normalized.find(alias_key)
            while start != -1:
                level = self._find_level(normalized, start, start + len(alias_key), spec)
                key = (spec.cert_id, level)
                if key not in seen:
                    seen.add(key)
                    results.append(
                        CertRequirement(
                            cert_id=spec.cert_id,
                            name=spec.name,
                            level=level,
                            raw=text,
                            evidence=_slice(text, start, start + len(alias_key)),
                        )
                    )
                start = normalized.find(alias_key, start + 1)
        return results

    def parse_profile_certificate(self, raw: str) -> Certificate:
        text = clean_text(raw)
        normalized = normalize_key(text)
        for alias_key, spec in self._alias_index:
            if alias_key and alias_key in normalized:
                level = self._find_level(normalized, normalized.find(alias_key), normalized.find(alias_key) + len(alias_key), spec)
                return Certificate(cert_id=spec.cert_id, level=level, raw=text)
        return Certificate(cert_id="", level="", raw=text)

    def check(self, position, profile: Profile) -> Optional[Check]:
        text = "；".join(
            item
            for item in (
                clean_text(position.cert_raw),
                clean_text(position.remark),
                clean_text(position.post_desc),
                clean_text(position.post_attr),
            )
            if item
        )
        requirements = self.parse_requirement(text)
        if not requirements:
            if _REQUIRE_HINT.search(text):
                return Check("执业资格", None, "备注提到证书要求，但没有识别出具体证书，需人工核对", _slice(text, 0, 40))
            return None

        bob = profile.cert_objs or []
        if not bob:
            bob = [self.parse_profile_certificate(item) for item in profile.certificates]
            profile.cert_objs = bob
        bob_by_id = {cert.cert_id: cert for cert in bob if cert.cert_id}

        for requirement in requirements:
            cert = bob_by_id.get(requirement.cert_id)
            if cert is None:
                matched_raw = any(
                    normalize_key(item.raw) and normalize_key(item.raw) in normalize_key(text)
                    for item in bob
                    if not item.cert_id
                )
                if matched_raw:
                    continue
                label = f"{requirement.name}{requirement.level or ''}"
                return Check(
                    "执业资格",
                    False,
                    f"职位要求{label}，你的证书里没有",
                    requirement.evidence,
                )
            if requirement.level:
                if not cert.level:
                    return Check(
                        "执业资格",
                        None,
                        f"职位要求{requirement.name}{requirement.level}，你的证书未写等级",
                        requirement.evidence,
                    )
                if cert.level != requirement.level:
                    return Check(
                        "执业资格",
                        False,
                        f"职位要求{requirement.name}{requirement.level}，你的是{cert.level}",
                        requirement.evidence,
                    )
        labels = "、".join(f"{item.name}{item.level or ''}" for item in requirements)
        return Check("执业资格", True, f"证书满足（{labels}）", requirements[0].evidence)


def _slice(text: str, start: int, end: int, span: int = 16) -> str:
    left = max(0, start - span)
    right = min(len(text), end + span)
    snippet = text[left:right].strip()
    if left > 0:
        snippet = "…" + snippet
    if right < len(text):
        snippet = snippet + "…"
    return snippet


_REGISTRY: CertRegistry | None = None


def registry() -> CertRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = CertRegistry.load()
    return _REGISTRY
