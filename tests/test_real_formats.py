import unittest
from pathlib import Path

import xlsxwriter

from tests.support import make_position, temp_dir
from xuangang.config import load_preset
from xuangang.ingest.excel import read_table
from xuangang.ingest.history import HistorySpec, _fill_scales, load_history
from xuangang.ingest.positions import build_mapper
from xuangang.match.linker import link_records
from xuangang.models import Issue, ScoreRecord

FIXTURES = Path(__file__).resolve().parent / "fixtures"

GUANGDONG_POSITION_HEADER = [
    "招考单位", "单位代码", "招考职位", "职位代码", "职位简介", "职位类型", "录用人数",
    "学历", "学位", "研究生专业 名称及代码", "本科专业 名称及代码", "大专专业 名称及代码",
    "是否要求2年以上基层工作经历", "是否限应届毕业生报考", "其他要求", "考区",
]

GUOKAO_HISTORY_HEADER = [
    "部门代码", "部门名称", "用人司局", "机构性质", "招考职位", "职位简介", "职位代码",
    "招考人数", "报名人数 （10月24日17时）", "过审人数 （10月24日17时）",
    "待审人数 （10月24日17时）", "专业", "学历", "学位", "工作地点", "落户地点", "最低进面分数线",
]


class RealFormatMappingTest(unittest.TestCase):
    def test_guangdong_position_header(self):
        mapper = build_mapper(load_preset("guangdong"), "positions")
        mapping, _unknown, _conf = mapper.map_headers(GUANGDONG_POSITION_HEADER)
        self.assertEqual(mapping["dept"], [0])
        self.assertEqual(mapping["dept_code"], [1])
        self.assertEqual(mapping["post_name"], [2])
        self.assertEqual(mapping["headcount"], [6])
        self.assertEqual(mapping["work_place"], [15])
        self.assertEqual(len(mapping["major"]), 3)
        self.assertIn("fresh", mapping)
        self.assertNotIn("unit", mapping)

    def test_preset_inheritance_merges_aliases(self):
        preset = load_preset("guangdong")
        fields = preset["positions"]["fields"]
        self.assertIn("招考单位", fields["dept"])
        self.assertIn("招录机关", fields["dept"])
        self.assertIn("招考职位", fields["post_name"])
        self.assertIn("职位名称", fields["post_name"])
        self.assertIn("录用人数", fields["headcount"])
        self.assertIn("招考人数", fields["headcount"])

    def test_guokao_history_header(self):
        mapper = build_mapper(load_preset("guokao"), "history")
        mapping, unknown, _conf = mapper.map_headers(GUOKAO_HISTORY_HEADER)
        self.assertEqual(mapping["dept"], [1])
        self.assertEqual(mapping["post_name"], [4])
        self.assertEqual(mapping["post_code"], [6])
        self.assertEqual(mapping["min_score"], [16])
        self.assertNotIn("major", mapping)
        self.assertNotIn("education", mapping)
        self.assertIn("学位", unknown)

    def test_fujian_like_position_header(self):
        headers = [
            "序号", "单位名称", "职位名称", "职位代码", "招录人数", "学历要求", "学位",
            "专业", "政治面貌", "基层工作年限", "考生身份", "其他条件", "工作地点",
        ]
        mapper = build_mapper(load_preset("shengkao_generic"), "positions")
        mapping, unknown, _conf = mapper.map_headers(headers)
        for field in ("dept", "unit", "post_name", "post_code", "headcount", "education", "degree", "major", "politics", "grassroots", "fresh", "remark", "work_place"):
            self.assertIn(field, mapping, field)
        self.assertIn("序号", unknown)
        self.assertEqual(mapping["unit"], [1])

    def test_position_with_only_unit_name(self):
        with temp_dir("fj-position-") as tmp:
            path = Path(tmp) / "福建岗位.xlsx"
            workbook = xlsxwriter.Workbook(str(path))
            sheet = workbook.add_worksheet("职位表")
            headers = ["单位名称", "职位名称", "职位代码", "招录人数", "学历要求", "专业"]
            for column, header in enumerate(headers):
                sheet.write_string(0, column, header)
            sheet.write_string(1, 0, "福建省测试局")
            sheet.write_string(1, 1, "一级科员")
            sheet.write_string(1, 2, "100000000001")
            sheet.write_number(1, 3, 1)
            sheet.write_string(1, 4, "本科及以上")
            sheet.write_string(1, 5, "中国语言文学类")
            workbook.close()
            from xuangang.ingest.positions import PositionSpec, load_positions
            from xuangang.models import Issue

            issues: list[Issue] = []
            positions = load_positions(
                [PositionSpec(path=path, exam="shengkao", province="福建省", year=2027, preset="shengkao_generic")],
                issues,
            )
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].dept, "福建省测试局")

    def test_no_reverse_alias_matching(self):
        mapper = build_mapper(load_preset("guokao"), "history")
        mapping, _unknown, _conf = mapper.map_headers(["分数", "总成绩", "职位"])
        self.assertNotIn("kind", mapping)
        self.assertNotIn("scale", mapping)
        self.assertEqual(mapping.get("post_name"), [2])


