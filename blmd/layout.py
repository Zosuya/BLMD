"""區塊清單 → 排好版的繪製指令與點擊熱區。

不 import bpy / blf：量字寬、查圖片大小都由呼叫端傳進來（Measurer），
這樣不開 Blender 也能測試排版。座標一律以「文件頂端 = 0、往下為正」表示，
畫的時候再換成區塊座標並扣掉捲動量。
"""

import re
from dataclasses import dataclass

from . import parser as md


# ---------------------------------------------------------------- 輸出

@dataclass
class TextOp:
    x: float
    y: float  # 基線
    text: str
    size: float
    color: tuple
    mono: bool = False
    bold: bool = False


@dataclass
class RectOp:
    x: float
    y: float  # 頂端
    w: float
    h: float
    color: tuple


@dataclass
class CheckOp:
    x: float
    y: float
    size: float
    checked: bool


@dataclass
class ImageOp:
    x: float
    y: float
    w: float
    h: float
    src: str


@dataclass
class Hotspot:
    x: float
    y: float
    w: float
    h: float
    kind: str  # "check" / "link"
    payload: object  # check: (行號, 欄位)；link: 目標字串

    def contains(self, px, py):
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h


@dataclass
class Layout:
    ops: list
    hotspots: list
    height: float


class Measurer:
    """呼叫端實作：measure 回傳字寬；image_size 回傳 (寬, 高) 或 None。"""

    def measure(self, text, size, mono):
        raise NotImplementedError

    def image_size(self, src):
        return None


# ---------------------------------------------------------------- 樣式

PALETTE = {
    "bg": (0.12, 0.12, 0.13, 1.0),
    "text": (0.86, 0.86, 0.86, 1.0),
    "dim": (0.62, 0.62, 0.64, 1.0),
    "heading": (0.95, 0.95, 0.95, 1.0),
    "link": (0.40, 0.65, 1.00, 1.0),
    "code": (0.92, 0.75, 0.55, 1.0),
    "code_bg": (0.18, 0.18, 0.20, 1.0),
    "rule": (0.30, 0.30, 0.32, 1.0),
    "quote_bar": (0.35, 0.35, 0.40, 1.0),
    "table_head": (0.17, 0.17, 0.19, 1.0),
}

HEADING_SCALE = {1: 1.9, 2: 1.5, 3: 1.25, 4: 1.1, 5: 1.0, 6: 1.0}

# CJK、全形符號一個字一個單位，可以在任意字之間斷行；其餘以空白切單字
_CJK = "⺀-鿿가-힯　-〿＀-￯豈-﫿"
_TOKEN = re.compile(rf"[{_CJK}]|\s+|[^\s{_CJK}]+")


# ---------------------------------------------------------------- 換行

@dataclass
class _Seg:
    x: float
    w: float
    text: str
    span: md.Span


def _wrap(spans, width, size, m, mono_all=False):
    """把 spans 排進寬度 width，回傳每一行的 [_Seg]（x 從 0 起算）。"""
    lines = [[]]
    x = 0.0

    def place(tok, w, span):
        nonlocal x
        line = lines[-1]
        if line and line[-1].span is span and line[-1].x + line[-1].w == x:
            line[-1].text += tok
            line[-1].w += w
        else:
            line.append(_Seg(x, w, tok, span))
        x += w

    def newline():
        nonlocal x
        lines.append([])
        x = 0.0

    for span in spans:
        mono = mono_all or span.code
        for tok in _TOKEN.findall(span.text):
            w = m.measure(tok, size, mono)
            if tok.isspace():
                # 換行後的行首空白不畫；但程式碼第一行的縮排要留
                if x == 0 and not (mono_all and len(lines) == 1):
                    continue
                if x + w > width:
                    newline()
                    continue
                place(tok, w, span)
                continue
            if x + w > width and x > 0:
                newline()
            if w > width:
                # 單字比整行還寬，只好逐字切
                for ch in tok:
                    cw = m.measure(ch, size, mono)
                    if x + cw > width and x > 0:
                        newline()
                    place(ch, cw, span)
                continue
            place(tok, w, span)

    # 行尾空白不畫
    for line in lines:
        if line and line[-1].text.isspace():
            line.pop()
    return lines


