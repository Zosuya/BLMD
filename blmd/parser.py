"""Markdown → 區塊清單。

純 Python，不 import bpy，才能不開 Blender 就跑測試。
只支援筆記常用的子集；換行一律保留（像 Obsidian），不把相鄰行併成一段。
"""

import re
from dataclasses import dataclass


# ---------------------------------------------------------------- 行內

@dataclass
class Span:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    strike: bool = False
    link: str | None = None


_ESCAPABLE = set("\\`*_{}[]()#+-.!|~<>")
_AUTOLINK = re.compile(r"https?://[^\s<>()\[\]]+")


def _find_closing(s, start, marker):
    """從 start 找下一個 marker，跳過反斜線跳脫。找不到回傳 -1。"""
    i = start
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s.startswith(marker, i):
            return i
        i += 1
    return -1


def _find_bracket_end(s, start):
    """s[start] 是 '['，找對應的 ']'（允許巢狀）。"""
    depth = 0
    i = start
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _link_target(s, start):
    """s[start] 是 '('，回傳 (目標, 結束位置)。目標可用 <...> 包住以容納空白。"""
    if start >= len(s) or s[start] != "(":
        return None, -1
    if s.startswith("<", start + 1):
        end = s.find(">", start + 2)
        if end != -1 and s.startswith(")", end + 1):
            return s[start + 2 : end], end + 1
        return None, -1
    depth = 0
    for i in range(start, len(s)):
        c = s[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                # [text](url "title") 的 title 不要；其餘空白照收，
                # 因為 bl:workspace/<名稱> 的名稱可能有空格
                target = re.sub(r'\s+"[^"]*"$', "", s[start + 1 : i].strip())
                return target, i
    return None, -1


def _is_word(c):
    return c.isalnum()


def parse_inline(s, *, bold=False, italic=False, strike=False, link=None):
    spans = []
    buf = []

    def flush():
        if buf:
            spans.append(Span("".join(buf), bold, italic, False, strike, link))
            buf.clear()

    def sub(text, **kw):
        flush()
        args = dict(bold=bold, italic=italic, strike=strike, link=link)
        args.update(kw)
        spans.extend(parse_inline(text, **args))

    i = 0
    n = len(s)
    while i < n:
        c = s[i]

        if c == "\\" and i + 1 < n and s[i + 1] in _ESCAPABLE:
            buf.append(s[i + 1])
            i += 2
            continue

        if c == "`":
            run = len(s[i:]) - len(s[i:].lstrip("`"))
            marker = "`" * run
            end = s.find(marker, i + run)
            if end != -1:
                flush()
                spans.append(Span(s[i + run : end], bold, italic, True, strike, link))
                i = end + run
                continue

        if c == "!" and s.startswith("![", i):
            end = _find_bracket_end(s, i + 1)
            if end != -1:
                target, tend = _link_target(s, end + 1)
                if target is not None:
                    # 行內圖片不畫圖，顯示替代文字（獨立成行的圖片由區塊層處理）
                    alt = s[i + 2 : end] or target
                    sub("[" + alt + "]", link=link)
                    i = tend + 1
                    continue

        if c == "[" and link is None:
            end = _find_bracket_end(s, i)
            if end != -1:
                target, tend = _link_target(s, end + 1)
                if target is not None:
                    sub(s[i + 1 : end], link=target)
                    i = tend + 1
                    continue

        if c in "*_" and s.startswith(c * 2, i):
            end = _find_closing(s, i + 2, c * 2)
            if end > i + 2:
                sub(s[i + 2 : end], bold=True)
                i = end + 2
                continue

        if c in "*_":
            prev_ok = c == "*" or i == 0 or not _is_word(s[i - 1])
            if prev_ok and i + 1 < n and not s[i + 1].isspace():
                end = i + 1
                while True:
                    end = _find_closing(s, end, c)
                    if end == -1:
                        break
                    # 跳過雙字元標記（那是粗體的一部分）
                    if s.startswith(c * 2, end):
                        end += 2
                        continue
                    next_ok = c == "*" or end + 1 >= n or not _is_word(s[end + 1])
                    if not s[end - 1].isspace() and next_ok:
                        break
                    end += 1
                if end != -1:
                    sub(s[i + 1 : end], italic=True)
                    i = end + 1
                    continue

        if c == "~" and s.startswith("~~", i):
            end = _find_closing(s, i + 2, "~~")
            if end > i + 2:
                sub(s[i + 2 : end], strike=True)
                i = end + 2
                continue

        if c == "h" and link is None and (i == 0 or not _is_word(s[i - 1])):
            m = _AUTOLINK.match(s, i)
            if m:
                url = m.group(0).rstrip(".,;:!?")
                flush()
                spans.append(Span(url, bold, italic, False, strike, url))
                i += len(url)
                continue

        buf.append(c)
        i += 1

    flush()
    return spans


# ---------------------------------------------------------------- 區塊

@dataclass
class Heading:
    level: int
    spans: list
    line: int


@dataclass
class Paragraph:
    lines: list  # 每個元素是一行的 spans
    line: int


@dataclass
class ListItem:
    indent: int  # 巢狀層級，0 起算
    marker: str  # "•" 或 "1." 這類
    checked: bool | None  # None 表示不是勾選項目
    spans: list
    line: int
    check_col: int = -1  # 勾選框裡那個字元在原文那一行的位置


@dataclass
class CodeBlock:
    lang: str
    lines: list
    line: int


@dataclass
class Quote:
    lines: list  # 每個元素是一行的 spans
    line: int


@dataclass
class Rule:
    line: int


@dataclass
class Table:
    header: list  # 每格是 spans
    aligns: list  # "left" / "center" / "right"
    rows: list  # list[list[spans]]
    line: int
    # 每列每格的勾選框：(已勾?, 原文行號, 欄位) 或 None。格子以 [ ] / [x] 開頭才算
    checks: list = None


@dataclass
class Image:
    alt: str
    src: str
    line: int


@dataclass
class Blank:
    line: int


_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([^`\s]*)")
_RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_LIST = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
_TASK = re.compile(r"^\[([ xX])\]\s+")
_IMAGE_LINE = re.compile(r"^\s*!\[([^\]]*)\]\(\s*<?([^)>]*?)>?\s*\)\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def _split_row(line):
    """回傳 [(格子文字, 格子內容在原文那一行的起始位置)]。"""
    start, end = 0, len(line)
    while start < end and line[start].isspace():
        start += 1
    while end > start and line[end - 1].isspace():
        end -= 1
    if start < end and line[start] == "|":
        start += 1
    if end > start and line[end - 1] == "|" and line[end - 2 : end] != "\\|":
        end -= 1
    cells, buf, cell_start, i = [], [], start, start

    def push():
        text = "".join(buf)
        lead = len(text) - len(text.lstrip())
        cells.append((text.strip(), cell_start + lead))

    while i < end:
        if line[i] == "\\" and i + 1 < end and line[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if line[i] == "|":
            push()
            buf = []
            cell_start = i + 1
        else:
            buf.append(line[i])
        i += 1
    push()
    return cells


_CELL_TASK = re.compile(r"^\[([ xX])\](\s+|$)")


def _align(cell):
    cell = cell.strip()
    left, right = cell.startswith(":"), cell.endswith(":")
    if left and right:
        return "center"
    if right:
        return "right"
    return "left"


def _indent_width(ws):
    return len(ws.expandtabs(4))


def parse(text):
    lines = text.split("\n")
    blocks = []
    i = 0
    n = len(lines)
    para = None  # 進行中的段落
    quote = None

    def end_runs():
        nonlocal para, quote
        para = None
        quote = None

    while i < n:
        raw = lines[i]

        if not raw.strip():
            end_runs()
            blocks.append(Blank(i))
            i += 1
            continue

        m = _FENCE.match(raw)
        if m:
            end_runs()
            fence = m.group(2)
            start = i
            body = []
            i += 1
            while i < n and not lines[i].strip().startswith(fence[0] * len(fence)):
                body.append(lines[i])
                i += 1
            blocks.append(CodeBlock(m.group(3), body, start))
            i += 1  # 跳過結尾的 fence（沒有結尾就吃到文件尾）
            continue

        m = _HEADING.match(raw)
        if m:
            end_runs()
            blocks.append(Heading(len(m.group(1)), parse_inline(m.group(2)), i))
            i += 1
            continue

        if _RULE.match(raw):
            end_runs()
            blocks.append(Rule(i))
            i += 1
            continue

        m = _IMAGE_LINE.match(raw)
        if m:
            end_runs()
            blocks.append(Image(m.group(1), m.group(2).strip(), i))
            i += 1
            continue

        if "|" in raw and i + 1 < n and _TABLE_SEP.match(lines[i + 1]) and "-" in lines[i + 1]:
            end_runs()
            header = [c for c, _ in _split_row(raw)]
            aligns = [_align(c) for c, _ in _split_row(lines[i + 1])]
            cols = len(header)
            aligns = (aligns + ["left"] * cols)[:cols]
            start = i
            i += 2
            rows, checks = [], []
            while i < n and lines[i].strip() and "|" in lines[i]:
                cells = (_split_row(lines[i]) + [("", -1)] * cols)[:cols]
                row, row_checks = [], []
                for text, col in cells:
                    t = _CELL_TASK.match(text)
                    if t:
                        row_checks.append((t.group(1) != " ", i, col + 1))
                        text = text[t.end():]
                    else:
                        row_checks.append(None)
                    row.append(parse_inline(text))
                rows.append(row)
                checks.append(row_checks)
                i += 1
            blocks.append(Table([parse_inline(c) for c in header], aligns, rows, start, checks))
            continue

        m = _LIST.match(raw)
        if m:
            end_runs()
            ws, marker, rest = m.groups()
            indent = _indent_width(ws) // 2
            checked = None
            check_col = -1
            t = _TASK.match(rest)
            if t:
                checked = t.group(1) != " "
                check_col = raw.index("[", len(ws) + len(marker)) + 1
                rest = rest[t.end():]
            shown = "•" if marker in "-*+" else marker[:-1] + "."
            blocks.append(ListItem(indent, shown, checked, parse_inline(rest), i, check_col))
            i += 1
            continue

        if raw.lstrip().startswith(">"):
            para = None
            body = re.sub(r"^\s*>\s?", "", raw)
            if quote is None:
                quote = Quote([], i)
                blocks.append(quote)
            quote.lines.append(parse_inline(body))
            i += 1
            continue

        quote = None
        if para is None:
            para = Paragraph([], i)
            blocks.append(para)
        para.lines.append(parse_inline(raw.strip()))
        i += 1

    return blocks


def toggle_checkbox_line(line_text, check_col):
    """回傳把勾選框反轉後的那一行（給測試和外掛共用的判斷）。"""
    c = line_text[check_col]
    return line_text[:check_col] + (" " if c in "xX" else "x") + line_text[check_col + 1 :]
