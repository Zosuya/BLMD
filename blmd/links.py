"""點連結後要做的事。

bl: 連結只開放固定幾種安全動作（見 CLAUDE.md 重要規則）——筆記存在 .blend 裡，
別人給的 .blend 不能拿來執行任意指令。新增動作時照這個原則，不要開放任意 operator 或 Python。
"""

import math
from urllib.parse import unquote

import bpy
from mathutils import Vector

WEB_SCHEMES = ("http://", "https://", "mailto:")

# 對準物件時，物件大約佔畫面多少（0.5 = 一半）
FRAME_FILL = 0.5


def open_link(context, target):
    """回傳 (成功?, 訊息)。"""
    if target.startswith(WEB_SCHEMES):
        bpy.ops.wm.url_open(url=target)
        return True, ""
    if target.startswith("bl:"):
        kind, _, arg = target[3:].partition("/")
        arg = unquote(arg)
        handler = _BL_ACTIONS.get(kind)
        if handler is None:
            return False, f"Unknown Blender link: {target}"
        return handler(context, arg)
    return False, f"Unsupported link: {target}"


# ---------------------------------------------------------------- 共用

def _areas(context, kind):
    """預覽所在視窗裡某種區塊，連同它的主要 region。"""
    for area in context.window.screen.areas:
        if area.type == kind:
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is not None:
                yield area, region


def _select_only(context, objects):
    vl = context.view_layer
    for o in vl.objects.selected:
        o.select_set(False)
    picked = []
    for o in objects:
        try:
            o.select_set(True)
            picked.append(o)
        except RuntimeError:  # 不在這個 view layer 裡
            pass
    if picked:
        vl.objects.active = picked[0]
    return picked


def _frame(context, objects):
    """3D 視圖對準這些物件，留一點空間。

    不用內建的 View Selected：它會塞滿畫面，而且有 200ms 的動畫，事後再拉遠會被動畫蓋掉。
    這裡直接算外框球的位置和大小，設定視角中心與距離，不改視角方向。
    """
    pts = []
    for o in objects:
        pts.extend(o.matrix_world @ Vector(c) for c in o.bound_box)
    if not pts:
        return
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    center = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 0.1)
    for area, _region in _areas(context, 'VIEW_3D'):
        sp = area.spaces.active
        r3 = sp.region_3d
        if r3.view_perspective == 'CAMERA':
            r3.view_perspective = 'PERSP'
        # Blender 視埠用 72mm 當感光元件寬度換算焦距
        half_fov = math.atan(36.0 / sp.lens)
        r3.view_location = center
        r3.view_distance = radius / math.tan(half_fov) / FRAME_FILL
        area.tag_redraw()


def _find_object(context, name):
    ob = context.scene.objects.get(name)
    if ob is None:
        return None, f"Object not found in this scene: {name}"
    return ob, ""


# ---------------------------------------------------------------- 動作

def _workspace(context, name):
    ws = bpy.data.workspaces.get(name)
    if ws is None:
        return False, f"Workspace not found: {name}"
    win = context.window

    # 延到這次點擊處理完再切：切了之後預覽所在的畫面就換掉了
    def switch():
        win.workspace = ws  # 回傳 None：計時器只跑一次

    bpy.app.timers.register(switch, first_interval=0.0)
    return True, ""


def _object(context, name):
    ob, msg = _find_object(context, name)
    if ob is None:
        return False, msg
    if not _select_only(context, [ob]):
        return False, f"Object is not selectable in this view layer: {name}"
    _frame(context, [ob])
    return True, ""


def _collection(context, name):
    coll = bpy.data.collections.get(name)
    if coll is None:
        return False, f"Collection not found: {name}"
    scene_objs = set(context.scene.objects)
    objs = [o for o in coll.all_objects if o in scene_objs]
    if not objs:
        return False, f"Collection has no objects in this scene: {name}"
    picked = _select_only(context, objs)
    if not picked:
        return False, f"No selectable objects in collection: {name}"
    _frame(context, picked)
    return True, ""


def _camera(context, name):
    ob, msg = _find_object(context, name)
    if ob is None:
        return False, msg
    if ob.type != 'CAMERA':
        return False, f"Not a camera: {name}"
    context.scene.camera = ob
    for area, _region in _areas(context, 'VIEW_3D'):
        area.spaces.active.region_3d.view_perspective = 'CAMERA'
        area.tag_redraw()
    return True, ""


def _local(context, name):
    """局部視圖（小鍵盤 /）。已經在只看這個物件的局部視圖時，再點一次就退出。"""
    ob, msg = _find_object(context, name)
    if ob is None:
        return False, msg
    views = list(_areas(context, 'VIEW_3D'))
    if not views:
        return False, "No 3D Viewport in this window"
    # 判斷要不要只是退出：每個 3D 視圖都已經在「只有這個物件」的局部視圖
    def only_this(area):
        sp = area.spaces.active
        if sp.local_view is None:
            return False
        shown = [o for o in context.scene.objects if o.local_view_get(sp)]
        return shown == [ob]

    exit_only = all(only_this(a) for a, _ in views)
    if not exit_only and not _select_only(context, [ob]):
        return False, f"Object is not selectable in this view layer: {name}"
    for area, region in views:
        sp = area.spaces.active
        with context.temp_override(area=area, region=region, space_data=sp):
            if sp.local_view is not None:
                bpy.ops.view3d.localview()
            if not exit_only:
                bpy.ops.view3d.localview(frame_selected=True)
    return True, ""


