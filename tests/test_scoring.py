import unittest

from tests.support import make_position, make_profile
from xuangang.models import Check, MatchOutcome, ScoreRecord
from xuangang.scoring import build_year_distributions, evaluate_position


def record(year, score, scale=200, **overrides):
    data = {
        "year": year,
        "exam": "guokao",
        "province": "全国",
        "source": "分数.xlsx",
        "sheet": "s",
        "row": year,
        "dept": "A局",
        "post_name": "一级科员",
        "min_score": score,
        "max_score": score,
        "scale": scale,
        "kind": "笔试最低进面分",
    }
    data.update(overrides)
    return ScoreRecord(**data)


class ScoringTest(unittest.TestCase):
    def test_predicted_and_tier(self):
        position = make_position(post_name="一级科员", headcount=3, interview_ratio="3:1")
        records = [record(2024, 130.0), record(2025, 135.0), record(2026, 140.0)]
        distributions = build_year_distributions(records)
        evaluation = evaluate_position(position, records, distributions, make_profile(estimated_score=145))
        self.assertAlmostEqual(evaluation.predicted, 136.5)
        self.assertEqual(evaluation.confidence, "高")
        self.assertEqual([point.year for point in evaluation.history], [2026, 2025, 2024])
        self.assertEqual(evaluation.tier, "稳")
        self.assertGreater(evaluation.index, 0)

    def test_risk_tier(self):
        position = make_position(post_name="一级科员", headcount=1)
        records = [record(2026, 140.0)]
        evaluation = evaluate_position(position, records, build_year_distributions(records), make_profile(estimated_score=120))
        self.assertEqual(evaluation.tier, "风险")
        self.assertEqual(evaluation.confidence, "低")

    def test_missing_year_reweights(self):
        position = make_position(post_name="一级科员", headcount=2)
        records = [record(2025, 130.0), record(2026, 140.0)]
        evaluation = evaluate_position(position, records, build_year_distributions(records), make_profile(estimated_score=120))
        self.assertAlmostEqual(evaluation.predicted, (140 * 0.5 + 130 * 0.3) / 0.8, places=2)

    def test_scale_conversion(self):
        position = make_position(post_name="一级科员", headcount=2, interview_ratio="3:1")
        records = [record(2025, 240.0, scale=300), record(2026, 250.0, scale=300)]
        evaluation = evaluate_position(position, records, build_year_distributions(records), make_profile(estimated_score=240, score_scale=300))
        self.assertAlmostEqual(evaluation.predicted_200, (166.67 * 0.5 + 160 * 0.3) / 0.8, places=1)
        self.assertAlmostEqual(evaluation.predicted, (166.67 * 0.5 + 160 * 0.3) / 0.8 / 200 * 300, places=0)

    def test_no_history(self):
        position = make_position(post_name="一级科员", headcount=2)
        evaluation = evaluate_position(position, [], {}, make_profile())
        self.assertIsNone(evaluation.predicted)
        self.assertEqual(evaluation.confidence, "无")
        self.assertTrue(evaluation.notes)

    def test_old_years_filtered(self):
        position = make_position(post_name="一级科员", headcount=2)
        records = [record(2023, 130.0), record(2024, 135.0), record(2025, 140.0), record(2026, 145.0)]
        evaluation = evaluate_position(position, records, build_year_distributions(records), make_profile(estimated_score=150))
        self.assertEqual(len(evaluation.history), 3)
        self.assertEqual(evaluation.history[0].year, 2026)

    def test_heat(self):
        position = make_position(post_name="一级科员", headcount=2)
        records = [record(2026, 145.0)]
        extra = [record(2026, 120.0 + index, row=100 + index) for index in range(9)]
        distributions = build_year_distributions(records + extra)
        evaluation = evaluate_position(position, records, distributions, make_profile())
        self.assertIsNotNone(evaluation.heat)
        self.assertGreater(evaluation.heat, 0.5)

    def test_preference_boost(self):
        position = make_position(
            post_name="一级科员",
            headcount=2,
            dept="广州市税务局",
            unit="广州市税务局",
            work_place="广东省广州市",
        )
        records = [record(2026, 130.0)]
        distributions = build_year_distributions(records)
        neutral = evaluate_position(position, records, distributions, make_profile(estimated_score=135))
        liked = evaluate_position(
            position,
            records,
            distributions,
            make_profile(estimated_score=135, preferred_regions=["广州"]),
        )
        self.assertIsNone(neutral.preference)
        self.assertEqual(liked.preference, 1.0)
        self.assertEqual(liked.preference_label, "广州")
        self.assertGreater(liked.index, neutral.index)

    def test_preference_hometown(self):
        position = make_position(post_name="一级科员", headcount=2, work_place="广东省广州市")
        records = [record(2026, 130.0)]
        distributions = build_year_distributions(records)
        profile = make_profile(
            estimated_score=135, hukou_province="广东省", hometown_province="广东省", prefer_hometown=True
        )
        evaluation = evaluate_position(position, records, distributions, profile)
        self.assertEqual(evaluation.preference, 1.0)

    def test_barrier_boost(self):
        position = make_position(post_name="一级科员", headcount=2)
        records = [record(2026, 130.0)]
        distributions = build_year_distributions(records)
        outcome = MatchOutcome(
            position_id=position.id,
            status="符合",
            checks=[
                Check("性别", True, "性别满足（限男性）", "限男性"),
                Check("学历", True, "学历不限", "不限"),
                Check("专业", True, "专业精确匹配", "汉语言文学"),
            ],
        )
        with_barrier = evaluate_position(
            position, records, distributions, make_profile(estimated_score=135), outcome=outcome
        )
        without = evaluate_position(position, records, distributions, make_profile(estimated_score=135))
        self.assertGreater(with_barrier.barrier, 0)
        self.assertIn("性别限制", with_barrier.barrier_tags)
        self.assertNotIn("学历限制", with_barrier.barrier_tags)
        self.assertGreater(with_barrier.index, without.index)


if __name__ == "__main__":
    unittest.main()
