_needs_reload = "bpy" in locals()

import bpy  # noqa: E402

from . import draw, input, layout, links, parser, preview  # noqa: E402

if _needs_reload:
    import importlib

    # 先載入被依賴的模組，再載入用到它們的模組
    parser = importlib.reload(parser)
    layout = importlib.reload(layout)
    links = importlib.reload(links)
    preview = importlib.reload(preview)
    draw = importlib.reload(draw)
    input = importlib.reload(input)

_modules = (preview, draw, input)

# 所有要註冊的類別都收進這一個清單（見 CLAUDE.md 唯一合法存取方式）
classes = (*preview.classes, *input.classes)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    for mod in _modules:
        mod.register()


def unregister():
    for mod in reversed(_modules):
        mod.unregister()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
