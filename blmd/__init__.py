"""BLMD：Blender 文字編輯器的 Markdown 即時預覽。

bpy 相關模組在 register() 裡才 import，這樣 parser / layout 可以不開 Blender 單獨測試。
"""

import importlib
import sys

_MODULES = ("preview", "draw", "input")


def _modules():
    mods = []
    for name in _MODULES:
        full = f"{__name__}.{name}"
        mod = sys.modules.get(full)
        # Reload Addon 時重新載入子模組，否則會沿用舊程式碼
        mods.append(importlib.reload(mod) if mod else importlib.import_module(full))
    return mods


def _classes(mods):
    # 所有要註冊的類別都從各模組的 classes 收進這一個清單（見 CLAUDE.md 唯一合法存取方式）
    return [cls for mod in mods for cls in getattr(mod, "classes", ())]


def register():
    import bpy

    for sub in ("parser", "layout", "links"):
        full = f"{__name__}.{sub}"
        if full in sys.modules:
            importlib.reload(sys.modules[full])
    mods = _modules()
    for cls in _classes(mods):
        bpy.utils.register_class(cls)
    for mod in mods:
        mod.register()


def unregister():
    import bpy

    mods = [sys.modules[f"{__name__}.{n}"] for n in _MODULES if f"{__name__}.{n}" in sys.modules]
    for mod in reversed(mods):
        mod.unregister()
    for cls in reversed(_classes(mods)):
        bpy.utils.unregister_class(cls)
