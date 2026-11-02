import tempfile
import unittest
from pathlib import Path

import openpyxl

from tests.support import (
    build_history,
    build_positions,
    make_profile,
    position_by_code,
    run_fixture,
    temp_dir,
)
from xuangang.ingest.history import HistorySpec
from xuangang.ingest.positions import PositionSpec
from xuangang.match.overrides import Override, append_override
from xuangang.pipeline import RunConfig, run
from xuangang.report.csv_output import write_csv_outputs
from xuangang.report.excel_report import write_workbook
from xuangang.report.html_report import write_html
from xuangang.report.text_report import write_summary


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir("pipeline-")
        self.root = Path(self.tmp.name)
        self.profile = make_profile()
        self.result = run_fixture(self.root, self.profile)

    def tearDown(self):
        self.tmp.cleanup()

    def test_positions_and_statuses(self):
        self.assertEqual(len(self.result.positions), 3)
        statuses = {position.post_code or position.post_name: self.result.outcomes[position.id].status for position in self.result.positions}
        self.assertEqual(statuses["100000000001"], "符合")
        self.assertEqual(statuses["100000000002"], "不符合")
        self.assertEqual(statuses["监管一级行政执法员"], "符合")

    def test_history_link_and_prediction(self):
        position = position_by_code(self.result, "100000000001")
        evaluation = self.result.evaluations[position.id]
        self.assertEqual([point.year for point in evaluation.history], [2026, 2025])
        self.assertAlmostEqual(evaluation.predicted, 129.56, places=2)
        self.assertEqual(evaluation.confidence, "中")

    def test_history_dedupe_and_unmatched(self):
        # 7 行里：1 行重复、1 行「未公布」被跳过，剩下 5 条有效记录
        self.assertEqual(len(self.result.records), 5)
        self.assertEqual(self.result.stats["links"]["unmatched"], 1)
        self.assertEqual(self.result.stats["links"]["code"], 2)  # A 的 2025/2026 两条

    def test_outputs(self):
        out = self.root / "out"
        write_csv_outputs(self.result, out)
        write_workbook(self.result, out / "report.xlsx", self.profile)
        write_html(self.result, out / "report.html", self.profile)
        write_summary(self.result, out / "summary.txt")
        for name in (
            "report.xlsx",
            "report.html",
            "summary.txt",
            "links.csv",
            "links_review.csv",
            "normalized/positions.csv",
            "normalized/history.csv",
            "issues.csv",
        ):
            self.assertTrue((out / name).exists(), name)
        workbook = openpyxl.load_workbook(out / "report.xlsx", read_only=True)
        self.assertIn("推荐岗位", workbook.sheetnames)
        self.assertIn("匹配链路", workbook.sheetnames)
        workbook.close()
        html = (out / "report.html").read_text(encoding="utf-8")
        self.assertIn("考公选岗", html)
        self.assertIn("100000000001", html)

    def test_manual_override(self):
        manual = self.root / "manual_links.csv"
        append_override(
            manual,
            Override(
                source="history.xlsx",
                year=2026,
                dept="测试水利局",
                post_name="办公室科员",
                position_id="2027-guokao-全国-100000000002",
                action="link",
                note="人工测试",
            ),
        )
        config = RunConfig(
            positions=[
                PositionSpec(
                    path=self.root / "positions.xlsx",
                    exam="guokao",
                    province="全国",
                    year=2027,
                    preset="guokao",
                )
            ],
            history=[
                HistorySpec(
                    path=self.root / "history.xlsx",
                    exam="guokao",
                    province="全国",
                    year=None,
                    kind="笔试最低进面分",
                    scale=200,
                )
            ],
            profile=self.profile,
            preset="guokao",
            manual_links=manual,
            out_dir=self.root / "out2",
        )
        result = run(config)
        manual_links = [link for link in result.links if link.link_type == "manual"]
        self.assertEqual(len(manual_links), 1)
        self.assertEqual(manual_links[0].position_id, "2027-guokao-全国-100000000002")
        self.assertTrue(manual_links[0].accepted)

    def test_warning_for_hardship(self):
        position = next(item for item in self.result.positions if item.post_name == "监管一级行政执法员")
        warnings = self.result.outcomes[position.id].warnings
        self.assertTrue(any("出差" in item for item in warnings))


if __name__ == "__main__":
    unittest.main()