class _Builder:
    def __init__(self, width, scale, m):
        self.s = scale
        self.m = m
        self.pad = 16 * scale
        self.body = 15 * scale
        self.width = width
        self.ops = []
        self.hot = []
        self.y = self.pad

    # ---- 共用：把一串 spans 排成多行畫出來
    def spans(self, spans, x0, width, size, color, *, bold=False, mono_all=False):
        lh = size * 1.45
        for line in _wrap(spans, max(width, size * 2), size, self.m, mono_all):
            base = self.y + size * 1.05
            for seg in line:
                self.segment(seg, x0, base, size, color, bold, mono_all)
            self.y += lh

    def segment(self, seg, x0, base, size, color, bold, mono_all):
        sp = seg.span
        x = x0 + seg.x
        s = self.s
        c = color
        if sp.link:
            c = PALETTE["link"]
        elif sp.code and not mono_all:
            c = PALETTE["code"]
            self.ops.append(RectOp(x - 2 * s, base - size * 1.0, seg.w + 4 * s, size * 1.3, PALETTE["code_bg"]))
        self.ops.append(TextOp(x, base, seg.text, size, c, sp.code or mono_all, bold or sp.bold))
        if sp.link:
            self.ops.append(RectOp(x, base + 2 * s, seg.w, max(1.0, s), c))
            self.hot.append(Hotspot(x, base - size * 1.05, seg.w, size * 1.45, "link", sp.link))
        if sp.strike:
            self.ops.append(RectOp(x, base - size * 0.32, seg.w, max(1.0, s), c))

    def gap(self, k=1.0):
        self.y += self.body * 0.6 * k

    # ---- 各種區塊
    def heading(self, b, first):
        size = self.body * HEADING_SCALE.get(b.level, 1.0)
        if not first:
            self.y += size * 0.5
        self.spans(b.spans, self.pad, self.width - 2 * self.pad, size, PALETTE["heading"], bold=True)
        if b.level <= 2:
            self.y += size * 0.2
            self.ops.append(RectOp(self.pad, self.y, self.width - 2 * self.pad, max(1.0, self.s), PALETTE["rule"]))
            self.y += self.body * 0.5
        else:
            self.y += self.body * 0.2

    def paragraph(self, b):
        for line in b.lines:
            self.spans(line, self.pad, self.width - 2 * self.pad, self.body, PALETTE["text"])

    def list_item(self, b):
        s = self.s
        size = self.body
        x = self.pad + b.indent * 22 * s
        base = self.y + size * 1.05
        if b.checked is not None:
            box = size * 0.95
            top = base - size * 0.85
            self.ops.append(CheckOp(x, top, box, b.checked))
            self.hot.append(Hotspot(x - 3 * s, top - 3 * s, box + 6 * s, box + 6 * s, "check", (b.line, b.check_col)))
            tx = x + box + 8 * s
        elif b.marker == "•":
            self.ops.append(TextOp(x + 2 * s, base, "•", size, PALETTE["dim"]))
            tx = x + 16 * s
        else:
            self.ops.append(TextOp(x, base, b.marker, size, PALETTE["dim"]))
            tx = x + max(self.m.measure(b.marker, size, False) + 6 * s, 20 * s)
        color = PALETTE["dim"] if b.checked else PALETTE["text"]
        start = self.y
        self.spans(b.spans, tx, self.width - self.pad - tx, size, color)
        if self.y == start:  # 空項目也要佔一行
            self.y += size * 1.45

    def code(self, b):
        s = self.s
        size = self.body * 0.9
        inner = 10 * s
        top = self.y
        rect = RectOp(self.pad, top, self.width - 2 * self.pad, 0, PALETTE["code_bg"])
        self.ops.append(rect)
        self.y += inner
        w = self.width - 2 * self.pad - 2 * inner
        for line in b.lines or [""]:
            if not line:
                self.y += size * 1.45
                continue
            self.spans([md.Span(line.expandtabs(4))], self.pad + inner, w, size, PALETTE["code"], mono_all=True)
        self.y += inner
        rect.h = self.y - top
        self.gap(0.5)

    def quote(self, b):
        s = self.s
        top = self.y
        x = self.pad + 14 * s
        for line in b.lines:
            if line:
                self.spans(line, x, self.width - self.pad - x, self.body, PALETTE["dim"])
            else:
                self.y += self.body * 1.45
        self.ops.append(RectOp(self.pad, top, 3 * s, self.y - top, PALETTE["quote_bar"]))

    def rule(self):
        self.y += self.body * 0.6
        self.ops.append(RectOp(self.pad, self.y, self.width - 2 * self.pad, max(1.0, self.s), PALETTE["rule"]))
        self.y += self.body * 0.6

    def table(self, b):
        s = self.s
        m = self.m
        size = self.body
        cell_pad = 8 * s
        ncol = len(b.header)
        avail = self.width - 2 * self.pad
        all_rows = [b.header] + b.rows
        checks = [[None] * ncol] + (b.checks or [[None] * ncol for _ in b.rows])
        box = size * 0.95
        box_w = box + 6 * s  # 勾選框加上它跟字之間的空隙

        def natural(spans, chk):
            return sum(m.measure(sp.text, size, sp.code) for sp in spans) + (box_w if chk else 0)

        nat = [max(natural(r[c], k[c]) for r, k in zip(all_rows, checks)) + 2 * cell_pad for c in range(ncol)]
        if sum(nat) <= avail:
            widths = nat
        else:
            # 太寬：照自然寬度的比例分配，但每欄至少留一點空間，內容自動換行
            floor = min(60 * s, avail / ncol)
            widths = [floor] * ncol
            rest = avail - floor * ncol
            extra = [max(n - floor, 0) for n in nat]
            total = sum(extra) or 1
            widths = [w + rest * e / total for w, e in zip(widths, extra)]

        grid = PALETTE["rule"]
        line_w = max(1.0, s)
        top = self.y
        xs = [self.pad]
        for w in widths:
            xs.append(xs[-1] + w)
        for r, row in enumerate(all_rows):
            row_top = self.y
            heights = []
            ops_before = len(self.ops)
            for c in range(ncol):
                self.y = row_top + cell_pad * 0.6
                chk = checks[r][c]
                lead = box_w if chk else 0.0  # 勾選框佔掉的寬度，每行的字都往右讓
                inner = widths[c] - 2 * cell_pad - lead
                lines = _wrap(row[c], max(inner, size), size, m)
                lh = size * 1.45
                for li, line in enumerate(lines):
                    lw = (line[-1].x + line[-1].w if line else 0) + lead
                    if b.aligns[c] == "right":
                        x0 = xs[c] + widths[c] - cell_pad - lw
                    elif b.aligns[c] == "center":
                        x0 = xs[c] + (widths[c] - lw) / 2
                    else:
                        x0 = xs[c] + cell_pad
                    base = self.y + size * 1.05
                    if chk and li == 0:
                        checked, line_no, col = chk
                        btop = base - size * 0.85
                        self.ops.append(CheckOp(x0, btop, box, checked))
                        self.hot.append(Hotspot(x0 - 3 * s, btop - 3 * s, box + 6 * s, box + 6 * s, "check", (line_no, col)))
                    x0 += lead
                    for seg in line:
                        self.segment(seg, x0, base, size, PALETTE["heading"] if r == 0 else PALETTE["text"], r == 0, False)
                    self.y += lh
                heights.append(self.y - row_top + cell_pad * 0.6)
            row_h = max(heights)
            if r == 0:
                self.ops.insert(ops_before, RectOp(xs[0], row_top, xs[-1] - xs[0], row_h, PALETTE["table_head"]))
            self.y = row_top + row_h
            self.ops.append(RectOp(xs[0], self.y, xs[-1] - xs[0], line_w, grid))
        # 外框與直線
        self.ops.append(RectOp(xs[0], top, xs[-1] - xs[0], line_w, grid))
        for x in xs:
            self.ops.append(RectOp(x, top, line_w, self.y - top, grid))
        self.y += line_w
        self.gap(0.5)

    def image(self, b):
        size = self.m.image_size(b.src)
        avail = self.width - 2 * self.pad
        if not size or not size[0] or not size[1]:
            self.spans([md.Span(f"[image not found: {b.src}]")], self.pad, avail, self.body, PALETTE["dim"])
            return
        w, h = size
        w = w * self.s
        h = h * self.s
        if w > avail:
            h *= avail / w
            w = avail
        self.ops.append(ImageOp(self.pad, self.y, w, h, b.src))
        self.y += h + self.body * 0.4


