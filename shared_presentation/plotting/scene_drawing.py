"""Original initial optical scene drawing without Qt interaction controllers."""
from shared_presentation import theme_tokens as theme
from .canvas_3d_rendering import render_dynamic_scene
from .canvas_3d_static_parts import render_static_scene
from .canvas_view import fit_optical_scene_3d

def draw_optical_scene_3d(ax, data: dict):
    ax.set_proj_type("ortho")
    ax.set_axis_off()
    ax.figure.subplots_adjust(left=0.0, right=1.0, bottom=0.0, top=1.0)
    ax.set_position([0.0, 0.0, 1.0, 1.0])
    ax.set_facecolor(theme.SCENE_BACKGROUND)

    static = render_static_scene(ax, data)
    dynamic = render_dynamic_scene(ax, data)
    fit_optical_scene_3d(ax, data)
    ax.view_init(elev=17, azim=-72)
    title = str(data.get("title", ""))
    if title:
        ax.text2D(
            0.018, 0.972, title, transform=ax.transAxes,
            fontsize=13.0, fontweight="semibold", color=theme.TEXT_PRIMARY,
        )
    scale_label = str(data.get("scale_label", ""))
    if scale_label:
        ax.text2D(
            0.982, 0.025, scale_label, transform=ax.transAxes,
            ha="right", fontsize=8.5, color=theme.TEXT_MUTED,
        )

    return static, dynamic
