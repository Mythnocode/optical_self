from pathlib import Path
import sys, time, json
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop,QTimer
from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.features.teaching.page import TeachingPage

def wait(ms):
    loop=QEventLoop(); QTimer.singleShot(ms,loop.quit); loop.exec()

app=QApplication.instance() or QApplication([])
ctx=create_app_context()
p=TeachingPage(ctx); p.resize(1500,900); p.show(); wait(3500)
out=ROOT/'assets_3d/reports/teaching_page_live.png'; out.parent.mkdir(parents=True, exist_ok=True)
ok=p.grab().save(str(out))
view=p.workbench.view_3d
root=view._quick.rootObject()
report={
 'saved':ok,
 'qml_errors':[e.toString() for e in view._quick.errors()],
 'renderer':str(view._quick.quickWindow().rendererInterface().graphicsApi()),
 'model_revision':p.workbench.model.revision,
 'formal_status':p.workbench.model.scene_snapshot().physics_status,
 'formal_ray_count':len(p.workbench.model.scene_snapshot().formal_rays_mm),
 'edge_count':len(view._bridge.edges),
 'nodes':len(view._bridge.nodes),
 'final_preview_visible': bool(root.property('analysisPanelsVisible')) if root is not None else None,
 'screenshot':str(out),
}
print(json.dumps(report,ensure_ascii=False,indent=2))
p.close(); app.processEvents()
