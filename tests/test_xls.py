import unittest
from pathlib import Path

from tests.support import temp_dir
from xuangang.ingest.excel import read_table
from xuangang.ingest.positions import PositionSpec, load_positions
from xuangang.models import Issue

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class XlsTest(unittest.TestCase):
    def test_biff8(self):
        sheets = read_table(FIXTURES / "legacy_biff8.xls")
        self.assertEqual([sheet.name for sheet in sheets], ["职位表", "第二页"])
        self.assertEqual(len(sheets[0].rows), 6)
        self.assertEqual(sheets[0].rows[0][:4], ["部门名称", "招考职位", "职位代码", "招考人数"])
        self.assertEqual(sheets[0].rows[1][:3], ["测试市税务局", "一级行政执法员（一）", "100000000001"])
        self.assertEqual(sheets[1].rows[1][:3], ["测试教育局", "一级科员", "1"])

    def test_biff5(self):
        sheets = read_table(FIXTURES / "legacy_biff5.xls")
        self.assertEqual([sheet.name for sheet in sheets], ["职位表", "第二页"])
        self.assertEqual(len(sheets[0].rows), 6)
        self.assertEqual(sheets[0].rows[2][1], "一级行政执法员（二）")

    def test_long_sst(self):
        sheets = read_table(FIXTURES / "legacy_long_biff8.xls")
        self.assertEqual(len(sheets), 1)
        self.assertEqual(len(sheets[0].rows), 1201)
        self.assertEqual(sheets[0].rows[1][0], "测试单位0001")
        self.assertIn("中国语言文学类", sheets[0].rows[1][2])

    def test_html_pseudo_xls(self):
        html = (
            "<html><head><meta charset='utf-8'></head><body>"
            "<table><tr><td>部门名称</td><td>职位名称</td><td>招考人数</td></tr>"
            "<tr><td>测试市税务局</td><td>一级科员</td><td>2</td></tr></table>"
            "</body></html>"
        )
        with temp_dir("xls-html-") as tmp:
            path = Path(tmp) / "导出.xls"
            path.write_text(html, encoding="utf-8")
            sheets = read_table(path)
        self.assertEqual(sheets[0].rows[1], ["测试市税务局", "一级科员", "2"])

    def test_xml_pseudo_xls(self):
        xml = (
            "<?xml version='1.0' encoding='UTF-8'?>"
            "<Workbook xmlns='urn:schemas-microsoft-com:office:spreadsheet' "
            "xmlns:ss='urn:schemas-microsoft-com:office:spreadsheet'>"
            "<Worksheet ss:Name='职位表'><Table>"
            "<Row><Cell><Data ss:Type='String'>部门名称</Data></Cell>"
            "<Cell><Data ss:Type='String'>职位名称</Data></Cell></Row>"
            "<Row><Cell><Data ss:Type='String'>测试市税务局</Data></Cell>"
            "<Cell><Data ss:Type='String'>一级科员</Data></Cell></Row>"
            "</Table></Worksheet></Workbook>"
        )
        with temp_dir("xls-xml-") as tmp:
            path = Path(tmp) / "导出.xls"
            path.write_text(xml, encoding="utf-8")
            sheets = read_table(path)
        self.assertEqual(sheets[0].name, "职位表")
        self.assertEqual(sheets[0].rows[1], ["测试市税务局", "一级科员"])

    def test_text_pseudo_xls(self):
        text = "部门名称\t职位名称\t招考人数\n测试市税务局\t一级科员\t2\n"
        with temp_dir("xls-text-") as tmp:
            path = Path(tmp) / "导出.xls"
            path.write_text(text, encoding="utf-8")
            sheets = read_table(path)
        self.assertEqual(sheets[0].rows[1], ["测试市税务局", "一级科员", "2"])

    def test_html_utf16(self):
        html = "<html><body><table><tr><td>部门名称</td><td>职位名称</td></tr><tr><td>测试局</td><td>一级科员</td></tr></table></body></html>"
        with temp_dir("xls-utf16-") as tmp:
            path = Path(tmp) / "导出.xls"
            path.write_bytes(b"\xff\xfe" + html.encode("utf-16-le"))
            sheets = read_table(path)
        self.assertEqual(sheets[0].rows[1], ["测试局", "一级科员"])

    def test_positions_loader(self):
        issues: list[Issue] = []
        positions = load_positions(
            [
                PositionSpec(
                    path=FIXTURES / "legacy_biff8.xls",
                    exam="guokao",
                    province="全国",
                    year=2027,
                    preset="guokao",
                )
            ],
            issues,
        )
        self.assertEqual(len(positions), 6)
        self.assertEqual(positions[0].post_code, "100000000001")
        self.assertEqual(positions[0].headcount, 2)


if __name__ == "__main__":
    unittest.main()
