import unittest

from xuangang.models import Position
from xuangang.rules.education import (
    check_degree,
    check_education,
    parse_degree,
    parse_education,
    profile_degree_level,
    profile_education_level,
)


def make_position(**overrides) -> Position:
    data = {
        "id": "p1",
        "year": 2027,
        "exam": "guokao",
        "province": "全国",
        "source": "test.xlsx",
        "sheet": "s",
        "row": 2,
    }
    data.update(overrides)
    return Position(**data)


class EducationTest(unittest.TestCase):
    def test_parse_education_variants(self):
        self.assertEqual(parse_education("本科及以上").allowed, {4, 5, 6, 7})
        self.assertEqual(parse_education("仅限本科").allowed, {4})
        self.assertTrue(parse_education("仅限本科").exact)
        self.assertEqual(parse_education("本科或硕士研究生").allowed, {4, 5})
        self.assertEqual(parse_education("大专及以上").min_level, 3)
        self.assertTrue(parse_education("学历不限").unlimited)
        self.assertEqual(parse_education("研究生（硕士）及以上").min_level, 5)
        self.assertTrue(parse_education("本科及以上").full_time is False)

    def test_profile_level(self):
        self.assertEqual(profile_education_level("本科"), 4)
        self.assertEqual(profile_education_level("硕士研究生"), 5)
        self.assertEqual(profile_education_level("博士研究生"), 6)

    def test_check_education(self):
        position = make_position(education_raw="本科及以上")
        from tests.support import make_profile

        self.assertTrue(check_education(position, make_profile()).ok)
        position = make_position(education_raw="仅限本科")
        self.assertFalse(check_education(position, make_profile(education_level="硕士研究生")).ok)
        position = make_position(education_raw="硕士研究生及以上")
        self.assertFalse(check_education(position, make_profile()).ok)
        # 只写「本科」时，高学历考生标存疑而不是直接判死
        position = make_position(education_raw="本科")
        self.assertIsNone(check_education(position, make_profile(education_level="硕士研究生")).ok)

    def test_full_time(self):
        position = make_position(education_raw="本科及以上（全日制）")
        from tests.support import make_profile

        self.assertFalse(check_education(position, make_profile(full_time=False)).ok)

    def test_degree(self):
        self.assertEqual(profile_degree_level("学士"), 4)
        self.assertEqual(profile_degree_level("无"), 0)
        position = make_position(degree_raw="学士及以上")
        from tests.support import make_profile

        self.assertTrue(check_degree(position, make_profile()).ok)
        self.assertFalse(check_degree(position, make_profile(degree="无")).ok)
        position = make_position(degree_raw="硕士")
        self.assertIsNone(check_degree(position, make_profile(degree="博士")).ok)


if __name__ == "__main__":
    unittest.main()
