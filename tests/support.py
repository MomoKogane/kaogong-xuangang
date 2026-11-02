"""测试用的表格夹具与运行辅助。"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import xlsxwriter

from xuangang.config import profile_from_dict
from xuangang.ingest.history import HistorySpec
from xuangang.ingest.positions import PositionSpec
from xuangang.models import Position, Profile
from xuangang.pipeline import RunConfig, run

TEST_TMP = Path(__file__).resolve().parent.parent / ".test-tmp"
TEST_TMP.mkdir(parents=True, exist_ok=True)


class TempDir:
    """不受 tempfile 0o700 ACL 影响的临时目录（部分受限环境会拒绝写入）。"""

    def __init__(self, path: Path):
        self.path = path
        self.name = str(path)

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()


def temp_dir(prefix: str = "t-") -> TempDir:
    path = TEST_TMP / f"{prefix}{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True)
    return TempDir(path)

POSITION_HEADERS = [
    "部门代码", "部门名称", "用人司局", "机构性质", "招考职位", "职位代码", "职位属性", "职位分布",
    "职位简介", "招考人数", "专业", "学历", "学位", "政治面貌", "基层工作最低年限",
    "服务基层项目工作经历", "是否在面试阶段组织专业能力测试", "面试人员比例", "工作地点", "落户地点", "备注",
]

HISTORY_HEADERS = [
    "年份", "部门名称", "用人司局", "职位名称", "职位代码", "最低进面分", "最高进面分", "进面人数", "报名人数", "竞争比",
]


def write_sheet(path: Path, sheet_name: str, headers: list[str], rows: list[list], title: str | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(str(path))
    sheet = workbook.add_worksheet(sheet_name)
    header_format = workbook.add_format({"bold": True})
    start = 0
    if title:
        sheet.merge_range(0, 0, 0, max(1, len(headers) - 1), title)
        start = 1
    for column, header in enumerate(headers):
        sheet.write_string(start, column, header, header_format)
    for offset, row in enumerate(rows):
        for column, value in enumerate(row):
            sheet.write(start + 1 + offset, column, value)
    workbook.close()
    return path


def build_positions(path: Path) -> Path:
    rows = [
        [
            "100001", "测试市税务局", "第一税务分局", "中央国家行政机关省级以下直属机构", "一级行政执法员（一）",
            "100000000001", "普通职位", "其他职位", "从事税务相关工作", "2", "中国语言文学类", "本科及以上",
            "学士", "不限", "无限制", "无限制", "否", "3:1", "测试市", "测试市", "",
        ],
        [
            "100001", "测试市税务局", "第二税务分局", "中央国家行政机关省级以下直属机构", "一级行政执法员（二）",
            "100000000002", "普通职位", "其他职位", "从事税务相关工作", "1", "法学类", "仅限本科",
            "学士", "中共党员", "两年", "无限制", "否", "3:1", "测试市", "测试市", "限男性；最低服务年限5年",
        ],
        [
            "100002", "测试海关", "", "中央国家行政机关省级以下直属机构", "监管一级行政执法员",
            "", "普通职位", "其他职位", "从事海关监管", "3", "专业不限", "仅限本科",
            "学士", "不限", "无限制", "无限制", "否", "3:1", "测试市", "测试市", "需经常出差",
        ],
    ]
    return write_sheet(path, "职位表", POSITION_HEADERS, rows, title="2027年度考试录用公务员职位表（测试夹具）")


def build_history(path: Path) -> Path:
    rows = [
        [2025, "测试市税务局", "第一税务分局", "一级行政执法员（一）", "100000000001", "128.0", "133.5", 6, 90, "15:1"],
        [2026, "测试市税务局", "第一税务分局", "一级行政执法员（一）", "100000000001", "130.5", "136.2", 6, 110, "18.3:1"],
        [2026, "测试市税务局", "第一税务分局", "一级行政执法员（一）", "100000000001", "130.5", "136.2", 6, 110, "18.3:1"],
        [2025, "测试市税务局", "第二税务分局", "一级行政执法员（二）", "", "127.0", "132.0", 6, 80, ""],
        [2026, "测试市税务局", "第二税务分局", "一级行政执法员（二）", "", "132.5-140.0", "", 6, 85, ""],
        [2026, "测试海关", "", "监管一级行政执法员", "", "未公布", "", 6, 70, ""],
        [2026, "测试水利局", "办公室", "办公室科员", "", "135.0", "141.0", 3, 60, ""],
    ]
    return write_sheet(path, "进面分数", HISTORY_HEADERS, rows, title="2026年测试进面分数线（民间整理）")


def make_profile(**overrides) -> Profile:
    data = {
        "name": "bob",
        "education_level": "本科",
        "degree": "学士",
        "full_time": True,
        "major": "汉语言文学",
        "major_code": "050101",
        "major_level": "本科",
        "school": "测试大学",
        "school_tags": ["双一流"],
        "politics": "共青团员",
        "ethnicity": "汉族",
        "gender": "男",
        "birth_year": 2001,
        "fresh_status": "择业期内",
        "graduation_year": 2025,
        "has_employment_record": False,
        "grassroots_years": 2,
        "grassroots_projects": [{"name": "三支一扶", "completed": True}],
        "certificates": ["法律职业资格A证"],
        "hukou_province": "广东省",
        "hometown_province": "广东省",
        "exam": "guokao",
        "province": "",
        "target_year": 2027,
        "estimated_score": 130.0,
        "score_scale": 200,
    }
    data.update(overrides)
    return profile_from_dict(data)


def run_fixture(tmp_path: Path, profile: Profile | None = None, manual_links: Path | None = None):
    positions = build_positions(Path(tmp_path) / "positions.xlsx")
    history = build_history(Path(tmp_path) / "history.xlsx")
    config = RunConfig(
        positions=[PositionSpec(path=positions, exam="guokao", province="全国", year=2027, preset="guokao")],
        history=[HistorySpec(path=history, exam="guokao", province="全国", year=None, kind="笔试最低进面分", scale=200)],
        profile=profile or make_profile(),
        preset="guokao",
        manual_links=manual_links or (Path(tmp_path) / "manual_links.csv"),
        out_dir=Path(tmp_path) / "out",
    )
    return run(config)


def position_by_code(result, code: str):
    for position in result.positions:
        if position.post_code == code:
            return position
    raise AssertionError(f"没有找到职位代码 {code}")


def make_position(**overrides) -> Position:
    data = {
        "id": overrides.pop("id", "p1"),
        "year": overrides.pop("year", 2027),
        "exam": overrides.pop("exam", "guokao"),
        "province": overrides.pop("province", "全国"),
        "source": overrides.pop("source", "test.xlsx"),
        "sheet": overrides.pop("sheet", "s"),
        "row": overrides.pop("row", 2),
    }
    data.update(overrides)
    return Position(**data)
