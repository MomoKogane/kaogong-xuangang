"""本地网页服务：标准库 http.server，无第三方依赖，只监听 127.0.0.1。

网页端是主推用法：上传两张表 → 自动识别年份/分数制式/列名 → 填条件 → 出报告。
不需要手写 manifest，也不需要编辑 config。
"""

from __future__ import annotations

import base64
import json
import re
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .config import (
    default_preset,
    load_manifest,
    load_profile,
    profile_from_dict,
    project_root,
)
from .ingest.history import HistorySpec
from .ingest.inspect import inspect_file
from .ingest.positions import PositionSpec
from .pipeline import RunConfig, run
from .report.common import payload as report_payload
from .report.csv_output import write_csv_outputs
from .report.excel_report import write_workbook
from .report.html_report import write_html
from .report.text_report import write_summary

MAX_BODY = 64 * 1024 * 1024
WEB_DIR = Path(__file__).resolve().parent / "web"
SAFE_NAME = re.compile(r"[^\w\u4e00-\u9fa5.\-()（）\s]")
SUPPORTED = {".xlsx", ".xlsm", ".xls", ".csv"}


@dataclass
class Upload:
    file_id: str
    path: Path
    name: str
    kind: str
    meta: dict = field(default_factory=dict)


@dataclass
class AppState:
    uploads: list[Upload] = field(default_factory=list)
    last_result: object | None = None
    last_dir: Path | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def by_kind(self, kind: str) -> list[Upload]:
        return [item for item in self.uploads if item.kind == kind]

    def find(self, file_id: str) -> Upload | None:
        for item in self.uploads:
            if item.file_id == file_id:
                return item
        return None


STATE = AppState()


def serve(port: int = 8765, run_dir: Path | None = None, open_browser: bool = True) -> int:
    root = project_root()
    (root / "data" / "imported").mkdir(parents=True, exist_ok=True)
    if run_dir is not None and Path(run_dir).exists():
        STATE.last_dir = Path(run_dir)

    server: ThreadingHTTPServer | None = None
    chosen_port = port
    for offset in range(10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port + offset), Handler)
            chosen_port = port + offset
            break
        except OSError:
            continue
    if server is None:
        raise OSError(f"端口 {port}~{port + 9} 都被占用，换一个 --port 试试")

    url = f"http://127.0.0.1:{chosen_port}/"
    print("=" * 56)
    print("  考公选岗已启动")
    print(f"  浏览器打开：{url}")
    print("  关闭这个窗口即可停止服务。")
    print("=" * 56)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    return 0


