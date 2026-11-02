import unittest

from xuangang.config import load_preset
from xuangang.ingest.columns import ColumnMapper, read_field_levels
from xuangang.ingest.positions import build_mapper


class ColumnsTest(unittest.TestCase):
    def setUp(self):
        self.preset = load_preset("guokao")
        self.mapper = build_mapper(self.preset, "positions")

    def test_header_detection_skips_title_row(self):
        rows = [
            ["2027年度国家公务员考试职位表"],
            ["部门代码", "部门名称", "招考职位", "职位代码", "招考人数", "专业", "学历"],
            ["100001", "测试局", "一级科员", "123456789012", "2", "中国语言文学类", "本科及以上"],
        ]
        header = self.mapper.detect_header(rows)
        self.assertIsNotNone(header)
        self.assertEqual(header.header_row, 1)
        self.assertIn("major", header.mapping)
        self.assertIn("dept", header.mapping)

    def test_major_column_not_confused_with_professional_test(self):
        headers = [
            "部门名称", "招考职位", "招考人数", "专业", "学历", "是否在面试阶段组织专业能力测试",
        ]
        mapping, unknown, _ = self.mapper.map_headers(headers)
        self.assertEqual(mapping["major"], [3])
        self.assertIn("是否在面试阶段组织专业能力测试", unknown)

    def test_level_specific_major_columns(self):
        headers = ["招录机关", "职位名称", "招考人数", "研究生专业名称及代码", "本科专业名称及代码", "大专专业名称及代码", "学历要求"]
        row = ["某局", "一级科员", "1", "应用经济学（0202）", "中国语言文学类（B0501）", "", "本科以上"]
        mapper = build_mapper(load_preset("guangdong"), "positions")
        mapping, _, _ = mapper.map_headers(headers)
        levels = read_field_levels(row, mapping, headers)
        self.assertEqual(levels.get("研究生"), "应用经济学（0202）")
        self.assertEqual(levels.get("本科"), "中国语言文学类（B0501）")
        self.assertNotIn("大专", levels)

    def test_missing_required(self):
        mapper = ColumnMapper({"dept": ["部门名称"], "post_name": ["职位名称"]}, ["dept", "post_name", "major"])
        header = mapper.detect_header([["部门名称", "职位名称"], ["某局", "一级科员"]])
        self.assertEqual(header.missing_required, ["major"])


if __name__ == "__main__":
    unittest.main()
