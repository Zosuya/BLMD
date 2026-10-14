"""哪個區塊是預覽、預覽顯示哪份文字、切換預覽的操作、標題列按鈕、背景計時器。

預覽區 = 資訊（Info）視窗，且同時符合：
  1. 五個訊息篩選全部關掉——這是外掛留下的標記。標記存在區塊自己的資料裡，
     版面重建、切換工作區、存檔重開都會跟著走，不靠記憶體位址。
  2. 區塊裡還留著一個文字編輯器的資料（從文字編輯器切過來時 Blender 會保留），
     預覽就顯示那個文字編輯器開著的文字。下拉選單改的也是它。
"""

import bpy

REPORT_FLAGS = (
    "show_report_debug",
    "show_report_info",
    "show_report_operator",
    "show_report_warning",
    "show_report_error",
)
# 關掉預覽時把篩選恢復成 Blender 的預設值
NORMAL_FLAGS = {
    "show_report_debug": False,
    "show_report_info": True,
    "show_report_operator": True,
    "show_report_warning": True,
    "show_report_error": True,
}

# ---- 執行期狀態（不存檔）
scroll = {}  # 文字名稱 → 捲動量（像素）
last_draw = {}  # area 指標 → (layout, 文字名稱, 區塊高度)
want_images = set()  # 畫的時候發現要從硬碟載入的圖片，交給計時器載入
_signatures = {}  # area 指標 → 上次看到的文字內容雜湊


def text_space(area):
    for sp in area.spaces:
        if sp.type == 'TEXT_EDITOR':
            return sp
    return None


def is_preview(area):
    if area is None or area.type != 'INFO':
        return False
    sp = area.spaces.active
    if any(getattr(sp, f) for f in REPORT_FLAGS):
        return False
    return text_space(area) is not None


def preview_text(area):
    sp = text_space(area)
    return sp.text if sp else None


def iter_previews():
    # 用 bpy.data 而不是 bpy.context：計時器和註冊階段的 context 可能是受限的
    for wm in bpy.data.window_managers:
        for win in wm.windows:
            for area in win.screen.areas:
                if is_preview(area):
                    yield win, area


def enter(area):
    """文字編輯器 → 預覽。"""
    area.type = 'INFO'
    sp = area.spaces.active
    for f in REPORT_FLAGS:
        setattr(sp, f, False)
    area.tag_redraw()


def leave(area):
    """預覽 → 文字編輯器。先把篩選恢復，之後這個區塊手動切回資訊視窗也不會又變成預覽。"""
    sp = area.spaces.active
    for f, v in NORMAL_FLAGS.items():
        setattr(sp, f, v)
    area.type = 'TEXT_EDITOR'


def tag_previews(text=None):
    for _win, area in iter_previews():
        if text is None or preview_text(area) == text:
            area.tag_redraw()


# ---------------------------------------------------------------- 操作

class BLMD_OT_toggle_preview(bpy.types.Operator):
    """Toggle between editing this text and its Markdown preview"""

    bl_idname = "blmd.toggle_preview"
    bl_label = "Toggle Markdown Preview"

    @classmethod
    def poll(cls, context):
        area = context.area
        if area is None:
            return False
        if area.type == 'TEXT_EDITOR':
            return context.space_data.text is not None
        return is_preview(area)

    def execute(self, context):
        area = context.area
        if area.type == 'TEXT_EDITOR':
            enter(area)
        else:
            leave(area)
        return {'FINISHED'}


class BLMD_OT_preview_side(bpy.types.Operator):
    """Open a Markdown preview of this text to the side"""

    bl_idname = "blmd.preview_side"
    bl_label = "Open Markdown Preview to the Side"

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'TEXT_EDITOR' and context.space_data.text is not None

    def execute(self, context):
        area = context.area
        text = context.space_data.text
        screen = context.screen
        # 同一個畫面已經有這份文字的預覽，就不再開一個（跟 VS Code 一樣）
        for a in screen.areas:
            if is_preview(a) and preview_text(a) == text:
                a.tag_redraw()
                return {'FINISHED'}
        before = {a.as_pointer() for a in screen.areas}
        region = next(r for r in area.regions if r.type == 'WINDOW')
        with context.temp_override(area=area, region=region):
            bpy.ops.screen.area_split(direction='VERTICAL', factor=0.5)
        new = next((a for a in screen.areas if a.as_pointer() not in before), None)
        if new is None:
            self.report({'WARNING'}, "Could not split the area")
            return {'CANCELLED'}
        right = new if new.x > area.x else area
        if right.type == 'TEXT_EDITOR' and right.spaces.active.text != text:
            right.spaces.active.text = text
        enter(right)
        return {'FINISHED'}


