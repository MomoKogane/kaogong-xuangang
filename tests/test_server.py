import base64
import json
import threading
import unittest
import urllib.error
import urllib.request
from dataclasses import asdict
from http.server import ThreadingHTTPServer
from pathlib import Path

from tests.support import build_history, build_positions, make_profile, temp_dir
from xuangang.server import STATE, Handler


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = temp_dir("server-")
        root = Path(cls.tmp.name)
        cls.positions = build_positions(root / "positions.xlsx")
        cls.history = build_history(root / "history.xlsx")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        with STATE.lock:
            STATE.uploads.clear()
        STATE.last_result = None

    def request(self, method: str, path: str, data: dict | None = None):
        body = None
        headers = {}
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=body, headers=headers, method=method
        )
        return urllib.request.urlopen(request, timeout=60)

    def upload(self, path: Path, kind: str, meta: dict) -> dict:
        payload = {
            "kind": kind,
            "filename": path.name,
            "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
            "meta": meta,
        }
        with self.request("POST", "/api/upload", payload) as response:
            return json.loads(response.read().decode("utf-8"))

    def profile(self) -> dict:
        data = asdict(make_profile())
        data.pop("cert_objs", None)
        return data

    def test_full_flow(self):
        with self.request("GET", "/") as response:
            self.assertEqual(response.status, 200)
            self.assertIn("考公选岗", response.read().decode("utf-8"))

        position = self.upload(self.positions, "positions", {"exam": "guokao", "province": "全国", "year": 2027})
        self.assertTrue(position["ok"])
        self.assertEqual(position["inspect"]["total_rows"], 3)
        self.assertEqual(position["inspect"]["suggested"]["year"], 2027)
        history = self.upload(self.history, "history", {"exam": "guokao", "province": "全国"})
        self.assertTrue(history["ok"])
        self.assertEqual(history["inspect"]["suggested"]["year"], 2026)
        self.assertEqual(history["inspect"]["suggested"]["scale"], 200)

        files = [
            {"file_id": position["file_id"], "meta": {"exam": "guokao", "province": "全国", "year": 2027}},
            {"file_id": history["file_id"], "meta": {"exam": "guokao", "province": "全国", "year": 2026, "scale": 200}},
        ]
        with self.request("POST", "/api/analyze", {"profile": self.profile(), "files": files}) as response:
            data = json.loads(response.read().decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["stats"]["positions"], 3)
        self.assertEqual(len(data["rows"]), 3)
        self.assertIn("issues", data)

        with self.request("GET", "/api/report.xlsx") as response:
            blob = response.read()
            self.assertEqual(response.status, 200)
            self.assertTrue(blob.startswith(b"PK"))
        with self.request("GET", "/api/report.html") as response:
            html = response.read().decode("utf-8")
            self.assertIn("考公选岗", html)

        with self.request("GET", "/api/state") as response:
            state = json.loads(response.read().decode("utf-8"))
        self.assertTrue(state["has_run"])
        self.assertEqual(len(state["uploads"]), 2)

    def test_profile_endpoint(self):
        with self.request("GET", "/api/profile") as response:
            data = json.loads(response.read().decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertIn("profile", data)

    def test_positions_only(self):
        position = self.upload(self.positions, "positions", {"exam": "guokao", "province": "全国", "year": 2027})
        files = [{"file_id": position["file_id"], "meta": {"exam": "guokao", "province": "全国", "year": 2027}}]
        with self.request("POST", "/api/analyze", {"profile": self.profile(), "files": files}) as response:
            data = json.loads(response.read().decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["stats"]["records"], 0)
        self.assertEqual(data["stats"]["positions"], 3)

    def test_clear_kind(self):
        self.upload(self.positions, "positions", {"exam": "guokao"})
        with self.request("POST", "/api/clear", {"kind": "positions"}) as response:
            self.assertTrue(json.loads(response.read().decode("utf-8"))["ok"])
        self.assertEqual(STATE.by_kind("positions"), [])

    def test_sample_analyze(self):
        with self.request("POST", "/api/analyze", {"profile": self.profile(), "sample": True}) as response:
            data = json.loads(response.read().decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertGreaterEqual(data["stats"]["positions"], 10)

    def test_preferences_in_payload(self):
        position = self.upload(self.positions, "positions", {"exam": "guokao", "province": "全国", "year": 2027})
        history = self.upload(self.history, "history", {"exam": "guokao", "province": "全国", "year": 2026, "scale": 200})
        files = [
            {"file_id": position["file_id"], "meta": {"exam": "guokao", "province": "全国", "year": 2027}},
            {"file_id": history["file_id"], "meta": {"exam": "guokao", "province": "全国", "year": 2026, "scale": 200}},
        ]
        profile = self.profile()
        profile["preferred_regions"] = ["测试"]
        with self.request("POST", "/api/analyze", {"profile": profile, "files": files}) as response:
            data = json.loads(response.read().decode("utf-8"))
        self.assertTrue(any(row["advantage_tags"] for row in data["rows"]))
        self.assertTrue(any(row["preference"] == 1 for row in data["rows"]))

    def test_xls_upload(self):
        legacy = Path(__file__).resolve().parent / "fixtures" / "legacy_biff8.xls"
        position = self.upload(legacy, "positions", {"exam": "guokao", "province": "全国", "year": 2027})
        self.assertTrue(position["ok"])
        self.assertEqual(position["inspect"]["total_rows"], 6)
        files = [{"file_id": position["file_id"], "meta": {"exam": "guokao", "province": "全国", "year": 2027}}]
        with self.request("POST", "/api/analyze", {"profile": self.profile(), "files": files}) as response:
            data = json.loads(response.read().decode("utf-8"))
        self.assertEqual(data["stats"]["positions"], 6)

    def test_analyze_requires_uploads(self):
        try:
            with self.request("POST", "/api/analyze", {"profile": {}, "files": []}):
                self.fail("应该返回错误")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)


if __name__ == "__main__":
    unittest.main()
