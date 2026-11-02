import unittest

from xuangang.ingest.values import (
    clean_text,
    infer_score_scale,
    normalize_code,
    normalize_key,
    parse_int,
    parse_ratio,
    parse_score_range,
    parse_years,
    score_to_200,
    split_tokens,
    to_halfwidth,
)


class ValuesTest(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(clean_text(None), "")
        self.assertEqual(clean_text(float("nan")), "")
        self.assertEqual(clean_text("  一级\n行政执法员  "), "一级 行政执法员")
        self.assertEqual(clean_text("１３２．５分"), "132.5分")
        self.assertIn("（一）", clean_text("一级行政执法员（一）"))

    def test_to_halfwidth_keeps_chinese_punctuation(self):
        self.assertEqual(to_halfwidth("１２３ＡＢ（一）"), "123AB（一）")

    def test_normalize_code(self):
        self.assertEqual(normalize_code("１００１１０００１００１"), "100110001001")
        self.assertEqual(normalize_code("100110001001.0"), "100110001001")
        self.assertEqual(normalize_code(" 100,110 "), "100110")

    def test_normalize_key(self):
        self.assertEqual(normalize_key("国家税务总局（本级）"), "国家税务总局本级")
        self.assertEqual(normalize_key("一级行政执法员（一）"), normalize_key("一级行政执法员(一)"))

    def test_score_range(self):
        self.assertEqual(parse_score_range("132.5")[0], 132.5)
        self.assertEqual(parse_score_range("132.5-140.2")[:2], (132.5, 140.2))
        self.assertEqual(parse_score_range("132.5～140.2")[:2], (132.5, 140.2))
        self.assertEqual(parse_score_range("约 132.5 分")[0], 132.5)
        self.assertEqual(parse_score_range("未公布")[:2], (None, None))
        self.assertEqual(parse_score_range("")[2], "empty")

    def test_int_and_years(self):
        self.assertEqual(parse_int("3人"), 3)
        self.assertEqual(parse_int("若干"), None)
        self.assertEqual(parse_int("三名"), 3)
        self.assertEqual(parse_years("两年以上"), 2)
        self.assertEqual(parse_years("1年以上"), 1)
        self.assertEqual(parse_years("无限制"), 0)
        self.assertEqual(parse_years("不限"), 0)

    def test_ratio(self):
        self.assertEqual(parse_ratio("3:1"), 3.0)
        self.assertEqual(parse_ratio("1：3"), 3.0)
        self.assertIsNone(parse_ratio("—"))

    def test_scale(self):
        self.assertEqual(infer_score_scale([130, 140, 150]), 200)
        self.assertEqual(infer_score_scale([240, 250, 260]), 300)
        self.assertEqual(infer_score_scale([70, 80, 90]), 100)
        self.assertEqual(score_to_200(240, 300), 160.0)
        self.assertIsNone(score_to_200(None, 200))

    def test_split_tokens(self):
        self.assertEqual(split_tokens("中国语言文学类、新闻传播学类"), ["中国语言文学类", "新闻传播学类"])
        self.assertEqual(split_tokens("法学（0301）；政治学类"), ["法学（0301）", "政治学类"])
        self.assertEqual(split_tokens(""), [])


if __name__ == "__main__":
    unittest.main()