def _text(context, name):
    from . import preview

    text = bpy.data.texts.get(name)
    if text is None:
        return False, f"Text not found: {name}"
    sp = preview.text_space(context.area)
    if sp is None:
        return False, "Not a preview area"
    sp.text = text
    context.area.tag_redraw()
    return True, ""


def _find_tree(path):
    """bl:node/<節點樹>/<節點> 的節點樹名稱裡也可能有 /，從長到短試。

    回傳 (種類, 擁有者, 節點樹, 剩下的節點名稱)；種類是 "material" / "group" / "world"。
    """
    parts = path.split("/")
    for i in range(len(parts), 0, -1):
        name, rest = "/".join(parts[:i]), "/".join(parts[i:])
        mat = bpy.data.materials.get(name)
        if mat is not None and mat.node_tree is not None:
            return "material", mat, mat.node_tree, rest
        group = bpy.data.node_groups.get(name)
        if group is not None:
            return "group", group, group, rest
        world = bpy.data.worlds.get(name)
        if world is not None and world.node_tree is not None:
            return "world", world, world.node_tree, rest
    return None, None, None, ""


def _show_without_pin(context, sp, kind, owner):
    """讓節點編輯器「自然地」顯示這個節點樹（不釘選）：

    - 材質：作用中物件有這個材質就切到那一格；沒有就改選場景裡用到它的物件
    - 幾何節點：改選用這個節點群組當修改器的物件，並把那個修改器設成作用中
    - 世界：只有目前場景用的世界才行

    做不到（例如材質沒有物件在用、節點群組是包在別的節點樹裡）就回傳 False，由呼叫端改用釘選。
    """
    vl = context.view_layer
    scene_objs = list(context.scene.objects)

    if kind == "material":
        def slot(o):
            return next((i for i, s in enumerate(o.material_slots) if s.material == owner), None)

        ob = vl.objects.active
        if ob is None or slot(ob) is None:
            ob = next((o for o in scene_objs if slot(o) is not None and o.name in vl.objects), None)
            if ob is None or not _select_only(context, [ob]):
                return False
        ob.active_material_index = slot(ob)
        sp.tree_type = 'ShaderNodeTree'
        sp.shader_type = 'OBJECT'
        return True

    if kind == "group" and owner.bl_idname == 'GeometryNodeTree':
        def modifier(o):
            return next((m for m in o.modifiers if m.type == 'NODES' and m.node_group == owner), None)

        ob = vl.objects.active
        if ob is None or modifier(ob) is None:
            ob = next((o for o in scene_objs if modifier(o) is not None and o.name in vl.objects), None)
            if ob is None or not _select_only(context, [ob]):
                return False
        modifier(ob).is_active = True
        sp.tree_type = 'GeometryNodeTree'
        sp.geometry_nodes_type = 'MODIFIER'
        return True

    if kind == "world" and context.scene.world == owner:
        sp.tree_type = 'ShaderNodeTree'
        sp.shader_type = 'WORLD'
        return True

    return False


def _node(context, path):
    kind, owner, tree, node_name = _find_tree(path)
    if tree is None:
        return False, f"Node tree not found: {path}"
    node = None
    if node_name:
        node = tree.nodes.get(node_name) or next((n for n in tree.nodes if n.label == node_name), None)
        if node is None:
            return False, f"Node not found: {node_name}"
    editors = list(_areas(context, 'NODE_EDITOR'))
    if not editors:
        return False, "No Node Editor in this window"
    area, _region = editors[0]
    sp = area.spaces.active
    sp.pin = False
    if not _show_without_pin(context, sp, kind, owner):
        # 最後手段：釘選。使用者要自己點掉圖釘才會恢復跟著選取變
        sp.tree_type = tree.bl_idname
        if tree.bl_idname == 'ShaderNodeTree':
            sp.shader_type = 'WORLD' if kind == "world" else 'OBJECT'
        sp.pin = True
        sp.node_tree = tree
    if node is not None:
        for n in tree.nodes:
            n.select = n == node
        tree.nodes.active = node
    area.tag_redraw()
    win = context.window

    # 剛切過去的節點樹還沒畫過，節點大小是 0，對準會偏；等畫過一次再對準
    def frame():
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is None or area.type != 'NODE_EDITOR':
            return None
        with bpy.context.temp_override(window=win, area=area, region=region):
            if node is not None:
                bpy.ops.node.view_selected()
            else:
                bpy.ops.node.view_all()
        return None

    bpy.app.timers.register(frame, first_interval=0.1)
    return True, ""


def _frame_number(context, arg):
    try:
        frame = int(arg)
    except ValueError:
        return False, f"Not a frame number: {arg}"
    context.scene.frame_set(frame)
    return True, ""


_BL_ACTIONS = {
    "workspace": _workspace,
    "object": _object,
    "collection": _collection,
    "camera": _camera,
    "local": _local,
    "text": _text,
    "node": _node,
    "frame": _frame_number,
}
