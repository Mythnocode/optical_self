"""One-time extraction of Qt-free drawing code, preserving existing source bodies."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
qt = ROOT / "frontend_pyside/shared/plotting"
shared = ROOT / "shared_presentation/plotting"

def extract(source, destination, replacements=()):
    text = source.read_text(encoding="utf-8")
    for old, new in replacements:
        if old not in text:
            raise ValueError(f"Missing import: {old}")
        text = text.replace(old, new)
    destination.write_text(text, encoding="utf-8", newline="\n")
    module = "shared_presentation.plotting." + destination.stem
    source.write_text(
        '"""Compatibility facade for the shared presentation implementation."""\n'
        f'from {module} import ' + destination.stem + ' as _unused\n'
        if False else
        '"""Compatibility facade for the shared presentation implementation."""\n'
        f'import {module} as _implementation\n\n'
        'globals().update({name: value for name, value in vars(_implementation).items() if not name.startswith("__")})\n',
        encoding="utf-8", newline="\n",
    )

extract(qt / "ray_plot_style.py", shared / "ray_plot_style.py")
extract(qt / "canvas_parts/data_utils.py", shared / "data_utils.py")
extract(qt / "canvas_parts/canvas_2d.py", shared / "canvas_2d.py", (
    ("from frontend_pyside.resources import theme_tokens as theme", "from shared_presentation import theme_tokens as theme"),
    ("from frontend_pyside.shared.plotting.canvas_view", "from shared_presentation.plotting.canvas_view"),
    ("from frontend_pyside.shared.plotting.ray_plot_style", "from shared_presentation.plotting.ray_plot_style"),
))

canvas = qt / "canvas.py"
text = canvas.read_text(encoding="utf-8")
tree = ast.parse(text)
method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_apply_safe_plot_margins")
lines = text.splitlines(keepends=True)
body = ''.join(line[4:] if line.startswith('    ') else line for line in lines[method.lineno-1:method.end_lineno])
body = body.replace("def _apply_safe_plot_margins(self, kind: str)", "def apply_safe_plot_margins(figure, data: dict, kind: str)").replace("self.figure", "figure").replace("self._data", "data")
(shared / "margins.py").write_text('"""Original plot margins, shared by Qt and headless figure export."""\n\n' + body, encoding="utf-8", newline="\n")
lines[method.lineno-1:method.end_lineno] = [
    '    def _apply_safe_plot_margins(self, kind: str) -> None:\n',
    '        from shared_presentation.plotting.margins import apply_safe_plot_margins\n',
    '        apply_safe_plot_margins(self.figure, self._data, kind)\n',
]
canvas.write_text(''.join(lines), encoding="utf-8", newline="\n")

source = qt / "canvas_parts/canvas_3d.py"
text = source.read_text(encoding="utf-8")
start = text.index('        ax.set_proj_type("ortho")')
end = text.index('        self._interaction.update_artists(', start)
body = text[start:end]
body = ''.join(line[4:] if line.startswith('    ') else line for line in body.splitlines(keepends=True))
body = body.replace('self.figure', 'ax.figure')
body = body.replace('    self._scene_static_signature = _scene_static_signature(data)\n    self._static_scene_artists = static\n    self._dynamic_scene_artists = dynamic\n', '')
(shared / "scene_drawing.py").write_text(
    '"""Original initial optical scene drawing without Qt interaction controllers."""\n'
    'from shared_presentation import theme_tokens as theme\n'
    'from .canvas_3d_rendering import render_dynamic_scene\n'
    'from .canvas_3d_static_parts import render_static_scene\n'
    'from .canvas_view import fit_optical_scene_3d\n\n'
    'def draw_optical_scene_3d(ax, data: dict):\n' + body + '    return static, dynamic\n',
    encoding="utf-8", newline="\n",
)
text = text[:start] + (
    '        from shared_presentation.plotting.scene_drawing import draw_optical_scene_3d\n'
    '        static, dynamic = draw_optical_scene_3d(ax, data)\n'
    '        self._scene_static_signature = _scene_static_signature(data)\n'
    '        self._static_scene_artists = static\n'
    '        self._dynamic_scene_artists = dynamic\n\n'
) + text[end:]
source.write_text(text, encoding="utf-8", newline="\n")
