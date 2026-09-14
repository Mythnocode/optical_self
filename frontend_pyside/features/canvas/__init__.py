"""画布节点库（scene/view/node/registry/edges/layout_store）。

正式入口是 ``app.py`` / ``run_frontend.py``，壳层见 ``WorkbenchShell`` 与 ``TeachingShell``。
本包不再提供独立产品窗口。
"""

from frontend_pyside.features.canvas.scene import CanvasScene, default_node_factory
from frontend_pyside.features.canvas.view import CanvasView

__all__ = ["CanvasScene", "CanvasView", "default_node_factory"]
