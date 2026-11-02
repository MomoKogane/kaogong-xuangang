"""配置加载：预设、个人条件、manifest、评分参数。

优先级：项目 ``config/`` 下的同名文件覆盖包内 ``resources/`` 默认值。
支持 ``XUANGANG_HOME`` 环境变量指定项目根目录。
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any

from .models import Profile

PACKAGE_ROOT = Path(__file__).resolve().parent
RESOURCES = PACKAGE_ROOT / "resources"


def project_root() -> Path:
    """项目根目录（默认当前工作目录，可用 XUANGANG_HOME 覆盖）。"""
    env = os.environ.get("XUANGANG_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd()


def load_toml(path: Path, required: bool = False) -> dict[str, Any]:
    """读取 TOML 文件；缺失时按需报错。"""
    path = Path(path)
    if not path.exists():
        if required:
            raise FileNotFoundError(f"配置文件不存在：{path}")
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"配置文件格式错误：{path}\n{exc}") from exc


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并字典；列表整体替换。"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def resource_path(*parts: str) -> Path:
    return RESOURCES.joinpath(*parts)


def available_presets() -> list[str]:
    names: set[str] = set()
    for folder in (RESOURCES / "presets", project_root() / "config" / "presets"):
        if folder.is_dir():
            names.update(path.stem for path in folder.glob("*.toml"))
    return sorted(names)


PROVINCE_PRESETS = {
    "广东省": "guangdong",
    "广东": "guangdong",
    "江苏省": "jiangsu",
    "江苏": "jiangsu",
    "山东省": "shandong",
    "山东": "shandong",
}


def default_preset(exam: str, province: str = "") -> str:
    """按考试类型与省份选一个默认列别名预设。"""
    if (exam or "guokao") == "guokao":
        return "guokao"
    text = (province or "").strip()
    for key, preset in PROVINCE_PRESETS.items():
        if key in text:
            return preset
    return "shengkao_generic"


def _merge_preset_fields(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """合并预设时，字段别名取并集（子预设/用户预设只增不减）。"""
    merged = deep_merge(base, override)
    for section in ("positions", "history"):
        base_fields = ((base.get(section) or {}).get("fields") or {})
        override_fields = ((override.get(section) or {}).get("fields") or {})
        if not override_fields:
            continue
        target = merged.setdefault(section, {}).setdefault("fields", {})
        for field_name, aliases in override_fields.items():
            combined = list(base_fields.get(field_name) or [])
            for alias in aliases or []:
                if alias not in combined:
                    combined.append(alias)
            target[field_name] = combined
    return merged


def load_preset(name: str, _seen: set[str] | None = None) -> dict[str, Any]:
    """加载列别名预设（支持 ``[meta] extends`` 继承，项目配置覆盖包内默认）。"""
    if not name:
        name = "guokao"
    seen = _seen if _seen is not None else set()
    if name in seen:
        raise ValueError(f"预设循环继承：{name}")
    seen.add(name)

    base_file = RESOURCES / "presets" / f"{name}.toml"
    if not base_file.exists():
        known = "、".join(available_presets()) or "（无）"
        raise FileNotFoundError(f"未知预设：{name}；可用预设：{known}")
    preset = load_toml(base_file)

    parent_name = (preset.get("meta") or {}).get("extends")
    if parent_name:
        parent = load_preset(str(parent_name), seen)
        preset = _merge_preset_fields(parent, preset)

    override_file = project_root() / "config" / "presets" / f"{name}.toml"
    if override_file.exists():
        preset = _merge_preset_fields(preset, load_toml(override_file))
    preset.setdefault("meta", {}).setdefault("name", name)
    return preset


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    """读取 data/manifest.toml（分数线/岗位表声明）。"""
    if path is None:
        path = project_root() / "data" / "manifest.toml"
    return load_toml(Path(path))


def load_scoring_config() -> dict[str, Any]:
    """评分参数：项目 config/scoring.toml 覆盖默认值。"""
    defaults: dict[str, Any] = {
        "history": {"max_years": 3, "weights": [0.5, 0.3, 0.2]},
        "tiers": {"bao": 10.0, "wen": 4.0, "chong": 0.0},
        "weights": {"fit": 45.0, "heat": 20.0, "capacity": 15.0, "preference": 10.0, "barrier": 10.0},
        "capacity": {"headcount_full": 5.0, "interview_full": 15.0, "headcount_weight": 0.7},
        "heat_percentile": {"high": 0.75, "medium": 0.5},
        "preference": {"neutral": 0.5},
        "barrier": {
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
        },
    }
    override = load_toml(project_root() / "config" / "scoring.toml")
    return deep_merge(defaults, override)


PROFILE_TEMPLATE = """# 考公选岗个人条件（bob.toml）
# 修改后运行： .\\run.ps1 run --config config\\bob.toml --positions ... --history ...

