"""把排版結果畫到預覽區上（blf 畫字、gpu 畫方塊、勾選框、圖片）。"""

import os
from urllib.parse import unquote

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from . import layout as lay
from . import parser as md
from . import preview

_fonts = {"regular": 0, "mono": 0, "mono_path": None}
_handle = None
_cache = {}  # (文字名稱, 內容雜湊, 寬度, 縮放) → Layout
_measure_cache = {}
failed_images = set()  # 載入失敗的 (src, base)，不再一直重試；文字內容變了就清掉重來


def _load_fonts():
    # system_resource 只認資料夾，直接給檔名會回傳空字串
    folder = bpy.utils.system_resource('DATAFILES', path="fonts")
    path = os.path.join(folder, "DejaVuSansMono.woff2") if folder else ""
    if path and os.path.exists(path):
        fid = blf.load(path)
        if fid != -1:
            _fonts["mono"] = fid
            _fonts["mono_path"] = path


def _unload_fonts():
    if _fonts["mono_path"]:
        blf.unload(_fonts["mono_path"])
    _fonts["mono"] = 0
    _fonts["mono_path"] = None


# ---------------------------------------------------------------- 圖片

def _image_base(text):
    """相對路徑以這份文字的檔案位置為準；內嵌文字則以 .blend 所在資料夾為準。"""
    if text is not None and text.filepath and not text.is_in_memory:
        return os.path.dirname(bpy.path.abspath(text.filepath))
    if bpy.data.filepath:
        return os.path.dirname(bpy.data.filepath)
    return None


def _file_path(src, base):
    if src.startswith("//"):
        return bpy.path.abspath(src)
    if os.path.isabs(src):
        return src
    if base:
        return os.path.normpath(os.path.join(base, src))
    return None


def find_image(src, base):
    """回傳 bpy Image；還沒載入就回傳 None。"""
    if src.startswith("bl:image/"):
        return bpy.data.images.get(unquote(src[len("bl:image/") :]))
    img = bpy.data.images.get(src)
    if img is not None:
        return img
    if "://" in src:
        return None  # 不支援網路圖片
    path = _file_path(src, base)
    if not path:
        return None
    norm = os.path.normcase(os.path.normpath(path))
    for img in bpy.data.images:
        if img.filepath and os.path.normcase(os.path.normpath(bpy.path.abspath(img.filepath))) == norm:
            return img
    return None


def load_image_file(src, base):
    """由計時器呼叫（畫圖時不能新增資料）。載入的圖片沒有使用者，存檔時 Blender 不會存進去。"""
    path = None if src.startswith("bl:") or "://" in src else _file_path(src, base)
    if path and os.path.isfile(path):
        try:
            bpy.data.images.load(path, check_existing=True)
            return
        except RuntimeError as e:
            print("BLMD: cannot load image", path, e)
    failed_images.add((src, base))


class _BlfMeasurer(lay.Measurer):
    def __init__(self, base):
        self.base = base
        self.missing = set()

    def measure(self, text, size, mono):
        key = (text, size, mono)
        w = _measure_cache.get(key)
        if w is None:
            fid = _fonts["mono"] if mono else _fonts["regular"]
            blf.size(fid, size)
            w = blf.dimensions(fid, text)[0]
            if len(_measure_cache) > 20000:
                _measure_cache.clear()
            _measure_cache[key] = w
        return w

    def image_size(self, src):
        img = find_image(src, self.base)
        if img is None:
            if (src, self.base) not in failed_images:
                self.missing.add(src)
            return None
        return tuple(img.size)


# ---------------------------------------------------------------- 畫

_shader = None


def _rect(x, y, w, h, color):
    sh = _shader
    batch = batch_for_shader(
        sh, 'TRIS', {"pos": [(x, y), (x + w, y), (x + w, y + h), (x, y), (x + w, y + h), (x, y + h)]}
    )
    sh.uniform_float("color", color)
    batch.draw(sh)


def _frame(x, y, w, h, t, color):
    _rect(x, y, w, t, color)
    _rect(x, y + h - t, w, t, color)
    _rect(x, y, t, h, color)
    _rect(x + w - t, y, t, h, color)


def _scale(context):
    return context.preferences.system.ui_scale


