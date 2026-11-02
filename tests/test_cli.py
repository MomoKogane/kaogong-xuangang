import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests.support import build_history, build_positions, temp_dir
from xuangang.cli import main

PROJECT = Path(__file__).resolve().parent.parent


class CliTest(unittest.TestCase):
    def test_init_creates_templates(self):
        with temp_dir() as tmp:
            self.assertEqual(main(["init", "--dir", tmp]), 0)
            self.assertTrue((Path(tmp) / "config" / "bob.toml").exists())
            self.assertTrue((Path(tmp) / "data" / "manifest.toml").exists())
            self.assertTrue((Path(tmp) / "data" / "manual_links.csv").exists())

    def test_import_inspect(self):
        with temp_dir() as tmp:
            path = build_positions(Path(tmp) / "positions.xlsx")
            buffer = io.StringIO()
            with redirect_stdout(buffer), redirect_stderr(buffer):
                code = main(["import", str(path), "--kind", "positions"])
            self.assertEqual(code, 0)
            self.assertIn("表头", buffer.getvalue())
            self.assertIn("专业", buffer.getvalue())

    def test_import_inspect_xls(self):
        path = PROJECT / "tests" / "fixtures" / "legacy_biff8.xls"
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            code = main(["import", str(path), "--kind", "positions"])
        self.assertEqual(code, 0)
        self.assertIn("表头", buffer.getvalue())

    def test_doctor(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            code = main(["doctor"])
        self.assertEqual(code, 0)
        self.assertIn("pandas", buffer.getvalue())

    def test_run_sample(self):
        with temp_dir() as tmp:
            out = Path(tmp) / "out"
            buffer = io.StringIO()
            with redirect_stdout(buffer), redirect_stderr(buffer):
                code = main(
                    [
                        "run",
                        "--config", "data/sample/bob.toml",
                        "--positions", "data/sample/positions",
                        "--history", "data/sample/history",
                        "--out", str(out),
                        "--preset", "guokao",
                        "--exam", "guokao",
                        "--year", "2027",
                    ]
                )
            self.assertEqual(code, 0, buffer.getvalue())
            self.assertTrue((out / "report.xlsx").exists())
            self.assertTrue((out / "report.html").exists())
            self.assertIn("输出目录", buffer.getvalue())

    def test_missing_config(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            code = main(
                [
                    "run",
                    "--config", "config/不存在.toml",
                    "--positions", "data/sample/positions",
                    "--history", "data/sample/history",
                    "--out", "out/should-not-run",
                ]
            )
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
