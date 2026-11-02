"""命令行入口：init / doctor / import / run / links / serve。"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import __version__
from .config import (
    PROFILE_TEMPLATE,
    available_presets,
    default_preset,
    load_manifest,
    load_preset,
    load_profile,
    project_root,
    write_profile_template,
)
from .ingest.columns import FIELD_DISPLAY
from .ingest.excel import read_table
from .ingest.history import HistorySpec
from .ingest.positions import PositionSpec, build_mapper
from .match.overrides import ensure_override_file
from .models import Profile
from .pipeline import RunConfig, run, summarize_text

SUPPORTED_SUFFIXES = {".xlsx", ".xlsm", ".xls", ".csv"}

MANIFEST_TEMPLATE = """# 数据清单：声明每个文件属于哪场考试、哪一年、什么分数制式。
# 相对路径以项目根目录为准。没有声明的文件也可以用命令行参数临时指定。

# ---- 岗位表（当年要报考的岗位）----
# [[positions]]
# file = "data/incoming/positions/2027国考职位表.xlsx"
# exam = "guokao"
# province = "全国"
# year = 2027
# preset = "guokao"
# sheet = ""                      # 可选：只读指定 sheet

# ---- 往年进面分数线（民间整理也放这里）----
# [[history]]
# file = "data/incoming/history/2026国考进面分数线.xlsx"
# exam = "guokao"
# province = "全国"
# year = 2026
# kind = "笔试最低进面分"          # 笔试最低进面分 | 综合成绩 | 面试成绩
# scale = 200                    # 100 | 150 | 200 | 300

# ---- 省考示例 ----
# [[positions]]
# file = "data/incoming/positions/2026广东省考职位表.xlsx"
# exam = "shengkao"
# province = "广东省"
# year = 2026
# preset = "guangdong"
#
# [[history]]
# file = "data/incoming/history/2025广东省考进面分数.xlsx"
# exam = "shengkao"
# province = "广东省"
# year = 2025
# kind = "笔试最低进面分"
# scale = 300
"""

NOTES_TEMPLATE = """# 自定义备注抽取规则（可选）。
# 内置规则在 xuangang/rules/notes.py；这里追加的规则会一起生效。
# dimension 可取：gender / politics / ethnicity / hukou / grassroots / projects /
#                cert / school / age / special / service / warning
# kind 取 hard（硬条件）或 soft（只提醒）。
#
# [[rule]]
# id = "custom_cert"
# dimension = "cert"
# kind = "hard"
# pattern = "具有(X)证书"
# group = 1
# message = "自定义证书要求"
"""

SCORING_TEMPLATE = """# 评分与分档参数（可选覆盖，删掉即用默认值）

[history]
max_years = 3
weights = [0.5, 0.3, 0.2]

[tiers]
bao = 10.0       # 预估分 - 预测分 >= 10 -> 保
wen = 4.0        # >= 4 -> 稳
chong = 0.0      # >= 0 -> 冲，< 0 -> 风险

[weights]
fit = 45.0        # 分数适配
heat = 20.0       # 竞争热度（越低越好）
capacity = 15.0   # 招录容量
preference = 10.0 # 意向地区
barrier = 10.0    # 岗位限制对你形成的竞争壁垒

[capacity]
headcount_full = 5.0
interview_full = 15.0
headcount_weight = 0.7

[heat_percentile]
high = 0.75
medium = 0.5

[preference]
neutral = 0.5     # 没填意向地区时给中性分

