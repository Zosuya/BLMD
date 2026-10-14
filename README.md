# BLMD — Live Markdown Preview for Blender

![BLMD — Blender Markdown](DOC/hero.png)

BLMD adds a live Markdown preview to Blender's Text Editor. Write notes in the built-in Text Editor and see them rendered next to it, updating as you type. Checkboxes in the preview can be toggled with a click, and links can open web pages or drive Blender itself: switch workspaces, frame objects, jump to frames, or jump to a node in the Node Editor.

For a complete walkthrough that you can open and try inside Blender, see the [User Guide](examples/BLMD_Guide_EN.md) ([繁體中文](examples/BLMD_Guide.md)).

## Features

- **Live preview** next to the Text Editor, or toggled in place.
- **Markdown support**: headings, bold, italic, strikethrough, inline code, nested and numbered lists, task lists, tables (with column alignment), block quotes, horizontal rules, fenced code blocks, and images.
- **Clickable checkboxes**: clicking toggles `[ ]` / `[x]` in the source text and can be undone with Ctrl+Z. Checkboxes also work at the start of table cells.
- **Web links** open in the default browser.
- **Blender links** (`bl:`), a fixed set of safe actions:

| Link | Action |
|:--|:--|
| `bl:workspace/<name>` | Switch to a workspace |
| `bl:object/<name>` | Select an object and frame it in the 3D Viewport |
| `bl:collection/<name>` | Select all objects in a collection and frame them |
| `bl:camera/<name>` | Make a camera the scene camera and look through it |
| `bl:local/<name>` | Toggle Local View on an object |
| `bl:frame/<number>` | Jump to a frame |
| `bl:node/<tree>/<node>` | Show a material, node group or world in the Node Editor and frame a node or frame |
| `bl:text/<name>` | Show another text in the preview |

- **Images** from the current .blend (`bl:image/<name>`) or from disk (paths relative to the note, or `//` for paths relative to the .blend). Wide images are scaled down to fit.
- Mixed CJK and Latin text wraps correctly.

## Usage

| Where | Shortcut | Action |
|:--|:--|:--|
| Text Editor | Ctrl+Alt+V | Open a preview to the side |
| Text Editor | Ctrl+Shift+V | Toggle between editing and preview |
| Preview | Ctrl+Shift+V | Back to editing |
| Preview | Wheel, Page Up/Down, Home/End | Scroll |
| Preview | Left click | Toggle checkboxes, follow links |

To open a .md file, use **Text > Open Markdown** (Blender's own Open does not list .md files).

The same actions are available as buttons in the Text Editor header. The preview header has a text selector with New and Open, like the Text Editor.

## Safety

`bl:` links can only perform the actions listed above. They cannot run operators or Python code, so notes stored inside a .blend file you received from someone else cannot be used to execute anything.

## Permissions

- **Files**: images referenced by a note can be loaded from disk to display them in the preview. Loaded images have no users and are not saved into the .blend file.

## Notes

- The preview is drawn on top of an Info editor. Switching the preview back to editing restores the normal Info editor settings.
- Italic text is drawn upright, because Blender's text drawing has no italic font.
- Line breaks inside a paragraph are kept as written.

## License

GPL-3.0-or-later