class Handler(BaseHTTPRequestHandler):
    server_version = "xuangang/0.2"
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A003 - 保持简洁
        pass

    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _error(self, status: int, message: str):
        self._json(status, {"ok": False, "error": message})

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("上传内容过大（上限 64MB），请拆分文件")
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"请求体不是合法 JSON：{exc}") from exc

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self._serve_file(WEB_DIR / "index.html")
            return
        if path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return
        if path == "/api/state":
            self._api_state()
            return
        if path == "/api/profile":
            self._api_profile()
            return
        if path == "/api/report.xlsx":
            self._serve_run_file("report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            return
        if path == "/api/report.html":
            self._serve_run_file("report.html", "text/html; charset=utf-8")
            return
        if path == "/api/summary.txt":
            self._serve_run_file("summary.txt", "text/plain; charset=utf-8")
            return
        self._error(404, "没有这个页面")

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/upload":
                self._api_upload()
            elif path == "/api/analyze":
                self._api_analyze()
            elif path == "/api/clear":
                self._api_clear()
            elif path == "/api/reset":
                with STATE.lock:
                    STATE.uploads.clear()
                self._json(200, {"ok": True})
            else:
                self._error(404, "没有这个接口")
        except (ValueError, FileNotFoundError) as exc:
            self._error(400, str(exc))
        except Exception as exc:  # noqa: BLE001 - 本地工具，错误直接显示
            self._error(500, f"处理失败：{exc}")

    # ---------- 接口实现 ----------

    def _api_state(self):
        result = STATE.last_result
        stats = result.stats if result is not None else None
        self._json(
            200,
            {
                "ok": True,
                "has_run": result is not None,
                "stats": stats,
                "run_dir": str(STATE.last_dir) if STATE.last_dir else "",
                "uploads": [
                    {"file_id": item.file_id, "name": item.name, "kind": item.kind, "meta": item.meta}
                    for item in STATE.uploads
                ],
            },
        )

    def _api_profile(self):
        path = project_root() / "config" / "bob.toml"
        data: dict = {}
        if path.exists():
            try:
                profile = load_profile(path)
                data = asdict(profile)
                data.pop("cert_objs", None)
            except Exception:  # noqa: BLE001 - 配置坏了也要能打开网页
                data = {}
        self._json(200, {"ok": True, "profile": data, "has_config": path.exists()})

    def _api_clear(self):
        data = self._read_body()
        kind = data.get("kind")
        with STATE.lock:
            if kind in {"positions", "history"}:
                STATE.uploads = [item for item in STATE.uploads if item.kind != kind]
            else:
                STATE.uploads.clear()
        self._json(200, {"ok": True})

    def _api_upload(self):
        data = self._read_body()
        kind = data.get("kind")
        if kind not in {"positions", "history"}:
            raise ValueError("kind 必须是 positions 或 history")
        filename = SAFE_NAME.sub("_", Path(str(data.get("filename") or "upload.xlsx")).name).strip() or "upload.xlsx"
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED:
            raise ValueError("只支持 .xlsx / .xlsm / .xls / .csv 文件")
        content = data.get("content_base64") or ""
        if content.startswith("data:"):
            content = content.split(",", 1)[-1]
        try:
            blob = base64.b64decode(content)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"文件内容解码失败：{exc}") from exc
        if not blob:
            raise ValueError("文件内容为空")

        meta = data.get("meta") or {}
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
        folder = project_root() / "data" / "imported" / stamp
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / filename
        path.write_bytes(blob)
        file_id = f"{stamp}/{filename}"

        inspection: dict = {"ok": False, "warnings": []}
        try:
            inspection = inspect_file(
                path,
                kind,
                default_exam=str(meta.get("exam") or "guokao"),
                default_province=str(meta.get("province") or ""),
                default_year=int(meta["year"]) if meta.get("year") else None,
            )
        except Exception as exc:  # noqa: BLE001 - 识别失败不影响上传
            inspection["warnings"] = [f"自动识别失败：{exc}"]

        with STATE.lock:
            STATE.uploads = [
                item for item in STATE.uploads if not (item.kind == kind and item.name == filename)
            ]
            STATE.uploads.append(Upload(file_id=file_id, path=path, name=filename, kind=kind, meta=meta))
        self._json(
            200,
            {
                "ok": True,
                "file_id": file_id,
                "name": filename,
                "kind": kind,
                "meta": meta,
                "inspect": inspection,
            },
        )

    def _api_analyze(self):
        data = self._read_body()
        profile_data = data.get("profile") or {}
        profile = profile_from_dict(profile_data)
        if not profile.target_year:
            profile.target_year = 2027
        exam = profile.exam or "guokao"
        province = profile.province or ("全国" if exam == "guokao" else "")
        preset_name = default_preset(exam, province)

        if data.get("sample"):
            position_specs, history_specs = _sample_specs(exam, province, preset_name)
        else:
            files = data.get("files")
            if files is not None:
                selected: list[tuple[Upload, dict]] = []
                with STATE.lock:
                    for item in files:
                        upload = STATE.find(str(item.get("file_id") or ""))
                        if upload is None:
                            continue
                        selected.append((upload, item.get("meta") or {}))
            else:
                with STATE.lock:
                    selected = [(upload, upload.meta or {}) for upload in STATE.uploads]
            positions = [(upload, meta) for upload, meta in selected if upload.kind == "positions"]
            histories = [(upload, meta) for upload, meta in selected if upload.kind == "history"]
            if not positions:
                raise ValueError("还没有上传岗位表")

            position_specs = []
            for upload, meta in positions:
                position_specs.append(
                    PositionSpec(
                        path=upload.path,
                        exam=str(meta.get("exam") or exam),
                        province=str(meta.get("province") or province),
                        year=int(meta.get("year") or profile.target_year),
                        preset=str(meta.get("preset") or preset_name),
                        sheet_filter=[meta["sheet"]] if meta.get("sheet") else None,
                    )
                )
            history_specs = []
            for upload, meta in histories:
                history_specs.append(
                    HistorySpec(
                        path=upload.path,
                        exam=str(meta.get("exam") or exam),
                        province=str(meta.get("province") or province),
                        year=int(meta["year"]) if meta.get("year") else None,
                        kind=str(meta.get("kind") or "笔试最低进面分"),
                        scale=int(meta["scale"]) if meta.get("scale") else None,
                        preset=str(meta.get("preset") or preset_name),
                    )
                )

        out_dir = project_root() / "out" / "server_run"
        config = RunConfig(
            positions=position_specs,
            history=history_specs,
            profile=profile,
            preset=preset_name,
            manual_links=project_root() / "data" / "manual_links.csv",
            out_dir=out_dir,
        )

        with STATE.lock:
            result = run(config)
            write_csv_outputs(result, out_dir)
            write_summary(result, out_dir / "summary.txt", top=15)
            write_html(result, out_dir / "report.html", profile)
            write_workbook(result, out_dir / "report.xlsx", profile)
            STATE.last_result = result
            STATE.last_dir = out_dir

        report = report_payload(result)
        rows = report["rows"]
        issues = [
            issue.to_dict()
            for issue in result.issues
            if issue.level in {"warn", "error"}
        ][:40]
        self._json(
            200,
            {
                "ok": True,
                "stats": result.stats,
                "profile": report["profile"],
                "rows": rows[:3000],
                "truncated": len(rows) > 3000,
                "run_dir": str(out_dir),
                "issues": issues,
                "issues_total": len(result.issues),
            },
        )

    def _serve_run_file(self, name: str, content_type: str):
        if STATE.last_dir is None:
            self._error(404, "还没有生成报告")
            return
        path = (STATE.last_dir / name).resolve()
        try:
            path.relative_to(STATE.last_dir.resolve())
        except ValueError:
            self._error(400, "非法路径")
            return
        self._serve_file(path, content_type)

    def _serve_file(self, path: Path, content_type: str | None = None):
        path = Path(path)
        if not path.is_file():
            self._error(404, "文件不存在")
            return
        content_type = content_type or {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".txt": "text/plain; charset=utf-8",
        }.get(path.suffix.lower(), "application/octet-stream")
        self._send(200, path.read_bytes(), content_type)


