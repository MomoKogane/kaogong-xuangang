import unittest

from tests.support import make_position, make_profile
from xuangang.rules import certs as certs_module
from xuangang.rules.composite import evaluate
from xuangang.rules.ethnicity import check_ethnicity
from xuangang.rules.extras import check_age, check_gender, check_hukou, collect_warnings
from xuangang.rules.fresh import check_fresh
from xuangang.rules.grassroots import check_grassroots
from xuangang.rules.notes import extract_requirements, mentioned_dimensions
from xuangang.rules.politics import check_politics


class PoliticsTest(unittest.TestCase):
    def test_party(self):
        position = make_position(politics_raw="中共党员")
        self.assertFalse(check_politics(position, make_profile()).ok)
        self.assertTrue(check_politics(position, make_profile(politics="中共党员")).ok)
        self.assertTrue(check_politics(position, make_profile(politics="中共预备党员")).ok)

    def test_unlimited(self):
        position = make_position(politics_raw="不限")
        self.assertTrue(check_politics(position, make_profile()).ok)

    def test_or_league(self):
        position = make_position(politics_raw="中共党员或共青团员")
        self.assertTrue(check_politics(position, make_profile(politics="共青团员")).ok)


class EthnicityTest(unittest.TestCase):
    def test_minority(self):
        position = make_position(ethnicity_raw="限少数民族")
        self.assertFalse(check_ethnicity(position, make_profile(ethnicity="汉族")).ok)
        self.assertTrue(check_ethnicity(position, make_profile(ethnicity="壮族")).ok)

    def test_specific(self):
        position = make_position(ethnicity_raw="限维吾尔族")
        self.assertFalse(check_ethnicity(position, make_profile(ethnicity="汉族")).ok)
        self.assertTrue(check_ethnicity(position, make_profile(ethnicity="维吾尔族")).ok)


class FreshTest(unittest.TestCase):
    def test_year_specific(self):
        position = make_position(fresh_raw="2027年应届毕业生")
        self.assertTrue(check_fresh(position, make_profile(fresh_status="当年应届", graduation_year=2027)).ok)
        self.assertFalse(check_fresh(position, make_profile(fresh_status="择业期内", graduation_year=2025)).ok)

    def test_generic(self):
        position = make_position(fresh_raw="应届毕业生")
        self.assertTrue(check_fresh(position, make_profile(fresh_status="择业期内")).ok)
        self.assertFalse(check_fresh(position, make_profile(fresh_status="非应届")).ok)

    def test_employment_record(self):
        position = make_position(fresh_raw="应届毕业生")
        self.assertIsNone(
            check_fresh(position, make_profile(fresh_status="择业期内", has_employment_record=True)).ok
        )


class GrassrootsTest(unittest.TestCase):
    def test_years_boundary(self):
        position = make_position(grassroots_raw="两年")
        self.assertTrue(check_grassroots(position, make_profile(grassroots_years=2)).ok)
        self.assertFalse(check_grassroots(position, make_profile(grassroots_years=1)).ok)

    def test_projects(self):
        position = make_position(grassroots_projects_raw="三支一扶")
        self.assertTrue(check_grassroots(position, make_profile()).ok)
        self.assertFalse(check_grassroots(position, make_profile(grassroots_projects=[])).ok)
        incomplete = make_profile(grassroots_projects=[{"name": "三支一扶", "completed": False}])
        self.assertIsNone(check_grassroots(position, incomplete).ok)

    def test_generic_project(self):
        position = make_position(grassroots_projects_raw="服务基层项目人员")
        self.assertTrue(check_grassroots(position, make_profile()).ok)

    def test_no_requirement(self):
        position = make_position(grassroots_raw="无限制")
        self.assertIsNone(check_grassroots(position, make_profile()))


class CertTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = certs_module.CertRegistry.load()

    def test_level_match(self):
        position = make_position(cert_raw="法律职业资格A类")
        self.assertTrue(self.registry.check(position, make_profile()).ok)
        c_cert = make_profile(certificates=["法律职业资格C证"])
        self.assertFalse(self.registry.check(position, c_cert).ok)
        self.assertFalse(self.registry.check(position, make_profile(certificates=[])).ok)

    def test_generic_cert(self):
        position = make_position(cert_raw="教师资格证")
        self.assertFalse(self.registry.check(position, make_profile()).ok)
        self.assertTrue(
            self.registry.check(position, make_profile(certificates=["教师资格证"])).ok
        )

    def test_unknown_cert(self):
        position = make_position(cert_raw="具有某种特殊资格证书")
        self.assertIsNone(self.registry.check(position, make_profile()).ok)


class NotesTest(unittest.TestCase):
    def test_extract(self):
        notes = extract_requirements("限男性；最低服务年限5年；需经常出差")
        dimensions = {note.dimension for note in notes}
        self.assertIn("gender", dimensions)
        self.assertIn("service", dimensions)
        self.assertIn("warning", dimensions)
        self.assertTrue(any(note.kind == "soft" for note in notes))

    def test_mentions(self):
        dims = mentioned_dimensions("限本省户籍，中共党员优先，需通过体能测评")
        self.assertIn("hukou", dims)
        self.assertIn("politics", dims)


class ExtrasTest(unittest.TestCase):
    def test_hukou(self):
        position = make_position(hukou_raw="限本省户籍", province="广东省")
        self.assertTrue(check_hukou(position, make_profile()).ok)
        self.assertFalse(check_hukou(position, make_profile(hukou_province="湖南省", hometown_province="湖南省")).ok)

    def test_gender(self):
        position = make_position(gender_raw="限女性")
        self.assertFalse(check_gender(position, make_profile(gender="男")).ok)
        self.assertTrue(check_gender(position, make_profile(gender="女")).ok)

    def test_age(self):
        position = make_position(notes=extract_requirements("35周岁以下"))
        self.assertTrue(check_age(position, make_profile(birth_year=2001)).ok)
        self.assertFalse(check_age(position, make_profile(birth_year=1985)).ok)

    def test_warnings(self):
        position = make_position(notes=extract_requirements("最低服务年限5年；需经常出差"))
        warnings = collect_warnings(position, make_profile())
        self.assertTrue(any("服务年限" in item for item in warnings))
        self.assertTrue(any("出差" in item for item in warnings))


class CompositeTest(unittest.TestCase):
    def test_compliant(self):
        position = make_position(
            major_raw="中国语言文学类",
            education_raw="本科及以上",
            degree_raw="学士",
            politics_raw="不限",
            fresh_raw="不限",
            grassroots_raw="无限制",
        )
        outcome = evaluate(position, make_profile())
        self.assertEqual(outcome.status, "符合")

    def test_rejected(self):
        position = make_position(
            major_raw="中国语言文学类",
            education_raw="本科及以上",
            degree_raw="学士",
            politics_raw="不限",
            fresh_raw="不限",
            grassroots_raw="无限制",
            remark="限女性",
        )
        self.assertEqual(evaluate(position, make_profile()).status, "不符合")

    def test_unknown(self):
        position = make_position(
            major_raw="中国语言文学类",
            education_raw="本科及以上",
            degree_raw="学士",
            politics_raw="不限",
            fresh_raw="不限",
            grassroots_raw="无限制",
            remark="须具有某种特殊资格证书",
        )
        self.assertEqual(evaluate(position, make_profile()).status, "存疑")


if __name__ == "__main__":
    unittest.main()
