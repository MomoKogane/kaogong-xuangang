"""文本与数值清洗原语。

Excel 里的中文表格经常混入全角字符、换行、合并单元格残留、单位后缀，
分数还会写成 ``132.5-140.2`` 或 ``约 132``。这里集中处理这些脏值。
"""

from __future__ import annotations

import math
import re
from typing import Iterable, Optional

_CN_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

_EMPTY_TOKENS = {"", "-", "--", "—", "——", "/", "\\", "无", "暂无", "未公布", "不公布", "空", "nan", "none", "null"}
_ZW = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\u00a0"), None)


def to_halfwidth(text: str) -> str:
    """全角数字/字母/小数点和全角空格转半角；中文标点（如括号）保留原样。"""
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF10 <= code <= 0xFF19 or 0xFF21 <= code <= 0xFF3A or 0xFF41 <= code <= 0xFF5A:
            out.append(chr(code - 0xFEE0))
        elif code == 0xFF0E:
            out.append(".")
        else:
            out.append(ch)
    return "".join(out)


def clean_text(value) -> str:
    """把任意单元格值洗成单行文本；None / NaN / 空串都返回 ``""``。"""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    text = str(value)
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = to_halfwidth(text)
    text = text.translate(_ZW)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_blank(value) -> bool:
    return clean_text(value) == ""


def normalize_key(value) -> str:
    """用于比对的主键归一：去空白、去常见标点、统一括号。"""
    text = clean_text(value)
    if not text:
        return ""
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("【", "[").replace("】", "]")
    text = re.sub(r"[\s()\[\]{}《》<>«»、,，。.;；:：/\\|_\-—~～·]+", "", text)
    return text


def normalize_code(value) -> str:
    """职位代码归一：去空格/全角/千分位，去掉 Excel 数字残留的 ``.0``。"""
    text = clean_text(value).replace(",", "").replace("，", "")
    text = text.replace("'", "").replace('"', "")
    text = re.sub(r"\.0+$", "", text)
    return text


_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def parse_float(value) -> Optional[float]:
    """取文本中的第一个数字。``132.5分`` -> 132.5。"""
    text = clean_text(value).replace(",", "").replace("，", "")
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def parse_int(value) -> Optional[int]:
    """取文本中的第一个整数，支持 ``3人``、``若干``（None）与中文数字。"""
    text = clean_text(value).replace(",", "").replace("，", "")
    if not text or any(token in text for token in ("若干", "不限", "待定")):
        return None
    match = re.search(r"\d+", text)
    if match:
        return int(match.group())
    cn = re.search(r"[零一二两三四五六七八九十]+", text)
    if cn:
        return cn_to_int(cn.group())
    return None


def cn_to_int(text: str) -> Optional[int]:
    """中文数字（0-99）转整数。"""
    if not text:
        return None
    if "十" in text:
        head, _, tail = text.partition("十")
        tens = _CN_DIGITS.get(head, 1) if head else 1
        ones = _CN_DIGITS.get(tail, 0) if tail else 0
        return tens * 10 + ones
    if len(text) == 1:
        return _CN_DIGITS.get(text, 0)
    return None


def is_empty_token(value) -> bool:
    text = clean_text(value).lower()
    return text in _EMPTY_TOKENS or text == ""


def parse_score_range(value) -> tuple[Optional[float], Optional[float], str]:
    """解析进面分数，返回 ``(min, max, kind)``。

    - ``132.5`` -> (132.5, 132.5, "single")
    - ``132.5-140.2`` / ``132.5~140.2`` / ``132.5至140.2`` -> (132.5, 140.2, "range")
    - 空值 / ``未公布`` -> (None, None, "empty")
    """
    text = clean_text(value)
    if is_empty_token(text):
        return None, None, "empty"
    cleaned = text.replace(",", "").replace("，", "").replace("分", "")
    numbers = [float(item) for item in _NUMBER_RE.findall(cleaned)]
    if not numbers:
        return None, None, "no_number"
    if len(numbers) == 1:
        return numbers[0], numbers[0], "single"
    return min(numbers[0], numbers[1]), max(numbers[0], numbers[1]), "range"


def parse_years(value) -> Optional[int]:
    """解析年限要求。``两年以上`` -> 2，``无限制`` -> 0，``不限`` -> 0。"""
    text = clean_text(value)
    if not text:
        return None
    if "不限" in text or "无限制" in text or text in {"无", "无要求"}:
        return 0
    match = re.search(r"(\d+)\s*年", text)
    if match:
        return int(match.group(1))
    match = re.search(r"([零一二两三四五六七八九十]+)\s*年", text)
    if match:
        return cn_to_int(match.group(1))
    return None


def parse_ratio(value) -> Optional[float]:
    """解析面试比例，``3:1`` -> 3.0（每个招录名额对应的进面人数）。"""
    text = clean_text(value)
    match = re.search(r"(\d+)\s*[:：]\s*(\d+)", text)
    if not match:
        return None
    left, right = int(match.group(1)), int(match.group(2))
    if left <= 0 or right <= 0:
        return None
    return max(left, right) / min(left, right)


def split_tokens(value, seps: str = r"[、,，;；/／\n]") -> list[str]:
    """按中文顿号/分号/逗号/斜杠切分，保留括号内容。"""
    text = clean_text(value)
    if not text:
        return []
    parts = re.split(seps, text)
    result: list[str] = []
    for part in parts:
        part = part.strip()
        if part and not is_empty_token(part):
            result.append(part)
    return result


def dedupe_keep_order(items: Iterable) -> list:
    seen: set = set()
    out: list = []
    for item in items:
        key = item if isinstance(item, str) else repr(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def infer_score_scale(values: Iterable[Optional[float]]) -> Optional[int]:
    """根据一组进面分推断分数制式（100/150/200/300）。

    规则（保守，报告里会提示人工核对）：
    - 最大值 > 220 或中位数 > 150 -> 300 分制
    - 最大值 > 150 或中位数 > 105 -> 200 分制
    - 最大值 > 120 或中位数 > 85 -> 150 分制
    - 其余 -> 100 分制
    """
    numbers = sorted(v for v in values if v is not None and v > 0)
    if not numbers:
        return None
    median = numbers[len(numbers) // 2]
    maximum = numbers[-1]
    if maximum > 220 or median > 150:
        return 300
    if maximum > 150 or median > 105:
        return 200
    if maximum > 110 or median > 90:
        return 150
    return 100


def score_to_200(value: Optional[float], scale: int) -> Optional[float]:
    """把任意制式折算成 200 分制，便于跨年比较。"""
    if value is None or not scale:
        return None
    return round(value / scale * 200, 2)


def display_width(text: str) -> int:
    """终端对齐用：中日韩字符按 2 列宽计。"""
    width = 0
    for ch in str(text):
        width += 2 if ord(ch) > 0x2E7F else 1
    return width


def pad_display(text: str, width: int, align: str = "left") -> str:
    text = str(text)
    padding = max(0, width - display_width(text))
    if align == "right":
        return " " * padding + text
    return text + " " * padding


def truncate_display(text: str, width: int) -> str:
    text = str(text)
    if display_width(text) <= width:
        return text
    out = ""
    used = 0
    for ch in text:
        char_width = 2 if ord(ch) > 0x2E7F else 1
        if used + char_width > width - 1:
            break
        out += ch
        used += char_width
    return out + "…"
