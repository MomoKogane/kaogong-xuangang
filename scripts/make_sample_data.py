"""生成内置仿真数据（可复现），用于演示与快速验证。

包含国考与广东省考两套：岗位表 + 多年分数线，刻意混入一些真实世界里的脏数据：
标题行在表头上方、合并单元格、全角数字、区间分数、缺职位代码、缺用人司局、重复行。
"""

from __future__ import annotations

import random
from pathlib import Path

import xlsxwriter

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "sample"

POSITION_HEADERS = [
    "部门代码", "部门名称", "用人司局", "机构性质", "招考职位", "职位代码", "职位属性", "职位分布",
    "职位简介", "招考人数", "专业", "学历", "学位", "政治面貌", "基层工作最低年限",
    "服务基层项目工作经历", "是否在面试阶段组织专业能力测试", "面试人员比例", "工作地点", "落户地点", "备注",
]

HISTORY_HEADERS = [
    "年份", "部门名称", "用人司局", "职位名称", "职位代码", "最低进面分", "最高进面分", "进面人数", "报名人数", "竞争比",
]

UNITS = [
    ("100101", "国家税务总局广东省税务局", "国家税务总局广州市税务局", "广东省广州市"),
    ("100102", "国家税务总局广东省税务局", "国家税务总局深圳市税务局", "广东省深圳市"),
    ("100201", "国家税务总局北京市税务局", "国家税务总局北京市海淀区税务局", "北京市海淀区"),
    ("100301", "国家税务总局江苏省税务局", "国家税务总局南京市税务局", "江苏省南京市"),
    ("100401", "国家税务总局浙江省税务局", "国家税务总局杭州市税务局", "浙江省杭州市"),
    ("129101", "中华人民共和国北京海关", "北京首都机场海关", "北京市顺义区"),
    ("129201", "中华人民共和国上海海关", "上海浦东国际机场海关", "上海市浦东新区"),
    ("129301", "中华人民共和国广州海关", "广州白云机场海关", "广东省广州市"),
    ("135101", "国家统计局广东调查总队", "国家统计局广州调查队", "广东省广州市"),
    ("132101", "国家金融监督管理总局广东监管局", "广东监管局", "广东省广州市"),
    ("153101", "广东省气象局", "广州市气象局", "广东省广州市"),
    ("119101", "水利部珠江水利委员会", "珠江水利委员会", "广东省广州市"),
    ("109201", "广州铁路公安局", "广州铁路公安处", "广东省广州市"),
    ("130101", "中国民用航空局中南地区管理局", "民航广东安全监督管理局", "广东省广州市"),
    ("100501", "国家税务总局四川省税务局", "国家税务总局成都市税务局", "四川省成都市"),
]

POST_TEMPLATES = [
    {
        "post": "一级行政执法员（一）", "major": "中国语言文学类、新闻传播学类",
        "education": "本科及以上", "degree": "学士", "politics": "不限", "grassroots": "无限制",
        "fresh": "否", "cert": "", "remark": "", "headcount": 3,
    },
    {
        "post": "一级行政执法员（二）", "major": "法学类",
        "education": "本科及以上", "degree": "学士", "politics": "中共党员", "grassroots": "两年",
        "fresh": "否", "cert": "法律职业资格A类", "remark": "限男性；最低服务年限5年", "headcount": 2,
    },
    {
        "post": "办公室一级科员", "major": "专业不限",
        "education": "仅限本科", "degree": "学士", "politics": "中共党员或共青团员", "grassroots": "无限制",
        "fresh": "是", "cert": "", "remark": "2027年应届毕业生", "headcount": 4,
    },
    {
        "post": "综合管理一级科员", "major": "经济学类、统计学类",
        "education": "硕士研究生及以上", "degree": "硕士", "politics": "不限", "grassroots": "无限制",
        "fresh": "否", "cert": "", "remark": "", "headcount": 2,
    },
    {
        "post": "稽查局一级行政执法员", "major": "计算机类、电子信息类",
        "education": "本科及以上", "degree": "学士", "politics": "不限", "grassroots": "无限制",
        "fresh": "否", "cert": "计算机二级", "remark": "需经常出差", "headcount": 5,
    },
    {
        "post": "一级科员", "major": "汉语言文学、秘书学",
        "education": "本科", "degree": "学士", "politics": "不限", "grassroots": "无限制",
        "fresh": "否", "cert": "", "remark": "", "headcount": 1,
    },
    {
        "post": "法制岗一级科员", "major": "法学（0301）",
        "education": "本科及以上", "degree": "学士", "politics": "不限", "grassroots": "无限制",
        "fresh": "否", "cert": "法律职业资格A类", "remark": "限女性", "headcount": 2,
    },
    {
        "post": "财务岗一级科员", "major": "会计学、财务管理",
        "education": "本科及以上", "degree": "学士", "politics": "不限", "grassroots": "无限制",
        "fresh": "否", "cert": "", "remark": "限本省户籍；最低服务年限3年", "headcount": 2,
    },
]