class HistoryRobustnessTest(unittest.TestCase):
    def test_per_department_scale(self):
        records = [
            ScoreRecord(year=2026, exam="guokao", province="全国", source="a", sheet="s", row=1,
                        dept="广州铁路公安局", post_name="民警", min_score=60.0, scale=0,
                        kind="笔试最低进面分"),
            ScoreRecord(year=2026, exam="guokao", province="全国", source="a", sheet="s", row=2,
                        dept="广州铁路公安局", post_name="民警", min_score=65.0, scale=0,
                        kind="笔试最低进面分"),
            ScoreRecord(year=2026, exam="guokao", province="全国", source="a", sheet="s", row=3,
                        dept="广州铁路公安局", post_name="民警", min_score=70.0, scale=0,
                        kind="笔试最低进面分"),
            ScoreRecord(year=2026, exam="guokao", province="全国", source="a", sheet="s", row=4,
                        dept="国家税务总局广东省税务局", post_name="科员", min_score=120.0, scale=0,
                        kind="笔试最低进面分"),
            ScoreRecord(year=2026, exam="guokao", province="全国", source="a", sheet="s", row=5,
                        dept="国家税务总局广东省税务局", post_name="科员", min_score=130.0, scale=0,
                        kind="笔试最低进面分"),
            ScoreRecord(year=2026, exam="guokao", province="全国", source="a", sheet="s", row=6,
                        dept="国家税务总局广东省税务局", post_name="科员", min_score=140.0, scale=0,
                        kind="笔试最低进面分"),
        ]
        issues: list[Issue] = []
        _fill_scales(records, issues)
        self.assertEqual({record.scale for record in records if "铁路" in record.dept}, {100})
        self.assertEqual({record.scale for record in records if "税务" in record.dept}, {200})
        self.assertTrue(any(issue.message.startswith("分数制式") for issue in issues))

    def test_guokao_mixed_scale_by_value(self):
        records = [
            ScoreRecord(year=2026, exam="guokao", province="全国", source="a", sheet="s", row=1,
                        dept="云南出入境边防检查站", post_name="民警", min_score=55.0, scale=0,
                        kind="笔试最低进面分"),
            ScoreRecord(year=2026, exam="guokao", province="全国", source="a", sheet="s", row=2,
                        dept="云南出入境边防检查站", post_name="民警", min_score=65.0, scale=0,
                        kind="笔试最低进面分"),
            ScoreRecord(year=2026, exam="guokao", province="全国", source="a", sheet="s", row=3,
                        dept="云南出入境边防检查站", post_name="民警", min_score=125.0, scale=0,
                        kind="笔试最低进面分"),
        ]
        issues: list[Issue] = []
        _fill_scales(records, issues)
        self.assertEqual([record.scale for record in records], [100, 100, 200])

    def test_multi_year_sheets(self):
        with temp_dir("hist-year-") as tmp:
            path = Path(tmp) / "多市分数.xlsx"
            workbook = xlsxwriter.Workbook(str(path))
            for name, year, score in (("2024年厦门分数", 2024, 130.0), ("2025年福州分数", 2025, 135.0)):
                sheet = workbook.add_worksheet(name)
                for column, header in enumerate(["招录单位", "职位代码", "进面分"]):
                    sheet.write_string(0, column, header)
                sheet.write_string(1, 0, "测试局")
                sheet.write_string(1, 1, f"{year}0001")
                sheet.write_number(1, 2, score)
            workbook.close()
            issues: list[Issue] = []
            records = load_history(
                [HistorySpec(path=path, exam="shengkao", province="福建省", year=2026, preset="shengkao_generic")],
                issues,
            )
        self.assertEqual(sorted({record.year for record in records}), [2024, 2025])
        self.assertTrue(any("多个年份" in issue.message for issue in issues))

    def test_code_only_sheet(self):
        with temp_dir("hist-code-") as tmp:
            path = Path(tmp) / "汇总.xlsx"
            workbook = xlsxwriter.Workbook(str(path))
            sheet = workbook.add_worksheet("汇总")
            for column, header in enumerate(["招录单位", "职位代码", "最低进面分"]):
                sheet.write_string(0, column, header)
            sheet.write_string(1, 0, "测试局")
            sheet.write_string(1, 1, "100000000001")
            sheet.write_number(1, 2, 128.5)
            workbook.close()
            issues: list[Issue] = []
            records = load_history(
                [HistorySpec(path=path, exam="guokao", province="全国", year=2026, preset="guokao")],
                issues,
            )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].post_code, "100000000001")
        self.assertEqual(records[0].post_name, "")