def build(blocks, width, scale, measurer):
    b = _Builder(width, scale, measurer)
    first = True
    for blk in blocks:
        if isinstance(blk, md.Blank):
            b.gap()
            continue
        if isinstance(blk, md.Heading):
            b.heading(blk, first)
        elif isinstance(blk, md.Paragraph):
            b.paragraph(blk)
        elif isinstance(blk, md.ListItem):
            b.list_item(blk)
        elif isinstance(blk, md.CodeBlock):
            b.code(blk)
        elif isinstance(blk, md.Quote):
            b.quote(blk)
        elif isinstance(blk, md.Rule):
            b.rule()
        elif isinstance(blk, md.Table):
            b.table(blk)
        elif isinstance(blk, md.Image):
            b.image(blk)
        first = False
    return Layout(b.ops, b.hot, b.y + b.pad)


# ---------------------------------------------------------------- 捲軸
# 座標用區塊座標（底部 = 0、往上為正），跟畫圖和滑鼠事件一致。


def _thumb_h(view_h, total, scale):
    return min(view_h, max(view_h * view_h / total, 24 * scale))


def scrollbar_thumb(view_h, scroll, total, scale):
    """捲軸滑塊的 (頂端, 高度)。內容沒超出畫面就沒有捲軸，回傳 None。"""
    if total <= view_h:
        return None
    h = _thumb_h(view_h, total, scale)
    return view_h - scroll / (total - view_h) * (view_h - h), h


def scroll_for_thumb(view_h, top, total, scale):
    """反過來算：滑塊頂端被拖到 top 時，捲動量是多少（夾在可捲範圍內）。"""
    if total <= view_h:
        return 0.0
    h = _thumb_h(view_h, total, scale)
    if view_h <= h:
        return 0.0
    frac = (view_h - top) / (view_h - h)
    return min(max(frac, 0.0), 1.0) * (total - view_h)