EXAM_CATEGORIES = ["中央机关及其省级直属机构", "市（地）级及以下直属机构", "行政执法类"]
PROJECTS = ["无限制", "无限制", "无限制", "大学生村官", "三支一扶"]


def _position_rows(seed: int = 2027):
    random.seed(seed)
    rows = []
    for unit_index, (dept_code, dept, unit, place) in enumerate(UNITS):
        for post_index, template in enumerate(POST_TEMPLATES):
            code = f"{dept_code}{unit_index + 1:02d}{post_index + 1:03d}"
            headcount = template["headcount"]
            headcount_text = str(headcount)
            if unit_index == 2 and post_index == 0:
                headcount_text = "３"  # 全角数字，测试清洗
            rows.append(
                [
                    dept_code,
                    dept,
                    unit,
                    "中央国家行政机关省级以下直属机构",
                    template["post"],
                    code,
                    "普通职位",
                    "其他职位",
                    f"从事{template['post']}相关工作",
                    headcount_text,
                    template["major"],
                    template["education"],
                    template["degree"],
                    template["politics"],
                    template["grassroots"],
                    PROJECTS[post_index % len(PROJECTS)],
                    "否",
                    "3:1",
                    place,
                    place,
                    template["remark"],
                ]
            )
    return rows


def _history_rows(positions, year: int, seed: int):
    random.seed(seed)
    rows = []
    for index, row in enumerate(positions):
        dept_code, dept, unit, place = row[0], row[1], row[2], row[18]
        post, code = row[4], row[5]
        if index % 7 == 0:
            continue  # 部分岗位没有历史数据
        base = 126 + (index % 15) * 0.8 + random.uniform(-2.5, 2.5) + (year - 2024) * 2
        min_score = round(base, 1)
        max_score = round(min_score + random.uniform(2, 8), 1)
        min_text = f"{min_score}"
        max_text = f"{max_score}"
        if index % 11 == 0:
            min_text, max_text = f"{min_score}-{max_score}", ""  # 区间写法
        elif index % 13 == 0:
            min_text = "未公布"
        included_code = code if index % 3 != 0 else ""
        included_unit = unit if index % 5 != 0 else ""
        post_text = post
        if index % 9 == 0:
            post_text = post.replace("（", "(").replace("）", ")")  # 全角/半角括号混用
        headcount = row[9]
        applicants = random.randint(int(headcount) * 20, int(headcount) * 180) if str(headcount).isdigit() else None
        rows.append(
            [
                year,
                dept,
                included_unit,
                post_text,
                included_code,
                min_text,
                max_text,
                random.randint(6, 30),
                applicants or "",
                f"{round(applicants / max(1, int(str(headcount).strip())), 1)}:1" if applicants else "",
            ]
        )
        if index % 17 == 0:
            rows.append(list(rows[-1]))  # 重复行
    return rows


def _write_sheet(workbook, name, headers, rows, title: str | None = None, widths=None):
    sheet = workbook.add_worksheet(name)
    header_format = workbook.add_format({"bold": True, "bg_color": "#DDEBF7", "border": 1})
    title_format = workbook.add_format({"bold": True, "font_size": 13})
    start = 0
    if title:
        sheet.merge_range(0, 0, 0, len(headers) - 1, title, title_format)
        start = 1
    for column, header in enumerate(headers):
        sheet.write_string(start, column, header, header_format)
        sheet.set_column(column, column, widths[column] if widths else 16)
    for offset, row in enumerate(rows):
        for column, value in enumerate(row):
            sheet.write(start + 1 + offset, column, value)
    sheet.freeze_panes(start + 1, 0)
    return sheet


def build_guokao() -> tuple[Path, list]:
    folder = SAMPLE / "positions"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "2027国考职位表.xlsx"
    positions = _position_rows()
    workbook = xlsxwriter.Workbook(str(path))
    widths = [10, 30, 30, 26, 26, 16, 10, 12, 24, 8, 30, 14, 8, 14, 12, 18, 18, 10, 18, 18, 30]
    _write_sheet(
        workbook, "中央党群机关", POSITION_HEADERS,
        [row for row in positions if row[1].endswith("海关")],
        title="2027年度国家公务员考试职位表（节选）", widths=widths,
    )
    _write_sheet(
        workbook, "省级以下直属机构", POSITION_HEADERS,
        [row for row in positions if not row[1].endswith("海关")],
        widths=widths,
    )
    workbook.close()
    return path, positions


