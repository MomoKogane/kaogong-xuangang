"""读取旧版 Excel（.xls）以及常见的「伪 xls」文件。

不依赖 xlrd / LibreOffice / Excel，纯标准库实现：

- OLE2 复合文档里的 BIFF8 / BIFF5 工作簿（Excel 97-2003、Excel 5.0/95）
- Excel 2003 XML Spreadsheet（另存为 .xls 时很常见）
- HTML 表格伪装成 .xls（很多政务网站导出就是这种）
- 制表符/逗号分隔文本伪装成 .xls

返回与 ``excel.read_table`` 一致的 ``RawSheet`` 列表。
"""

from __future__ import annotations

import codecs
import csv
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from .excel import RawSheet
from .values import clean_text

OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_END_OF_CHAIN = {0xFFFFFFFE, 0xFFFFFFFF}
_MAX_CELLS = 2_000_000


def read_xls(path: Path) -> list[RawSheet]:
    data = Path(path).read_bytes()
    if data.startswith(OLE_SIGNATURE):
        return _read_biff_workbook(data, Path(path).name)
    text = _decode_text(data)
    stripped = text.lstrip("\ufeff \t\r\n")
    head = stripped[:4096].lower()
    if "urn:schemas-microsoft-com:office:spreadsheet" in head:
        return _parse_xml_spreadsheet(text)
    if stripped.startswith("<") and ("<table" in head or "<html" in head or "<tr" in head):
        return _parse_html_tables(text)
    if stripped.startswith("<"):
        raise ValueError("这个 .xls 内容像 XML/HTML，但没有识别出表格，请用 Excel 另存为 .xlsx")
    return _parse_text_table(text, Path(path).stem)


# --------------------------------------------------------------------------
# OLE2 复合文档
# --------------------------------------------------------------------------


class OleError(ValueError):
    pass