class LinkerRobustnessTest(unittest.TestCase):
    def test_duplicate_code_uses_department(self):
        positions = [
            make_position(id="p1", post_code="111", dept="A局", unit="U", post_name="一级科员"),
            make_position(id="p2", post_code="111", dept="B局", unit="U", post_name="一级科员"),
        ]
        record = ScoreRecord(
            year=2026, exam="guokao", province="全国", source="a", sheet="s", row=1,
            dept="B局", unit="U", post_name="一级科员", post_code="111", min_score=130.0,
            scale=200, kind="笔试最低进面分",
        )
        links, _stats = link_records(positions, [record])
        self.assertEqual(links[0].position_id, "p2")
        self.assertEqual(links[0].link_type, "code")
        self.assertTrue(links[0].accepted)

    def test_department_containment(self):
        positions = [
            make_position(id="p1", post_code="111", dept="湛江市雷州市", unit="", post_name="一级科员", exam="shengkao", province="广东省"),
            make_position(id="p2", post_code="222", dept="湛江市徐闻县", unit="", post_name="一级科员", exam="shengkao", province="广东省"),
        ]
        record = ScoreRecord(
            year=2026, exam="shengkao", province="广东省", source="a", sheet="s", row=1,
            dept="雷州市", unit="", post_name="一级科员", post_code="999", min_score=80.0,
            scale=100, kind="笔试最低进面分",
        )
        links, _stats = link_records(positions, [record])
        self.assertEqual(links[0].position_id, "p1")


class MergedCellXlsTest(unittest.TestCase):
    def test_merged_cells(self):
        sheets = read_table(FIXTURES / "legacy_merged_biff8.xls")
        self.assertEqual(len(sheets), 1)
        rows = sheets[0].rows
        for row in rows[1:4]:
            self.assertEqual(row[0], "测试市税务局")
            self.assertEqual(row[1], "第一税务分局")
        self.assertEqual(rows[1][2], "一级科员（1）")


if __name__ == "__main__":
    unittest.main()