def build_history(positions) -> list[Path]:
    folder = SAMPLE / "history"
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for year, seed, title in (
        (2024, 2024, "2024年国考进面分数线（民间整理）"),
        (2025, 2025, "2025年国考进面分数线（民间整理）"),
        (2026, 2026, "2026年国考进面分数线（民间整理）"),
    ):
        path = folder / f"{year}国考进面分数线.xlsx"
        rows = _history_rows(positions, year, seed)
        workbook = xlsxwriter.Workbook(str(path))
        widths = [8, 30, 26, 26, 16, 12, 12, 10, 10, 10]
        _write_sheet(workbook, "进面分数", HISTORY_HEADERS, rows, title=title, widths=widths)
        workbook.close()
        paths.append(path)
    return paths


GUANGDONG_HEADERS = [
    "序号", "招录机关", "用人单位", "职位名称", "职位代码", "职位类别", "招考人数", "学历要求", "学位要求",
    "研究生专业名称及代码", "本科专业名称及代码", "大专专业名称及代码", "政治面貌", "基层工作经历",
    "是否要求应届毕业生", "其他要求", "工作地点",
]

GUANGDONG_POSITIONS = [
    ("广东省财政厅", "广东省财政厅机关", "一级主任科员以下", "199001", "综合管理类", 2, "研究生", "硕士",
     "应用经济学（0202）", "", "", "不限", "无限制", "否", "具有2年以上基层工作经历", "广州市"),
    ("广东省人力资源和社会保障厅", "省社会保险基金管理局", "一级主任科员以下", "199002", "综合管理类", 1, "本科以上", "学士以上",
     "", "中国语言文学类（B0501）、新闻传播学类（B0503）", "", "中共党员", "无限制", "否", "", "广州市"),
    ("广东省市场监督管理局", "广东省市场监督管理局机关", "一级主任科员以下", "199003", "行政执法类", 3, "本科以上", "学士以上",
     "", "法学类（B0301）", "", "不限", "无限制", "否", "通过法律职业资格考试（A类）", "广州市"),
    ("广州市财政局", "广州市财政局", "四级主任科员以下", "199004", "综合管理类", 1, "本科", "学士",
     "", "会计学（B120203）", "", "不限", "无限制", "否", "", "广州市"),
    ("深圳市南山区人民政府", "南山区教育局", "一级科员", "199005", "综合管理类", 1, "本科以上", "学士以上",
     "", "教育学类（B0401）", "", "不限", "无限制", "是", "2026年应届毕业生", "深圳市"),
    ("珠海市生态环境局", "珠海市生态环境局", "一级行政执法员", "199006", "行政执法类", 2, "本科以上", "学士以上",
     "", "环境科学与工程类（B0825）", "", "不限", "无限制", "否", "限男性", "珠海市"),
    ("佛山市禅城区人民法院", "佛山市禅城区人民法院", "五级法官助理", "199007", "综合管理类", 2, "本科以上", "学士以上",
     "", "法学类（B0301）", "", "不限", "无限制", "否", "通过法律职业资格考试（A类）", "佛山市"),
    ("惠州市惠阳区人民政府", "惠阳区财政局", "一级科员", "199008", "综合管理类", 1, "本科以上", "学士以上",
     "", "财政学类（B0202）", "", "不限", "无限制", "否", "限本省户籍", "惠州市"),
    ("广东省统计局", "广东省统计局", "一级主任科员以下", "199009", "综合管理类", 1, "本科以上", "学士以上",
     "", "中国语言文学类（B0501）、新闻传播学类（B0503）", "", "不限", "无限制", "否", "", "广州市"),
    ("广州市文化广电旅游局", "广州市文化广电旅游局", "一级科员", "199010", "综合管理类", 1, "本科以上", "学士以上",
     "", "中国语言文学类（B0501）", "", "不限", "无限制", "否", "", "广州市"),
]


def build_province() -> tuple[Path, list[Path]]:
    folder = SAMPLE / "province"
    folder.mkdir(parents=True, exist_ok=True)
    position_path = folder / "2026广东省考职位表.xlsx"
    workbook = xlsxwriter.Workbook(str(position_path))
    rows = []
    for index, item in enumerate(GUANGDONG_POSITIONS, start=1):
        rows.append([index] + list(item))
    widths = [6, 26, 26, 22, 14, 14, 8, 12, 10, 26, 30, 20, 12, 14, 14, 30, 12]
    _write_sheet(workbook, "职位表", GUANGDONG_HEADERS, rows, widths=widths)
    workbook.close()

    history_path = folder / "2025广东省考进面分数线.xlsx"
    history_rows = []
    for index, item in enumerate(GUANGDONG_POSITIONS):
        dept = item[0]
        post = item[2]
        code = item[3]
        base = 205 + index * 4 + random.uniform(-3, 3)
        history_rows.append([2025, dept, post, code, round(base, 1), round(base + 6, 1), 6])
    workbook = xlsxwriter.Workbook(str(history_path))
    _write_sheet(
        workbook, "进面分数",
        ["年份", "招录机关", "职位名称", "职位代码", "最低进面分", "最高进面分", "进面人数"],
        history_rows,
        title="2025年广东省考进面分数线（民间整理）",
        widths=[8, 28, 24, 14, 12, 12, 10],
    )
    workbook.close()
    return position_path, [history_path]