[barrier]
"性别" = 1.0
"民族" = 1.0
"特殊身份" = 1.0
"户籍" = 0.8
"基层经验" = 0.8
"执业资格" = 0.6
"政治面貌" = 0.5
"应届" = 0.5
"专业" = 0.4
"学历" = 0.3
"学位" = 0.2
"""


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover - 某些环境没有 reconfigure
        pass

    parser = build_parser()
    args = parser.parse_args(argv)
    handler = {
        "init": cmd_init,
        "doctor": cmd_doctor,
        "import": cmd_import,
        "run": cmd_run,
        "links": cmd_links,
        "serve": cmd_serve,
    }[args.command]
    try:
        return handler(args)
    except KeyboardInterrupt:
        return 130
    except (FileNotFoundError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"文件访问错误：{exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xuangang",
        description="考公选岗：按个人条件与往年进面分数线筛选公务员岗位。",
    )
    parser.add_argument("--version", action="version", version=f"xuangang {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="生成配置模板与目录骨架")
    init.add_argument("--dir", default=".", help="项目目录（默认当前目录）")
    init.add_argument("--force", action="store_true", help="覆盖已有的配置文件")

    doctor = sub.add_parser("doctor", help="环境与数据文件自检")
    doctor.add_argument("--dir", default=".", help="项目目录")

    imp = sub.add_parser("import", help="诊断文件表头/列映射（只读，不写文件）")
    imp.add_argument("path", help="岗位表或分数线文件/目录")
    imp.add_argument("--kind", choices=["positions", "history"], default="positions")
    imp.add_argument("--preset", default=None, help="列别名预设（默认按考试类型）")
    imp.add_argument("--exam", default="guokao")
    imp.add_argument("--province", default="")
    imp.add_argument("--year", type=int, default=None)
    imp.add_argument("--sheet", default=None, help="只看指定 sheet")

    runp = sub.add_parser("run", help="读取数据、筛选、评分并生成报告")
    runp.add_argument("--config", default="config/bob.toml", help="个人条件 TOML")
    runp.add_argument("--manifest", default=None, help="数据清单 TOML（默认 data/manifest.toml）")
    runp.add_argument("--positions", nargs="+", default=None, help="岗位表文件或目录")
    runp.add_argument("--history", nargs="+", default=None, help="分数线文件或目录")
    runp.add_argument("--out", default=None, help="输出目录（默认 out/<年份>）")
    runp.add_argument("--preset", default=None)
    runp.add_argument("--exam", default=None)
    runp.add_argument("--province", default=None)
    runp.add_argument("--year", type=int, default=None)
    runp.add_argument("--history-year", type=int, default=None)
    runp.add_argument("--history-scale", type=int, default=None, choices=[100, 150, 200, 300])
    runp.add_argument("--history-kind", default=None)
    runp.add_argument("--estimated-score", type=float, default=None, help="预估笔试分（覆盖配置）")
    runp.add_argument("--score-scale", type=int, default=None, choices=[100, 150, 200, 300], help="预估分满分")
    runp.add_argument("--preferred-regions", default=None, help="意向工作地区，逗号分隔，如 广州,深圳")
    runp.add_argument("--prefer-hometown", action="store_true", help="把户籍/生源省份也作为意向地区")
    runp.add_argument("--major-catalog", default=None, help="自定义专业目录（xlsx/csv）")
    runp.add_argument("--manual-links", default=None, help="人工对应表 CSV")
    runp.add_argument("--top", type=int, default=0, help="终端只显示前 N 个（0=全部）")
    runp.add_argument("--no-xlsx", action="store_true")
    runp.add_argument("--no-html", action="store_true")

    links = sub.add_parser("links", help="查看待人工核对的分数线匹配")
    links.add_argument("--out", default=None, help="运行输出目录（默认 out 下最新）")
    links.add_argument("--limit", type=int, default=50)

    serve = sub.add_parser("serve", help="启动本地网页界面（仅 127.0.0.1）")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--run-dir", default=None, help="已有运行结果目录（可选）")
    serve.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    return parser


def cmd_init(args) -> int:
    root = Path(args.dir).resolve()
    for relative in (
        "config/presets",
        "data/incoming/positions",
        "data/incoming/history",
        "data/imported",
        "out",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    profile_path = root / "config" / "bob.toml"
    if profile_path.exists() and not args.force:
        print(f"保留已有配置：{profile_path}")
    else:
        profile_path.write_text(PROFILE_TEMPLATE, encoding="utf-8")
        print(f"已生成个人条件模板：{profile_path}")
    manifest_path = root / "data" / "manifest.toml"
    if not manifest_path.exists() or args.force:
        manifest_path.write_text(MANIFEST_TEMPLATE, encoding="utf-8")
        print(f"已生成数据清单模板：{manifest_path}")
    else:
        print(f"保留已有清单：{manifest_path}")
    manual_path = root / "data" / "manual_links.csv"
    ensure_override_file(manual_path)
    print(f"人工对应表：{manual_path}")
    notes_path = root / "config" / "notes_patterns.toml"
    if not notes_path.exists() or args.force:
        notes_path.write_text(NOTES_TEMPLATE, encoding="utf-8")
        print(f"自定义备注规则（可选）：{notes_path}")
    scoring_path = root / "config" / "scoring.toml"
    if not scoring_path.exists() or args.force:
        scoring_path.write_text(SCORING_TEMPLATE, encoding="utf-8")
        print(f"评分参数：{scoring_path}")
    print("")
    print("下一步：")
    print("  1. 把岗位表放进 data/incoming/positions/，分数线放进 data/incoming/history/")
    print("  2. 在 data/manifest.toml 里为每个文件声明年份/考试/分数制式")
    print("  3. 编辑 config/bob.toml 填写个人条件")
    print("  4. 运行： .\\run.cmd run --config config\\bob.toml --positions data\\incoming\\positions --history data\\incoming\\history")
    return 0


def cmd_doctor(args) -> int:
    root = Path(args.dir).resolve()
    print("== 环境 ==")
    print(f"Python {sys.version.split()[0]}")
    try:
        import pandas
        import openpyxl
        import xlsxwriter

        print(f"pandas {pandas.__version__} / openpyxl {openpyxl.__version__} / xlsxwriter {xlsxwriter.__version__}")
    except ImportError as exc:
        print(f"缺少依赖：{exc}")
        print("请安装：pip install pandas openpyxl XlsxWriter")
        return 1

    print("")
    print("== 项目 ==")
    profile_path = root / "config" / "bob.toml"
    print(f"个人条件：{profile_path} {'（存在）' if profile_path.exists() else '（缺失，先运行 init）'}")
    manifest = load_manifest(root / "data" / "manifest.toml") if (root / "data" / "manifest.toml").exists() else {}
    history_entries = manifest.get("history") or []
    position_entries = manifest.get("positions") or []
    print(f"manifest：岗位表 {len(position_entries)} 条，分数线 {len(history_entries)} 条")

    print("")
    print("== 数据文件 ==")
    files = _collect_manifest_files(root, manifest)
    extra = []
    for folder in ("data/incoming/positions", "data/incoming/history"):
        folder_path = root / folder
        if folder_path.is_dir():
            extra.extend(sorted(folder_path.glob("*.xlsx")))
            extra.extend(sorted(folder_path.glob("*.xlsm")))
            extra.extend(sorted(folder_path.glob("*.xls")))
            extra.extend(sorted(folder_path.glob("*.csv")))
    seen = set()
    for path in files + extra:
        if path in seen:
            continue
        seen.add(path)
        if not path.exists():
            print(f"[缺失] {path}")
            continue
        try:
            sheets = read_table(path)
            print(f"[OK] {path.name}：{len(sheets)} 个 sheet（{', '.join(sheet.name for sheet in sheets[:4])}）")
        except Exception as exc:  # noqa: BLE001 - doctor 要尽量报告问题
            print(f"[错误] {path.name}：{exc}")
    if not seen:
        print("data/incoming/ 下还没有文件。")
    print("")
    print("提示：列名对不上时用 .\\run.cmd import --inspect <文件> 诊断。")
    return 0


def _collect_manifest_files(root: Path, manifest: dict) -> list[Path]:
    files: list[Path] = []
    for section in ("positions", "history"):
        for entry in manifest.get(section) or []:
            value = entry.get("file")
            if not value:
                continue
            path = Path(value)
            if not path.is_absolute():
                path = root / path
            files.append(path)
    return files


def cmd_import(args) -> int:
    preset_name = args.preset or (args.exam or "guokao")
    preset = load_preset(preset_name)
    section = "positions" if args.kind == "positions" else "history"
    mapper = build_mapper(preset, section)
    path = Path(args.path)
    files = _expand_files([path])
    if not files:
        print(f"没有找到可读的表格文件：{path}")
        return 2
    print(f"预设：{preset.get('meta', {}).get('display_name', preset_name)}（{section}）")
    for file in files:
        print("")
        print(f"== {file} ==")
        try:
            sheets = read_table(file)
        except (ValueError, OSError) as exc:
            print(f"  读取失败：{exc}")
            continue
        for sheet in sheets:
            if args.sheet and sheet.name != args.sheet:
                continue
            header = mapper.detect_header(sheet.rows)
            if header is None:
                print(f"  [{sheet.name}] 没有识别出表头（前 {len(sheet.rows)} 行）")
                preview = sheet.rows[0][:12] if sheet.rows else []
                print(f"    首行预览：{preview}")
                continue
            print(f"  [{sheet.name}] 表头在第 {header.header_row + 1} 行")
            for field, indexes in header.mapping.items():
                column_names = []
                for index in indexes:
                    name = header.headers[index] if index < len(header.headers) else "?"
                    column_names.append(f"{name}")
                confidence = header.mapping_confidence.get(field, 0)
                print(
                    f"    {FIELD_DISPLAY.get(field, field):<12} <- {'、'.join(column_names)}"
                    f"（{confidence:.2f}）"
                )
            if header.missing_required:
                print(
                    "    缺少必填列："
                    + "、".join(FIELD_DISPLAY.get(item, item) for item in header.missing_required)
                )
            if header.unknown:
                print("    未识别列：" + "、".join(header.unknown[:15]))
            print(f"    数据行约 {max(0, len(sheet.rows) - header.header_row - 1)} 行")
            print("    可复制到 config/presets/*.toml 的片段：")
            print("    [%s.fields]" % section)
            for field, indexes in header.mapping.items():
                names = [header.headers[index] for index in indexes if index < len(header.headers)]
                print(f'    {field} = {_toml_list(names)}')
    return 0


def _toml_list(items: list[str]) -> str:
    escaped = ", ".join('"' + str(item).replace('"', '\\"') + '"' for item in items)
    return f"[{escaped}]"


def _expand_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        path = Path(path)
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_file() and child.suffix.lower() in SUPPORTED_SUFFIXES:
                    files.append(child)
        elif path.is_file():
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                raise ValueError(f"不支持的文件类型：{path}（支持 .xlsx / .xlsm / .xls / .csv）")
            files.append(path)
        else:
            raise FileNotFoundError(f"路径不存在：{path}")
    deduped: list[Path] = []
    for item in files:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _profile_from_args(args) -> Profile:
    profile_path = Path(args.config)
    if not profile_path.is_absolute():
        profile_path = project_root() / profile_path
    if not profile_path.exists():
        raise FileNotFoundError(
            f"个人条件文件不存在：{profile_path}\n先运行： .\\run.cmd init，然后编辑 config/bob.toml"
        )
    return load_profile(profile_path)


def cmd_run(args) -> int:
    root = project_root()
    profile = _profile_from_args(args)
    if args.exam:
        profile.exam = args.exam
    if args.province:
        profile.province = args.province
    if args.year:
        profile.target_year = args.year
    if args.estimated_score is not None:
        profile.estimated_score = args.estimated_score
    if args.score_scale:
        profile.score_scale = args.score_scale
    if args.preferred_regions:
        profile.preferred_regions = [
            item.strip() for item in re.split(r"[,，、]", args.preferred_regions) if item.strip()
        ]
    if args.prefer_hometown:
        profile.prefer_hometown = True
    exam = profile.exam or "guokao"
    province = profile.province or ("全国" if exam == "guokao" else "")
    year = int(profile.target_year or 2027)
    preset = args.preset or default_preset(exam, province)

    manifest = load_manifest(root / "data" / "manifest.toml") if (root / "data" / "manifest.toml").exists() else {}
    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.is_absolute():
            manifest_path = root / manifest_path
        if not manifest_path.exists():
            raise FileNotFoundError(f"数据清单不存在：{manifest_path}")
        manifest = load_manifest(manifest_path)

    position_paths = _expand_files([Path(item) for item in args.positions]) if args.positions else []
    if not position_paths:
        position_paths = _manifest_files(root, manifest, "positions", exam)
    if not position_paths:
        raise FileNotFoundError("没有岗位表：用 --positions 指定，或在 data/manifest.toml 里声明")

    history_paths = _expand_files([Path(item) for item in args.history]) if args.history else []
    if not history_paths:
        history_paths = _manifest_files(root, manifest, "history", exam)
    if not history_paths:
        raise FileNotFoundError("没有分数线文件：用 --history 指定，或在 data/manifest.toml 里声明")

    manifest_positions = {Path(entry["file"]).name: entry for entry in manifest.get("positions") or [] if entry.get("file")}
    manifest_history = {Path(entry["file"]).name: entry for entry in manifest.get("history") or [] if entry.get("file")}

    position_specs: list[PositionSpec] = []
    for path in position_paths:
        entry = manifest_positions.get(path.name, {})
        position_specs.append(
            PositionSpec(
                path=path,
                exam=str(entry.get("exam") or exam),
                province=str(entry.get("province") or province),
                year=int(entry.get("year") or year),
                preset=str(entry.get("preset") or preset),
                sheet_filter=[entry["sheet"]] if entry.get("sheet") else None,
            )
        )

    history_specs: list[HistorySpec] = []
    for path in history_paths:
        entry = manifest_history.get(path.name, {})
        spec_year = entry.get("year") or args.history_year
        history_specs.append(
            HistorySpec(
                path=path,
                exam=str(entry.get("exam") or exam),
                province=str(entry.get("province") or province),
                year=int(spec_year) if spec_year else None,
                kind=str(entry.get("kind") or args.history_kind or "笔试最低进面分"),
                scale=int(entry["scale"]) if entry.get("scale") else args.history_scale,
                preset=str(entry.get("preset") or preset),
            )
        )

    out_dir = Path(args.out) if args.out else root / "out" / str(year)
    if not out_dir.is_absolute():
        out_dir = root / out_dir

    config = RunConfig(
        positions=position_specs,
        history=history_specs,
        profile=profile,
        preset=preset,
        manual_links=Path(args.manual_links) if args.manual_links else root / "data" / "manual_links.csv",
        major_catalog=Path(args.major_catalog) if args.major_catalog else None,
        top=args.top,
        out_dir=out_dir,
    )
    result = run(config)

    from .report.csv_output import write_csv_outputs
    from .report.html_report import write_html
    from .report.text_report import write_summary

    write_csv_outputs(result, out_dir)
    text_path = write_summary(result, out_dir / "summary.txt", top=args.top or 15)
    if not args.no_html:
        write_html(result, out_dir / "report.html", profile)
    if not args.no_xlsx:
        from .report.excel_report import write_workbook

        write_workbook(result, out_dir / "report.xlsx", profile)

    print(summarize_text(result, top=args.top or 15))
    print("")
    print(f"输出目录：{out_dir}")
    print(f"  终端摘要：{text_path}")
    if not args.no_html:
        print(f"  HTML 报告：{out_dir / 'report.html'}")
    if not args.no_xlsx:
        print(f"  Excel 报告：{out_dir / 'report.xlsx'}")
    print(f"  匹配明细：{out_dir / 'links.csv'}（存疑：links_review.csv）")
    if result.issues:
        errors = [issue for issue in result.issues if issue.level == "error"]
        if errors:
            print("")
            print("存在错误级数据问题：")
            for issue in errors[:10]:
                print(f"  - {issue.file} {issue.sheet} 第{issue.row}行：{issue.message}")
    return 0


def _manifest_files(root: Path, manifest: dict, section: str, exam: str | None = None) -> list[Path]:
    files: list[Path] = []
    for entry in manifest.get(section) or []:
        value = entry.get("file")
        if not value:
            continue
        entry_exam = entry.get("exam")
        if exam and entry_exam and entry_exam != exam:
            continue
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        if path.exists():
            files.append(path)
    return files


def cmd_links(args) -> int:
    root = project_root()
    out_dir = Path(args.out) if args.out else _latest_out_dir(root / "out")
    if out_dir is None or not Path(out_dir).exists():
        raise FileNotFoundError("没有找到运行结果目录，先运行 run")
    out_dir = Path(out_dir)
    review = out_dir / "links_review.csv"
    unmatched = out_dir / "links_unmatched.csv"
    print(f"运行目录：{out_dir}")
    for title, path in (("待人工核对（有候选但置信度不足）", review), ("未匹配到岗位", unmatched)):
        print("")
        print(f"== {title} ==")
        if not path.exists():
            print("（没有该文件）")
            continue
        import csv

        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            print("（空）")
            continue
        for row in rows[: args.limit]:
            print(
                f"  {row.get('history_key', '')}  ->  {row.get('position_id', '') or '（未匹配）'}"
                f"  相似度 {row.get('score', '')}  {row.get('note', '')}"
            )
        print(f"  共 {len(rows)} 条（显示前 {min(len(rows), args.limit)} 条）")
    print("")
    print("修正方法：编辑 data/manual_links.csv，追加一行")
    print("  history_source,history_year,dept,post_name,position_id,action,note")
    print("history_key 格式为「年份|文件名|sheet|行号」，position_id 在 out/.../normalized/positions.csv 里查。")
    return 0


def _latest_out_dir(out_root: Path) -> Path | None:
    if not out_root.is_dir():
        return None
    candidates = [path for path in out_root.iterdir() if path.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def cmd_serve(args) -> int:
    from .server import serve

    return serve(port=args.port, run_dir=Path(args.run_dir) if args.run_dir else None, open_browser=not args.no_open)
