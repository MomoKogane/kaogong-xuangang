import unittest

from xuangang.ingest.majors import MajorCatalog


class MajorsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.undergrad = MajorCatalog.load("本科")
        cls.graduate = MajorCatalog.load("研究生")

    def test_category_and_major(self):
        self.assertTrue(self.undergrad.match(["中国语言文学类"], "汉语言文学", "050101")[0])
        self.assertTrue(self.undergrad.match(["汉语言文学、秘书学"], "汉语言文学", "050101")[0])
        self.assertFalse(self.undergrad.match(["法学类"], "汉语言文学", "050101")[0])
        self.assertFalse(self.undergrad.match(["会计学"], "汉语言文学", "050101")[0])

    def test_unlimited(self):
        self.assertTrue(self.undergrad.match(["专业不限"], "汉语言文学", "050101")[0])
        self.assertTrue(self.undergrad.match(["不限"], "汉语言文学", "050101")[0])

    def test_code_suffix(self):
        self.assertTrue(self.undergrad.match(["中国语言文学类（B0501）"], "汉语言文学", "050101")[0])
        self.assertFalse(self.undergrad.match(["法学类（B0301）"], "汉语言文学", "050101")[0])
        self.assertTrue(self.undergrad.match(["法学（0301）"], "法学", "030101")[0])

    def test_vague_and_unknown(self):
        self.assertIsNone(self.undergrad.match(["详见备注"], "汉语言文学", "050101")[0])
        self.assertIsNone(self.undergrad.match(["汉语言文学（新方向）"], "汉语言文学", "050101")[0])
        self.assertFalse(self.undergrad.match(["某个目录外的专业"], "汉语言文学", "050101")[0])

    def test_ambiguous_major_vs_discipline(self):
        # 「法学」既可能是专业也可能是门类，跨门类考生应标存疑而不是直接判死
        self.assertIsNone(self.undergrad.match(["法学"], "政治学与行政学", "030202")[0])

    def test_graduate_catalog(self):
        self.assertTrue(self.graduate.match(["法学"], "民商法学", "030105")[0])
        self.assertTrue(self.graduate.match(["中国语言文学"], "汉语言文字学", "050103")[0])
        self.assertFalse(self.graduate.match(["计算机科学与技术"], "民商法学", "030105")[0])

    def test_missing_profile_major(self):
        self.assertIsNone(self.undergrad.match(["中国语言文学类"], "", "")[0])


if __name__ == "__main__":
    unittest.main()