class OleFile:
    def __init__(self, data: bytes):
        self.data = data
        if data[:8] != OLE_SIGNATURE:
            raise OleError("不是 OLE2 复合文档")
        try:
            self.sector_size = 1 << struct.unpack_from("<H", data, 30)[0]
            self.mini_sector_size = 1 << struct.unpack_from("<H", data, 32)[0]
            self.num_fat = struct.unpack_from("<I", data, 44)[0]
            self.first_dir = struct.unpack_from("<I", data, 48)[0]
            self.mini_cutoff = struct.unpack_from("<I", data, 56)[0]
            self.first_minifat = struct.unpack_from("<I", data, 60)[0]
            self.num_minifat = struct.unpack_from("<I", data, 64)[0]
            self.first_difat = struct.unpack_from("<I", data, 68)[0]
            self.num_difat = struct.unpack_from("<I", data, 72)[0]
        except struct.error as exc:
            raise OleError("OLE2 头部不完整") from exc
        if self.sector_size not in (512, 4096):
            raise OleError(f"不支持的 OLE 扇区大小：{self.sector_size}")
        self.fat = self._read_fat()
        self.directory = self._read_directory()
        self.root = next((item for item in self.directory if item["type"] == 5), None)
        self.minifat: list[int] = []
        self.ministream = b""
        if self.root:
            self.ministream = self._read_fat_chain(self.root["start"])[: self.root["size"]]
            self.minifat = self._read_mini_fat()

    def _sector(self, sector_id: int) -> bytes:
        offset = (sector_id + 1) * self.sector_size
        return self.data[offset : offset + self.sector_size]

    def _read_fat(self) -> list[int]:
        difat: list[int] = []
        for index in range(109):
            value = struct.unpack_from("<I", self.data, 76 + index * 4)[0]
            if value not in _END_OF_CHAIN:
                difat.append(value)
        next_sector = self.first_difat
        seen = set()
        while next_sector not in _END_OF_CHAIN and next_sector < 0xFFFFFFF0:
            if next_sector in seen:
                raise OleError("DIFAT 链循环")
            seen.add(next_sector)
            block = self._sector(next_sector)
            count = len(block) // 4 - 1
            for index in range(count):
                value = struct.unpack_from("<I", block, index * 4)[0]
                if value not in _END_OF_CHAIN:
                    difat.append(value)
            next_sector = struct.unpack_from("<I", block, count * 4)[0]

        fat: list[int] = []
        for sector_id in difat:
            block = self._sector(sector_id)
            fat.extend(struct.unpack("<" + "I" * (len(block) // 4), block))
        return fat

    def _read_fat_chain(self, start: int) -> bytes:
        chunks: list[bytes] = []
        sector_id = start
        seen = set()
        while sector_id not in _END_OF_CHAIN and sector_id < len(self.fat):
            if sector_id in seen:
                raise OleError("FAT 链循环")
            seen.add(sector_id)
            chunks.append(self._sector(sector_id))
            sector_id = self.fat[sector_id]
        return b"".join(chunks)

    def _read_mini_fat(self) -> list[int]:
        if self.first_minifat in _END_OF_CHAIN:
            return []
        block = self._read_fat_chain(self.first_minifat)
        return list(struct.unpack("<" + "I" * (len(block) // 4), block))

    def _read_mini_chain(self, start: int) -> bytes:
        chunks: list[bytes] = []
        sector_id = start
        seen = set()
        while sector_id not in _END_OF_CHAIN and sector_id < len(self.minifat):
            if sector_id in seen:
                raise OleError("MiniFAT 链循环")
            seen.add(sector_id)
            offset = sector_id * self.mini_sector_size
            chunks.append(self.ministream[offset : offset + self.mini_sector_size])
            sector_id = self.minifat[sector_id]
        return b"".join(chunks)

    def _read_directory(self) -> list[dict]:
        block = self._read_fat_chain(self.first_dir)
        entries: list[dict] = []
        for offset in range(0, len(block) - 127, 128):
            entry = block[offset : offset + 128]
            name_length = struct.unpack_from("<H", entry, 64)[0]
            entry_type = entry[66]
            if name_length < 2 or name_length > 64:
                name = ""
            else:
                name = entry[: name_length - 2].decode("utf-16-le", "replace")
            start = struct.unpack_from("<I", entry, 116)[0]
            size = struct.unpack_from("<Q", entry, 120)[0]
            if entry_type in (1, 2, 5):
                entries.append({"name": name, "type": entry_type, "start": start, "size": size})
        return entries

    def open_stream(self, names: list[str]) -> bytes | None:
        wanted = {name.lower() for name in names}
        for entry in self.directory:
            if entry["type"] != 2 or entry["name"].lower() not in wanted:
                continue
            if entry["size"] == 0:
                return b""
            if entry["size"] < self.mini_cutoff:
                data = self._read_mini_chain(entry["start"])
            else:
                data = self._read_fat_chain(entry["start"])
            return data[: entry["size"]]
        return None


# --------------------------------------------------------------------------
# BIFF8 / BIFF5
# --------------------------------------------------------------------------


def _read_biff_workbook(data: bytes, filename: str) -> list[RawSheet]:
    ole = OleFile(data)
    stream = ole.open_stream(["Workbook", "Book"])
    if stream is None:
        names = [entry["name"] for entry in ole.directory if entry["type"] == 2]
        raise ValueError(f"{filename} 里没有找到 Workbook/Book 流（包含：{'、'.join(names[:8])}）")
    sheets = _parse_biff(stream)
    if not sheets:
        raise ValueError(f"{filename} 里没有读到工作表数据")
    return sheets


def _iter_records(data: bytes, offset: int = 0):
    position = offset
    length_total = len(data)
    while position + 4 <= length_total:
        record_type, length = struct.unpack_from("<HH", data, position)
        end = position + 4 + length
        if end > length_total:
            break
        yield position, record_type, data[position + 4 : end]
        position = end


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _double(data: bytes, offset: int) -> float:
    return struct.unpack_from("<d", data, offset)[0]


def _rk_value(value: int) -> float:
    if value & 0x02:
        if value & 0x80000000:
            integer = (value - 0x100000000) >> 2
        else:
            integer = value >> 2
        number = float(integer)
    else:
        number = struct.unpack("<d", b"\x00\x00\x00\x00" + struct.pack("<I", value & 0xFFFFFFFC))[0]
    if value & 0x01:
        number /= 100.0
    return number


def _format_number(value: float) -> str:
    if value != value:  # NaN
        return ""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return format(value, ".15g")


class _SstStream:
    """SST 可能跨多个 CONTINUE 记录；按字符串读取时处理续接标志。"""

    def __init__(self, segments: list[bytes]):
        self.segments = segments
        self.segment = 0
        self.position = 0

    def eof(self) -> bool:
        self._skip_empty()
        return self.segment >= len(self.segments)

    def _skip_empty(self) -> None:
        while self.segment < len(self.segments) and self.position >= len(self.segments[self.segment]):
            self.segment += 1
            self.position = 0

    def read(self, count: int) -> bytes:
        out = bytearray()
        while count > 0:
            self._skip_empty()
            if self.segment >= len(self.segments):
                break
            block = self.segments[self.segment]
            take = min(count, len(block) - self.position)
            out += block[self.position : self.position + take]
            self.position += take
            count -= take
        return bytes(out)

    def read_string(self, count: int, compressed: bool) -> str:
        parts: list[str] = []
        remaining = count
        while remaining > 0:
            if self.segment >= len(self.segments):
                break
            block = self.segments[self.segment]
            if self.position >= len(block):
                # 进入 CONTINUE：第一个字节是该段字符的新编码标志
                self.segment += 1
                self.position = 0
                if self.segment >= len(self.segments):
                    break
                flags = self.segments[self.segment][0]
                self.position = 1
                compressed = (flags & 0x01) == 0
                continue
            width = 1 if compressed else 2
            available = (len(block) - self.position) // width
            if available <= 0:
                self.segment += 1
                self.position = 0
                if self.segment >= len(self.segments):
                    break
                flags = self.segments[self.segment][0]
                self.position = 1
                compressed = (flags & 0x01) == 0
                continue
            take = min(remaining, available)
            raw = block[self.position : self.position + take * width]
            self.position += take * width
            parts.append(raw.decode("latin-1") if compressed else raw.decode("utf-16-le", "replace"))
            remaining -= take
            if remaining > 0:
                # 跨到下一个 CONTINUE 继续读字符：先读该段的编码标志
                self.segment += 1
                self.position = 0
                if self.segment >= len(self.segments):
                    break
                flags = self.segments[self.segment][0]
                self.position = 1
                compressed = (flags & 0x01) == 0
        return "".join(parts)


def _parse_biff(stream: bytes) -> list[RawSheet]:
    records = list(_iter_records(stream))
    if not records:
        raise ValueError("BIFF 流为空")
    first_type, first_data = records[0][1], records[0][2]
    if first_type not in (0x0809, 0x0409, 0x0209, 0x0009):
        raise ValueError(f"不是可识别的 BIFF 记录（首个记录 0x{first_type:04X}）")
    version = _u16(first_data, 0) if len(first_data) >= 2 else 0x0600
    unicode8 = version >= 0x0600
    if version < 0x0500:
        raise ValueError("这是 Excel 4.0 及更早的格式，请用 Excel 另存为 .xlsx")

    codepage = 936 if not unicode8 else 1200
    sheet_entries: list[tuple[str, int]] = []
    sst: list[str] = []
    index = 0
    while index < len(records):
        position, record_type, payload = records[index]
        if record_type == 0x000A:  # EOF
            break
        if record_type == 0x002F:  # FILEPASS
            raise ValueError("这个 .xls 设置了密码或加密，请先取消密码再上传")
        if record_type == 0x0042 and len(payload) >= 2:  # CODEPAGE
            codepage = _u16(payload, 0)
        elif record_type == 0x0085:  # BOUNDSHEET
            if len(payload) >= 6:
                offset = _u32(payload, 0)
                name = _parse_short_string(payload, 6, unicode8, codepage)
                sheet_entries.append((name, offset))
        elif record_type == 0x00FC:  # SST
            segments = [payload]
            cursor = index + 1
            while cursor < len(records) and records[cursor][1] == 0x003C:
                segments.append(records[cursor][2])
                cursor += 1
            sst = _parse_sst(segments)
            index = cursor - 1
        index += 1

    if not sheet_entries:
        return []

    sheets: list[RawSheet] = []
    used_names: set[str] = set()
    for name, offset in sheet_entries:
        grid = _parse_sheet(stream, offset, unicode8, codepage, sst)
        grid = _trim_grid(grid)
        if not grid:
            continue
        sheet_name = clean_text(name) or f"Sheet{len(sheets) + 1}"
        if sheet_name in used_names:
            suffix = 2
            while f"{sheet_name}_{suffix}" in used_names:
                suffix += 1
            sheet_name = f"{sheet_name}_{suffix}"
        used_names.add(sheet_name)
        sheets.append(RawSheet(name=sheet_name, rows=grid))
    return sheets


def _parse_short_string(data: bytes, offset: int, unicode8: bool, codepage: int) -> str:
    if offset >= len(data):
        return ""
    length = data[offset]
    if unicode8:
        if offset + 1 >= len(data):
            return ""
        flags = data[offset + 1]
        start = offset + 2
        width = 2 if flags & 0x01 else 1
        raw = data[start : start + length * width]
        return raw.decode("utf-16-le", "replace") if width == 2 else raw.decode("latin-1", "replace")
    raw = data[offset + 1 : offset + 1 + length]
    return raw.decode(_codepage_name(codepage), "replace")


def _parse_sst(segments: list[bytes]) -> list[str]:
    reader = _SstStream(segments)
    try:
        total = struct.unpack("<I", reader.read(4))[0]
        unique = struct.unpack("<I", reader.read(4))[0]
    except struct.error:
        return []
    count = min(unique, total, 2_000_000)
    strings: list[str] = []
    for _ in range(count):
        if reader.eof():
            break
        header = reader.read(2)
        if len(header) < 2:
            break
        cch = struct.unpack("<H", header)[0]
        flags_bytes = reader.read(1)
        if len(flags_bytes) < 1:
            break
        flags = flags_bytes[0]
        compressed = (flags & 0x01) == 0
        rich = bool(flags & 0x08)
        extended = bool(flags & 0x04)
        c_run = 0
        ext_size = 0
        if rich:
            block = reader.read(2)
            if len(block) == 2:
                c_run = struct.unpack("<H", block)[0]
        if extended:
            block = reader.read(4)
            if len(block) == 4:
                ext_size = struct.unpack("<I", block)[0]
        text = reader.read_string(cch, compressed)
        strings.append(text)
        if rich and c_run:
            reader.read(c_run * 4)
        if extended and ext_size:
            reader.read(ext_size)
    return strings


def _parse_sheet(
    stream: bytes,
    offset: int,
    unicode8: bool,
    codepage: int,
    sst: list[str],
) -> list[list[str]]:
    cells: dict[tuple[int, int], str] = {}
    merged_ranges: list[tuple[int, int, int, int]] = []
    pending_formula: tuple[int, int] | None = None
    started = False
    for _position, record_type, payload in _iter_records(stream, offset):
        if record_type == 0x0809:  # BOF
            if started and len(payload) >= 4 and _u16(payload, 2) == 0x0010:
                break
            started = True
            continue
        if record_type == 0x000A:  # EOF
            break
        try:
            if record_type == 0x00FD and len(payload) >= 10:  # LABELSST
                row, col = struct.unpack_from("<HH", payload, 0)
                sst_index = _u32(payload, 6)
                cells[(row, col)] = sst[sst_index] if 0 <= sst_index < len(sst) else ""
            elif record_type == 0x0204 and len(payload) >= 6:  # LABEL
                row, col = struct.unpack_from("<HH", payload, 0)
                cells[(row, col)] = _parse_label_string(payload, 6, unicode8, codepage)
            elif record_type == 0x0203 and len(payload) >= 14:  # NUMBER
                row, col = struct.unpack_from("<HH", payload, 0)
                cells[(row, col)] = _format_number(_double(payload, 6))
            elif record_type == 0x027E and len(payload) >= 10:  # RK
                row, col = struct.unpack_from("<HH", payload, 0)
                cells[(row, col)] = _format_number(_rk_value(_u32(payload, 6)))
            elif record_type == 0x00BD and len(payload) >= 6:  # MULRK
                row = _u16(payload, 0)
                first_col = _u16(payload, 2)
                count = (len(payload) - 6) // 6
                for index in range(count):
                    value = _u32(payload, 4 + index * 6 + 2)
                    cells[(row, first_col + index)] = _format_number(_rk_value(value))
            elif record_type == 0x0006 and len(payload) >= 14:  # FORMULA
                row, col = struct.unpack_from("<HH", payload, 0)
                if payload[12] == 0xFF and payload[13] == 0xFF:
                    kind = payload[6]
                    if kind == 0x00:
                        pending_formula = (row, col)
                    elif kind == 0x01:
                        cells[(row, col)] = "TRUE" if payload[8] else "FALSE"
                    elif kind == 0x03:
                        cells[(row, col)] = ""
                else:
                    cells[(row, col)] = _format_number(_double(payload, 6))
            elif record_type == 0x0207 and pending_formula is not None:  # STRING
                row, col = pending_formula
                cells[(row, col)] = _parse_label_string(payload, 0, unicode8, codepage)
                pending_formula = None
            elif record_type == 0x0205 and len(payload) >= 8:  # BOOLERR
                row, col = struct.unpack_from("<HH", payload, 0)
                cells[(row, col)] = "TRUE" if payload[6] else "FALSE"
            elif record_type == 0x00E5 and len(payload) >= 2:  # MERGEDCELLS
                count = _u16(payload, 0)
                position = 2
                for _index in range(count):
                    if position + 8 > len(payload):
                        break
                    first_row, last_row, first_col, last_col = struct.unpack_from("<HHHH", payload, position)
                    position += 8
                    merged_ranges.append((first_row, last_row, first_col, last_col))
        except (struct.error, IndexError):
            continue

    if not cells:
        return []
    max_row = max(row for row, _ in cells)
    max_col = max(col for _, col in cells)
    if max_row + 1 > 200_000 or max_col + 1 > 5_000 or len(cells) > _MAX_CELLS:
        raise ValueError("这个 .xls 的数据范围异常大，请用 Excel 另存为 .xlsx")
    grid = [["" for _ in range(max_col + 1)] for _ in range(max_row + 1)]
    for (row, col), value in cells.items():
        grid[row][col] = clean_text(value)
    # 合并单元格只有左上角有值；把值填充到整个区域（常见于部门/单位列）
    filled = 0
    for first_row, last_row, first_col, last_col in merged_ranges:
        if first_row >= len(grid) or first_col >= len(grid[0]):
            continue
        value = grid[first_row][first_col]
        if not value:
            continue
        for row in range(first_row, min(last_row, len(grid) - 1) + 1):
            for col in range(first_col, min(last_col, len(grid[0]) - 1) + 1):
                if not grid[row][col]:
                    grid[row][col] = value
                    filled += 1
                    if filled > _MAX_CELLS:
                        break
            if filled > _MAX_CELLS:
                break
    return grid


def _parse_label_string(data: bytes, offset: int, unicode8: bool, codepage: int) -> str:
    if offset + 2 > len(data):
        return ""
    length = _u16(data, offset)
    if unicode8:
        if offset + 3 > len(data):
            return ""
        flags = data[offset + 2]
        start = offset + 3
        width = 2 if flags & 0x01 else 1
        raw = data[start : start + length * width]
        return raw.decode("utf-16-le", "replace") if width == 2 else raw.decode("latin-1", "replace")
    raw = data[offset + 2 : offset + 2 + length]
    return raw.decode(_codepage_name(codepage), "replace")


def _codepage_name(codepage: int) -> str:
    mapping = {1200: "utf-16-le", 1252: "cp1252", 936: "gbk", 950: "big5", 65001: "utf-8", 10000: "mac_roman"}
    if codepage in mapping:
        return mapping[codepage]
    try:
        return codecs.lookup(f"cp{codepage}").name
    except LookupError:
        return "gbk"


# --------------------------------------------------------------------------
# Excel 2003 XML / HTML / 文本
# --------------------------------------------------------------------------


def _decode_text(data: bytes) -> str:
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    if data[:200].count(b"\x00") > 40:
        try:
            return data.decode("utf-16-le", "replace")
        except UnicodeDecodeError:
            pass
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_xml_spreadsheet(text: str) -> list[RawSheet]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"Excel 2003 XML 解析失败：{exc}") from exc
    sheets: list[RawSheet] = []
    for worksheet in root.iter():
        if _local(worksheet.tag) != "Worksheet":
            continue
        name = ""
        for key, value in worksheet.attrib.items():
            if _local(key) == "Name":
                name = value
                break
        rows: list[list[str]] = []
        for row_element in worksheet.iter():
            if _local(row_element.tag) != "Row":
                continue
            cells: list[str] = []
            for cell in list(row_element):
                if _local(cell.tag) != "Cell":
                    continue
                index = 0
                for key, value in cell.attrib.items():
                    if _local(key) == "Index" and value.isdigit():
                        index = int(value)
                if index:
                    while len(cells) < index - 1:
                        cells.append("")
                data_text = ""
                for data_element in cell.iter():
                    if _local(data_element.tag) == "Data":
                        data_text = "".join(data_element.itertext())
                        break
                cells.append(clean_text(data_text))
            rows.append(cells)
        rows = _trim_grid(rows)
        if rows:
            sheets.append(RawSheet(name=clean_text(name) or f"Sheet{len(sheets) + 1}", rows=rows))
    if not sheets:
        raise ValueError("Excel 2003 XML 里没有工作表")
    return sheets


class _HtmlTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            if self._depth == 0:
                self._table = []
            self._depth += 1
        elif self._depth == 1 and tag == "tr":
            self._row = []
        elif self._depth == 1 and tag in {"td", "th"}:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "table":
            if self._depth == 1 and self._table is not None:
                self.tables.append(self._table)
                self._table = None
            self._depth = max(0, self._depth - 1)
        elif self._depth == 1 and tag == "tr":
            if self._row is not None:
                if self._table is not None:
                    self._table.append(self._row)
                self._row = None
        elif self._depth == 1 and tag in {"td", "th"}:
            if self._row is not None:
                self._row.append(clean_text("".join(self._cell or [])))
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _parse_html_tables(text: str) -> list[RawSheet]:
    parser = _HtmlTableParser()
    parser.feed(text)
    parser.close()
    sheets: list[RawSheet] = []
    for index, table in enumerate(parser.tables, start=1):
        rows = _trim_grid(table)
        if rows:
            sheets.append(RawSheet(name=f"Sheet{index}", rows=rows))
    if not sheets:
        raise ValueError("HTML 里没有找到可读的表格")
    return sheets


def _parse_text_table(text: str, name: str) -> list[RawSheet]:
    sample_lines = [line for line in text.splitlines()[:20] if line.strip()]
    sample = "\n".join(sample_lines)
    delimiter = "\t" if sample.count("\t") >= sample.count(",") else ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        delimiter = dialect.delimiter
    except csv.Error:
        pass
    rows = [[clean_text(cell) for cell in row] for row in csv.reader(text.splitlines(), delimiter=delimiter)]
    rows = _trim_grid(rows)
    if not rows:
        raise ValueError("文件内容不是可读的表格")
    return [RawSheet(name=name, rows=rows)]


def _trim_grid(grid: list[list[str]]) -> list[list[str]]:
    while grid and not any(cell.strip() for cell in grid[-1]):
        grid.pop()
    if not grid:
        return []
    max_cols = max(len(row) for row in grid)
    last_col = -1
    for row in grid:
        for index, cell in enumerate(row):
            if cell.strip():
                last_col = max(last_col, index)
    if last_col < 0:
        return []
    result: list[list[str]] = []
    for row in grid:
        padded = list(row) + [""] * (max_cols - len(row))
        result.append(padded[: last_col + 1])
    return result
