"""預覽區的滑鼠：滾輪、點擊、游標形狀。

全部用快捷鍵規則（keymap），沒有常駐的背景監看程式（modal operator）——
常駐的 modal 會讓 Blender 的自動存檔一直延後，等於關掉自動存檔。
滾輪和拖捲軸放在 View2D 那組，因為資訊視窗是在 View2D 那層處理滾輪和捲軸的。
"""

import bpy

from . import layout as lay
from . import links, preview


def _hit(context, event):
    """回傳 (layout 資料, 文件座標 x, y)。沒畫過就回傳 None。"""
    info = preview.last_draw.get(context.area.as_pointer())
    if info is None:
        return None
    result, text_name, height = info
    sc = preview.scroll.get(text_name, 0.0)
    x = event.mouse_region_x
    y = (context.region.height - event.mouse_region_y) + sc
    return result, x, y


def _hotspot_at(context, event):
    hit = _hit(context, event)
    if hit is None:
        return None
    result, x, y = hit
    for h in result.hotspots:
        if h.contains(x, y):
            return h
    return None


class _PreviewOp:
    @classmethod
    def poll(cls, context):
        return context.region is not None and context.region.type == 'WINDOW' and preview.is_preview(context.area)


class BLMD_OT_preview_scroll(_PreviewOp, bpy.types.Operator):
    bl_idname = "blmd.preview_scroll"
    bl_label = "Scroll Markdown Preview"
    bl_options = {'INTERNAL'}

    lines: bpy.props.FloatProperty(default=3.0)
    to_edge: bpy.props.EnumProperty(items=[('NONE', "None", ""), ('TOP', "Top", ""), ('BOTTOM', "Bottom", "")])

    def invoke(self, context, event):
        text = preview.preview_text(context.area)
        if text is None:
            return {'CANCELLED'}
        info = preview.last_draw.get(context.area.as_pointer())
        max_scroll = max(0.0, info[0].height - info[2]) if info else 0.0
        step = 15 * 1.45 * context.preferences.system.ui_scale
        if self.to_edge == 'TOP':
            sc = 0.0
        elif self.to_edge == 'BOTTOM':
            sc = max_scroll
        else:
            sc = preview.scroll.get(text.name, 0.0) + self.lines * step
        preview.scroll[text.name] = min(max(sc, 0.0), max_scroll)
        context.area.tag_redraw()
        return {'FINISHED'}


class BLMD_OT_preview_scrollbar(_PreviewOp, bpy.types.Operator):
    """拖右邊的捲軸。

    資訊視窗右緣那一條是 Blender 自己的捲軸地盤，點下去會被 View2D 那組的
    「拖捲軸」接走，捲的是底下（空的）資訊視窗，預覽不動。所以同樣掛在 View2D 組、
    搶在它前面接手。只在拖的那一下跑 modal，放開就結束，不會擋自動存檔。
    """

    bl_idname = "blmd.preview_scrollbar"
    bl_label = "Drag Markdown Preview Scrollbar"
    bl_options = {'INTERNAL'}

    def _apply(self, context, mouse_y):
        sc = lay.scroll_for_thumb(self._h, mouse_y + self._grab, self._total, self._scale)
        preview.scroll[self._text] = sc
        context.area.tag_redraw()

    def invoke(self, context, event):
        info = preview.last_draw.get(context.area.as_pointer())
        if info is None:
            return {'PASS_THROUGH'}
        result, text_name, H = info
        scale = context.preferences.system.ui_scale
        # 熱區比畫出來的細條寬一點，好點；排版左右各留 16 像素，碰不到內文
        if event.mouse_region_x < context.region.width - 14 * scale:
            return {'PASS_THROUGH'}
        thumb = lay.scrollbar_thumb(H, preview.scroll.get(text_name, 0.0), result.height, scale)
        if thumb is None:
            return {'FINISHED'}  # 沒東西可捲，也別讓底下的資訊視窗去捲
        top, h = thumb
        y = event.mouse_region_y
        self._text, self._h, self._total, self._scale = text_name, H, result.height, scale
        self._orig = preview.scroll.get(text_name, 0.0)
        if top - h <= y <= top:
            self._grab = top - y  # 抓在滑塊上：保持抓的位置
        else:
            self._grab = h / 2  # 點在軌道上：滑塊中心跳到滑鼠這裡
            self._apply(context, y)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            self._apply(context, event.mouse_region_y)
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            return {'FINISHED'}
        elif event.type in {'ESC', 'RIGHTMOUSE'}:
            preview.scroll[self._text] = self._orig
            context.area.tag_redraw()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class BLMD_OT_preview_click(_PreviewOp, bpy.types.Operator):
    bl_idname = "blmd.preview_click"
    bl_label = "Click Markdown Preview"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        h = _hotspot_at(context, event)
        # 點在預覽區但沒點中東西也要吃掉，不然資訊視窗會去選取訊息
        if h is None:
            return {'FINISHED'}
        if h.kind == "check":
            line, col = h.payload
            ok, msg = toggle_check(context, preview.preview_text(context.area), line, col)
        else:
            ok, msg = links.open_link(context, h.payload)
        if not ok:
            self.report({'WARNING'}, msg)
        return {'FINISHED'}