def _sample_specs(exam: str, province: str, preset_name: str) -> tuple[list[PositionSpec], list[HistorySpec]]:
    root = project_root()
    manifest_path = root / "data" / "sample" / "manifest.toml"
    if not manifest_path.exists():
        raise FileNotFoundError("示例数据不存在：data/sample/manifest.toml")
    manifest = load_manifest(manifest_path)
    position_specs: list[PositionSpec] = []
    history_specs: list[HistorySpec] = []
    for entry in manifest.get("positions") or []:
        if entry.get("exam") != exam:
            continue
        path = root / str(entry["file"])
        if path.exists():
            position_specs.append(
                PositionSpec(
                    path=path,
                    exam=str(entry.get("exam") or exam),
                    province=str(entry.get("province") or province),
                    year=int(entry.get("year") or 2027),
                    preset=str(entry.get("preset") or preset_name),
                )
            )
    for entry in manifest.get("history") or []:
        if entry.get("exam") != exam:
            continue
        path = root / str(entry["file"])
        if path.exists():
            history_specs.append(
                HistorySpec(
                    path=path,
                    exam=str(entry.get("exam") or exam),
                    province=str(entry.get("province") or province),
                    year=int(entry.get("year")) if entry.get("year") else None,
                    kind=str(entry.get("kind") or "笔试最低进面分"),
                    scale=int(entry["scale"]) if entry.get("scale") else None,
                    preset=str(entry.get("preset") or preset_name),
                )
            )
    if not position_specs:
        raise FileNotFoundError(f"示例数据里没有 {exam} 的岗位表，先切换考试类型再试")
    return position_specs, history_specs