def build_manifest(guokao_positions: Path, history_paths: list[Path], province_positions: Path, province_history: list[Path]) -> Path:
    lines = [
        "# 内置仿真数据的清单：直接用它跑演示。",
        "# 真实数据请照抄格式，把 file 指向 data/incoming/ 下的文件。",
        "",
        "[[positions]]",
        f'file = "{guokao_positions.relative_to(ROOT).as_posix()}"',
        'exam = "guokao"',
        'province = "全国"',
        "year = 2027",
        'preset = "guokao"',
        "",
    ]
    for path in sorted(history_paths):
        year = int(path.stem[:4])
        lines += [
            "[[history]]",
            f'file = "{path.relative_to(ROOT).as_posix()}"',
            'exam = "guokao"',
            'province = "全国"',
            f"year = {year}",
            'kind = "笔试最低进面分"',
            "scale = 200",
            "",
        ]
    lines += [
        "[[positions]]",
        f'file = "{province_positions.relative_to(ROOT).as_posix()}"',
        'exam = "shengkao"',
        'province = "广东省"',
        "year = 2026",
        'preset = "guangdong"',
        "",
    ]
    for path in province_history:
        lines += [
            "[[history]]",
            f'file = "{path.relative_to(ROOT).as_posix()}"',
            'exam = "shengkao"',
            'province = "广东省"',
            "year = 2025",
            'kind = "笔试最低进面分"',
            "scale = 300",
            "",
        ]
    manifest = SAMPLE / "manifest.toml"
    manifest.write_text("\n".join(lines), encoding="utf-8")
    return manifest


BOB_PROFILE = """# bob 的个人条件（仿真数据配套）
name = "bob"
education_level = "本科"
degree = "学士"
full_time = true
major = "汉语言文学"
major_code = "050101"
major_level = "本科"
school = "华南师范大学"
school_tags = ["双一流"]

politics = "共青团员"
ethnicity = "汉族"
gender = "男"
birth_year = 2001
fresh_status = "择业期内"
graduation_year = 2025
has_employment_record = false

grassroots_years = 2
certificates = ["法律职业资格A证"]

hukou_province = "广东省"
hometown_province = "广东省"

preferred_regions = ["广州", "深圳"]
prefer_hometown = true

exam = "guokao"
province = ""
target_year = 2027
estimated_score = 132.5
score_scale = 200

[[grassroots_projects]]
name = "三支一扶"
completed = true
"""


BOB_PROVINCE_PROFILE = """# bob 的广东省考条件（仿真数据配套）
name = "bob"
education_level = "本科"
degree = "学士"
full_time = true
major = "汉语言文学"
major_code = "050101"
major_level = "本科"

politics = "共青团员"
ethnicity = "汉族"
gender = "男"
birth_year = 2001
fresh_status = "择业期内"
graduation_year = 2025
has_employment_record = false

grassroots_years = 2
certificates = ["法律职业资格A证"]

hukou_province = "广东省"
hometown_province = "广东省"

preferred_regions = ["广州"]
prefer_hometown = true

exam = "shengkao"
province = "广东省"
target_year = 2026
estimated_score = 240
score_scale = 300
"""


def main() -> None:
    SAMPLE.mkdir(parents=True, exist_ok=True)
    guokao_positions, positions = build_guokao()
    history_paths = build_history(positions)
    province_positions, province_history = build_province()
    manifest = build_manifest(guokao_positions, history_paths, province_positions, province_history)
    profile = SAMPLE / "bob.toml"
    profile.write_text(BOB_PROFILE, encoding="utf-8")
    province_profile = SAMPLE / "bob_province.toml"
    province_profile.write_text(BOB_PROVINCE_PROFILE, encoding="utf-8")
    print(f"岗位表：{guokao_positions}")
    print(f"分数线：{', '.join(path.name for path in history_paths)}")
    print(f"省考样本：{province_positions}")
    print(f"manifest：{manifest}")
    print(f"个人条件：{profile}")
    print(f"省考条件：{province_profile}")


if __name__ == "__main__":
    main()