class BLMD_OT_preview_hover(_PreviewOp, bpy.types.Operator):
    bl_idname = "blmd.preview_hover"
    bl_label = "Hover Markdown Preview"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        h = _hotspot_at(context, event)
        context.window.cursor_set('HAND_POINT' if h else 'DEFAULT')
        return {'PASS_THROUGH'}


# ---------------------------------------------------------------- 勾選框

def _find_text_area(context, text):
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'TEXT_EDITOR' and area.spaces.active.text == text:
                return win, area
    return None, None


def _replace_char(context, win, area, text, line, col, ch):
    """用文字編輯器自己的「輸入文字」操作改字，之後把游標放回原處。

    第二個參數 True 要求這次操作推一步復原紀錄——從 Python 呼叫的操作預設不推，
    不加的話 Ctrl+Z 退不掉這次打勾。
    """
    region = next(r for r in area.regions if r.type == 'WINDOW')
    cur = (text.current_line_index, text.current_character, text.select_end_line_index, text.select_end_character)
    with context.temp_override(window=win, area=area, region=region, space_data=area.spaces.active):
        text.select_set(line, col, line, col + 1)
        bpy.ops.text.insert('EXEC_DEFAULT', True, text=ch)
    text.select_set(*cur)


def toggle_check(context, text, line, col):
    if text is None or line >= len(text.lines):
        return False, "Text changed, try again"
    body = text.lines[line].body
    if col >= len(body) or body[col] not in " xX" or body[col - 1] != "[":
        return False, "Text changed, try again"
    ch = " " if body[col] in "xX" else "x"

    win, area = _find_text_area(context, text)
    if area is not None:
        _replace_char(context, win, area, text, line, col, ch)
    else:
        # 沒有開著這份文字的編輯器：把預覽區暫時切回文字編輯器做，做完切回來。
        # 不能在點擊處理中途換區塊種類（點擊所在的區塊會被換掉），延到計時器做；
        # 計時器和重畫之間不會畫畫面，看不到切換。
        win, area = context.window, context.area

        def run():
            ctx = bpy.context
            area.type = 'TEXT_EDITOR'
            try:
                _replace_char(ctx, win, area, text, line, col, ch)
            finally:
                area.type = 'INFO'
            preview.tag_previews(text)

        bpy.app.timers.register(run, first_interval=0.0)
    preview.tag_previews(text)
    return True, ""


# ---------------------------------------------------------------- 快捷鍵規則

_keymaps = []


def register():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:  # 背景模式沒有 keyconfig
        return
    km = kc.keymaps.new(name="View2D", space_type='EMPTY')
    for key, lines in (('WHEELUPMOUSE', -3.0), ('WHEELDOWNMOUSE', 3.0)):
        kmi = km.keymap_items.new(BLMD_OT_preview_scroll.bl_idname, key, 'PRESS')
        kmi.properties.lines = lines
        _keymaps.append((km, kmi))
    _keymaps.append((km, km.keymap_items.new(BLMD_OT_preview_scrollbar.bl_idname, 'LEFTMOUSE', 'PRESS')))

    km = kc.keymaps.new(name="Info", space_type='INFO')
    for key, lines, edge in (
        ('PAGE_UP', -15.0, 'NONE'),
        ('PAGE_DOWN', 15.0, 'NONE'),
        ('HOME', 0.0, 'TOP'),
        ('END', 0.0, 'BOTTOM'),
    ):
        kmi = km.keymap_items.new(BLMD_OT_preview_scroll.bl_idname, key, 'PRESS')
        kmi.properties.lines = lines
        kmi.properties.to_edge = edge
        _keymaps.append((km, kmi))
    _keymaps.append((km, km.keymap_items.new(BLMD_OT_preview_click.bl_idname, 'LEFTMOUSE', 'PRESS')))
    _keymaps.append((km, km.keymap_items.new(BLMD_OT_preview_hover.bl_idname, 'MOUSEMOVE', 'ANY')))
    _keymaps.append((km, km.keymap_items.new("blmd.toggle_preview", 'V', 'PRESS', ctrl=True, shift=True)))

    km = kc.keymaps.new(name="Text", space_type='TEXT_EDITOR')
    _keymaps.append((km, km.keymap_items.new("blmd.toggle_preview", 'V', 'PRESS', ctrl=True, shift=True)))
    kmi = km.keymap_items.new("blmd.preview_side", 'V', 'PRESS', ctrl=True, alt=True)
    _keymaps.append((km, kmi))


def unregister():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()


classes = (BLMD_OT_preview_scroll, BLMD_OT_preview_scrollbar, BLMD_OT_preview_click, BLMD_OT_preview_hover)