name = "bob"

# ---------- 学历 / 学位 / 专业 ----------
education_level = "本科"          # 大专 | 本科 | 硕士研究生 | 博士研究生
degree = "学士"                  # 无 | 学士 | 硕士 | 博士
full_time = true                 # 是否全日制
major = "汉语言文学"              # 毕业证上的专业全称
major_code = "050101"            # 可选，专业代码（能填就填，匹配更准）
major_level = "本科"              # 专业目录层级：本科 | 研究生
school = ""                      # 院校名称（可选）
school_tags = []                 # 院校标签，如 ["双一流", "985"]

# ---------- 身份条件 ----------
politics = "共青团员"             # 中共党员 | 中共预备党员 | 共青团员 | 群众 | 民主党派
ethnicity = "汉族"                # 民族
gender = "男"                    # 男 | 女
birth_year = 2001                # 出生年份（用于年龄提示）
fresh_status = "择业期内"          # 当年应届 | 择业期内 | 非应届
graduation_year = 2025
has_employment_record = false    # 是否已落实工作单位（影响「择业期内未落实工作」类岗位）

# ---------- 工作经历 / 证书 ----------
grassroots_years = 2             # 基层工作年限（0/1/2/3...）
certificates = ["法律职业资格A证"]

# ---------- 地域 ----------
hukou_province = "广东省"         # 户籍所在省
hometown_province = "广东省"      # 生源所在省

# ---------- 选岗偏好（影响排序，不影响能不能报） ----------
preferred_regions = ["广州", "深圳"]   # 意向工作城市/省份关键词，可留空
prefer_hometown = false           # 是否把户籍/生源所在省也作为偏好

# ---------- 考试与参考分 ----------
exam = "guokao"                  # guokao | shengkao
province = ""                    # 省考时填写，如 "广东省"
target_year = 2027               # 要报考的年份
estimated_score = 132.5          # 可选：预估笔试分（没有就不填）
score_scale = 200                # 预估分对应的满分（国考 200）

# 服务基层项目（没有就整段删掉；数组表必须放在文件最后，否则后面的键会落进这张表）
[[grassroots_projects]]
name = "三支一扶"
completed = true                 # 是否服务期满且考核合格
"""


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，、]", value) if item.strip()]
    return [str(item).strip() for item in value if str(item).strip()]


def profile_from_dict(data: dict[str, Any]) -> Profile:
    """从 TOML/JSON 字典构造 Profile，忽略未知键。"""
    profile = Profile()
    for key, value in data.items():
        if hasattr(profile, key):
            setattr(profile, key, value)
    projects = data.get("grassroots_projects") or []
    if isinstance(projects, dict):
        projects = [projects]
    profile.grassroots_projects = list(projects)
    profile.school_tags = _as_list(data.get("school_tags"))
    profile.certificates = _as_list(data.get("certificates"))
    profile.preferred_regions = _as_list(data.get("preferred_regions"))
    for key in ("full_time", "has_employment_record", "veteran", "disabled", "prefer_hometown"):
        value = getattr(profile, key, None)
        if isinstance(value, str):
            setattr(profile, key, value.strip().lower() in {"true", "1", "是", "yes"})
    if profile.estimated_score is not None:
        try:
            profile.estimated_score = float(profile.estimated_score)
        except (TypeError, ValueError):
            profile.estimated_score = None
    return profile


def load_profile(path: Path) -> Profile:
    data = load_toml(Path(path), required=True)
    return profile_from_dict(data)


def write_profile_template(path: Path, overwrite: bool = False) -> Path:
    path = Path(path)
    if path.exists() and not overwrite:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(PROFILE_TEMPLATE, encoding="utf-8")
    return path


PROFILE_KEYS = [
    "name",
    "education_level",
    "degree",
    "full_time",
    "major",
    "major_code",
    "major_level",
    "school",
    "school_tags",
    "politics",
    "ethnicity",
    "gender",
    "birth_year",
    "fresh_status",
    "graduation_year",
    "has_employment_record",
    "grassroots_years",
    "grassroots_projects",
    "certificates",
    "hukou_province",
    "hometown_province",
    "exam",
    "province",
    "target_year",
    "estimated_score",
    "score_scale",
]