def draw_preview():
    global _shader
    context = bpy.context
    area = context.area
    if not preview.is_preview(area):
        return
    region = context.region
    text = preview.preview_text(area)
    scale = _scale(context)
    W, H = region.width, region.height

    _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    _shader.bind()
    _rect(0, 0, W, H, lay.PALETTE["bg"])

    if text is None:
        _message(W, H, scale, "No text selected. Pick one in the header.")
        gpu.state.blend_set('NONE')
        return

    content = text.as_string()
    base = _image_base(text)
    key = (text.name, hash(content), W, scale)
    result = _cache.get(key)
    if result is None:
        m = _BlfMeasurer(base)
        result = lay.build(md.parse(content), W, scale, m)
        if m.missing:
            for src in m.missing:
                preview.want_images.add((src, base))
        else:
            if len(_cache) > 32:
                _cache.clear()
            _cache[key] = result  # 圖片還沒載完的版本不快取，載完會重排

    max_scroll = max(0.0, result.height - H)
    sc = min(preview.scroll.get(text.name, 0.0), max_scroll)
    preview.scroll[text.name] = sc
    preview.last_draw[area.as_pointer()] = (result, text.name, H)

    def ry(y):  # 文件座標（往下為正）→ 區塊座標（往上為正）
        return H - (y - sc)

    pad_view = 40 * scale
    for op in result.ops:
        if isinstance(op, lay.TextOp):
            yy = ry(op.y)
            if yy < -pad_view or yy > H + pad_view:
                continue
            fid = _fonts["mono"] if op.mono else _fonts["regular"]
            blf.size(fid, op.size)
            blf.color(fid, *op.color)
            blf.position(fid, op.x, yy, 0)
            blf.draw(fid, op.text)
            if op.bold:  # blf 沒有粗體，錯開一點重畫一次
                blf.position(fid, op.x + max(1.0, round(scale * 0.8)), yy, 0)
                blf.draw(fid, op.text)
            _shader.bind()
        elif isinstance(op, lay.RectOp):
            top, bottom = ry(op.y), ry(op.y + op.h)
            if top < 0 or bottom > H:  # 整塊在畫面外
                continue
            _rect(op.x, bottom, op.w, op.h, op.color)
        elif isinstance(op, lay.CheckOp):
            top = ry(op.y)
            if top < -pad_view or top > H + pad_view:
                continue
            _draw_check(op.x, top - op.size, op.size, op.checked, scale)
        elif isinstance(op, lay.ImageOp):
            top = ry(op.y)
            if top < 0 or top - op.h > H:
                continue
            _draw_image(op, top, base)

    thumb = lay.scrollbar_thumb(H, sc, result.height, scale)
    if thumb is not None:
        _scrollbar(W, thumb, scale)
    gpu.state.blend_set('NONE')


def _draw_check(x, y, size, checked, scale):
    t = max(1.0, round(scale * 1.5))
    if checked:
        _rect(x, y, size, size, lay.PALETTE["link"])
        # 用兩段粗線畫 ✓，不依賴字型裡有沒有這個符號
        _check_mark(x, y, size, scale)
    else:
        _frame(x, y, size, size, t, lay.PALETTE["dim"])


def _check_mark(x, y, s, scale):
    sh = _shader
    pts = [(x + s * 0.22, y + s * 0.52), (x + s * 0.42, y + s * 0.30), (x + s * 0.78, y + s * 0.72)]
    gpu.state.line_width_set(max(1.5, 2.0 * scale))
    batch = batch_for_shader(sh, 'LINE_STRIP', {"pos": pts})
    sh.uniform_float("color", (1, 1, 1, 1))
    batch.draw(sh)
    gpu.state.line_width_set(1.0)


def _draw_image(op, top, base):
    img = find_image(op.src, base)
    if img is None:
        return
    try:
        tex = gpu.texture.from_image(img)
    except Exception:
        return
    sh = gpu.shader.from_builtin('IMAGE')
    x, y, w, h = op.x, top - op.h, op.w, op.h
    batch = batch_for_shader(
        sh,
        'TRI_FAN',
        {"pos": [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], "texCoord": [(0, 0), (1, 0), (1, 1), (0, 1)]},
    )
    sh.bind()
    sh.uniform_sampler("image", tex)
    batch.draw(sh)
    _shader.bind()


def _scrollbar(W, thumb, scale):
    top, h = thumb
    bar_w = 4 * scale
    _rect(W - bar_w - 3 * scale, top - h, bar_w, h, (1, 1, 1, 0.18))


def _message(W, H, scale, msg):
    size = 14 * scale
    blf.size(0, size)
    blf.color(0, *lay.PALETTE["dim"])
    blf.position(0, 16 * scale, H - 30 * scale, 0)
    blf.draw(0, msg)


def clear_cache():
    _cache.clear()
    _measure_cache.clear()


def register():
    global _handle
    _load_fonts()
    _handle = bpy.types.SpaceInfo.draw_handler_add(draw_preview, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _handle
    if _handle is not None:
        bpy.types.SpaceInfo.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
    _unload_fonts()
    clear_cache()
