import tempfile
import unittest
from pathlib import Path

from tests.support import make_position, temp_dir
from xuangang.match.linker import LinkOptions, link_records
from xuangang.match.overrides import Override, append_override, lookup_override, load_overrides
from xuangang.models import ScoreRecord


def make_record(**overrides) -> ScoreRecord:
    data = {
        "year": 2026,
        "exam": "guokao",
        "province": "全国",
        "source": "2026国考进面分数.xlsx",
        "sheet": "进面分数",
        "row": overrides.pop("row", 2),
        "dept": "A局",
        "unit": "U1",
        "post_name": "一级科员",
        "post_code": "",
        "min_score": 130.0,
    }
    data.update(overrides)
    return ScoreRecord(**data)


class LinkerTest(unittest.TestCase):
    def build(self):
        positions = [
            make_position(id="p1", post_code="111", dept="A局", unit="U1", post_name="一级科员"),
            make_position(id="p2", post_code="222", dept="A局", unit="U2", post_name="二级科员"),
            make_position(id="p3", post_code="", dept="B局", unit="", post_name="监管员"),
        ]
        return positions

    def test_code_link(self):
        positions = self.build()
        record = make_record(post_code="111", dept="", unit="", post_name="")
        links, stats = link_records(positions, [record])
        self.assertEqual(links[0].position_id, "p1")
        self.assertEqual(links[0].link_type, "code")
        self.assertTrue(links[0].accepted)
        self.assertEqual(stats.code, 1)

    def test_exact_link(self):
        positions = self.build()
        record = make_record(dept="A局", unit="U2", post_name="二级科员", post_code="")
        links, _ = link_records(positions, [record])
        self.assertEqual(links[0].position_id, "p2")
        self.assertEqual(links[0].link_type, "exact")
        self.assertTrue(links[0].accepted)

    def test_missing_unit_fuzzy(self):
        positions = self.build()
        record = make_record(dept="A局", unit="", post_name="一级科员", post_code="")
        links, _ = link_records(positions, [record])
        self.assertEqual(links[0].position_id, "p1")
        self.assertTrue(links[0].accepted)

    def test_ambiguous_review(self):
        positions = self.build() + [
            make_position(id="p1b", post_code="333", dept="A局", unit="U1", post_name="一级科员")
        ]
        record = make_record(dept="A局", unit="", post_name="一级科员", post_code="", row=9)
        links, stats = link_records(positions, [record])
        self.assertFalse(links[0].accepted)
        self.assertEqual(links[0].link_type, "fuzzy")
        self.assertEqual(stats.review, 1)

    def test_unmatched(self):
        positions = self.build()
        record = make_record(dept="C局", unit="", post_name="完全不存在", post_code="")
        links, stats = link_records(positions, [record])
        self.assertEqual(links[0].position_id, "")
        self.assertEqual(stats.unmatched, 1)

    def test_missing_department(self):
        positions = self.build()
        record = make_record(dept="", unit="", post_name="监管员", post_code="")
        links, _ = link_records(positions, [record])
        self.assertEqual(links[0].position_id, "p3")
        self.assertFalse(links[0].accepted)

    def test_manual_override_priority(self):
        positions = self.build()
        record = make_record(dept="A局", unit="U1", post_name="完全不同的名字", post_code="")
        with temp_dir() as tmp:
            path = Path(tmp) / "manual_links.csv"
            append_override(
                path,
                Override(
                    source="2026国考进面分数.xlsx",
                    year=2026,
                    dept="A局",
                    post_name="完全不同的名字",
                    position_id="p2",
                    action="link",
                    note="测试",
                ),
            )
            overrides = load_overrides(path)
            self.assertIsNotNone(
                lookup_override(overrides, "2026国考进面分数.xlsx", 2026, "A局", "完全不同的名字")
            )
            links, stats = link_records(positions, [record], overrides)
        self.assertEqual(links[0].position_id, "p2")
        self.assertEqual(links[0].link_type, "manual")
        self.assertTrue(links[0].accepted)
        self.assertEqual(stats.manual, 1)

    def test_manual_ignore(self):
        positions = self.build()
        record = make_record(post_code="111")
        with temp_dir() as tmp:
            path = Path(tmp) / "manual_links.csv"
            append_override(
                path,
                Override(
                    source="2026国考进面分数.xlsx",
                    year=2026,
                    dept="",
                    post_name="一级科员",
                    position_id="",
                    action="ignore",
                ),
            )
            overrides = load_overrides(path)
            links, _ = link_records(positions, [record], overrides)
        self.assertEqual(links[0].position_id, "")
        self.assertIn("忽略", links[0].note)


if __name__ == "__main__":
    unittest.main()