class _InPreview:
    @classmethod
    def poll(cls, context):
        return is_preview(context.area)


class BLMD_OT_preview_new(_InPreview, bpy.types.Operator):
    """Create a new text and show it in this preview"""

    bl_idname = "blmd.preview_new"
    bl_label = "New Text"

    def execute(self, context):
        text_space(context.area).text = bpy.data.texts.new("Text.md")
        context.area.tag_redraw()
        return {'FINISHED'}


class BLMD_OT_preview_open(_InPreview, bpy.types.Operator):
    """Open a text file and show it in this preview"""

    bl_idname = "blmd.preview_open"
    bl_label = "Open Text"

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.md;*.markdown;*.txt", options={'HIDDEN'})
    filter_text: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        path = bpy.path.abspath(self.filepath)
        # 已經開過的檔案就沿用，不要開出第二份
        text = next((t for t in bpy.data.texts if t.filepath and bpy.path.abspath(t.filepath) == path), None)
        if text is None:
            try:
                text = bpy.data.texts.load(path)
            except (RuntimeError, OSError) as e:
                self.report({'ERROR'}, f"Cannot open file: {e}")
                return {'CANCELLED'}
        text_space(context.area).text = text
        context.area.tag_redraw()
        return {'FINISHED'}


# ---------------------------------------------------------------- 標題列

def draw_text_header(self, context):
    if context.space_data.text is None:
        return
    row = self.layout.row(align=True)
    row.operator(BLMD_OT_toggle_preview.bl_idname, text="", icon='HIDE_OFF')
    row.operator(BLMD_OT_preview_side.bl_idname, text="", icon='SPLIT_VERTICAL')


def draw_info_header(self, context):
    area = context.area
    if not is_preview(area):
        return
    layout = self.layout
    layout.separator()
    row = layout.row(align=True)
    row.operator(BLMD_OT_toggle_preview.bl_idname, text="Edit", icon='TEXT')
    # 跟文字編輯器標題列一樣的選單：瀏覽、新增、開檔。
    # 不給 unlink：文字編輯器的 X 會刪掉文字資料，這裡的 X 只是讓預覽不顯示任何文字
    layout.template_ID(
        text_space(area), "text", new=BLMD_OT_preview_new.bl_idname, open=BLMD_OT_preview_open.bl_idname
    )


# ---------------------------------------------------------------- 計時器

def _tick():
    """每 0.2 秒：文字內容變了就重畫預覽；需要的圖片從硬碟載入。

    為什麼用計時器：資訊視窗不會因為文字被編輯而重畫，要外掛自己叫它重畫。
    為什麼圖片在這裡載入：畫圖的時候不准新增資料（bpy.data），只能在畫圖以外的時機做。
    """
    try:
        if want_images:
            from . import draw

            for src, base in list(want_images):
                draw.load_image_file(src, base)
            want_images.clear()
            tag_previews()

        seen = set()
        for _win, area in iter_previews():
            key = area.as_pointer()
            seen.add(key)
            text = preview_text(area)
            sig = hash((text.name, text.as_string())) if text else None
            if _signatures.get(key) != sig:
                _signatures[key] = sig
                from . import draw

                draw.failed_images.clear()
                area.tag_redraw()
        for key in list(_signatures):
            if key not in seen:
                del _signatures[key]
                last_draw.pop(key, None)
    except Exception as e:  # 計時器丟例外會被 Blender 移除，寧可印出來繼續跑
        print("BLMD timer:", e)
    return 0.2


def register():
    bpy.types.TEXT_HT_header.append(draw_text_header)
    bpy.types.INFO_HT_header.append(draw_info_header)
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.2, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    bpy.types.INFO_HT_header.remove(draw_info_header)
    bpy.types.TEXT_HT_header.remove(draw_text_header)
    scroll.clear()
    last_draw.clear()
    want_images.clear()
    _signatures.clear()


classes = (BLMD_OT_toggle_preview, BLMD_OT_preview_side, BLMD_OT_preview_new, BLMD_OT_preview_open)
