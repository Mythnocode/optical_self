"""Replay a manually observed Web equipment drop through the original Qt view."""
import json
import os
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtCore import QPointF, Qt, QMimeData
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication
from frontend_pyside.core.ui_theme import apply_application_theme
from frontend_pyside.shared.font_fallback import configure_qt_font
from frontend_pyside.features.teaching_v2.model import SceneStore
from frontend_pyside.features.teaching_v2.canvas import BenchScene, BenchView

app=QApplication([])
apply_application_theme(app)
configure_qt_font(app)
current=root/'tests/golden/ui-current/teaching/equipment'
original=root/'tests/golden/ui-baseline/teaching/equipment'
before=json.loads((current/'drop-2d-undo-scene.json').read_text(encoding='utf-8'))
after=json.loads((current/'drop-2d-scene.json').read_text(encoding='utf-8'))
observed=json.loads((current/'drop-2d-view.json').read_text(encoding='utf-8'))
store=SceneStore(start_empty=True)
store.restore_dict(before)
scene=BenchScene(store)
view=BenchView(scene)
view.resize(observed['host']['width'],observed['host']['height'])
view.show()
for _ in range(8):app.processEvents()
view.fit_scene()
for _ in range(8):app.processEvents()
transform=view.viewportTransform()
point=QPointF(observed['to'][0]-observed['host']['x']-1,observed['to'][1]-observed['host']['y']-1)
mime=QMimeData()
mime.setText('lens')
event=QDropEvent(point,Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
view.dropEvent(event)
original_scene=store.to_dict()
expected=next(c for c in after['components'] if c['component_id']==after['selected_component_id'])
actual=next(c for c in original_scene['components'] if c['component_id']==original_scene['selected_component_id'])
result={'accepted':event.isAccepted(),'qt_transform':[transform.m11(),transform.dx(),transform.dy()],
        'web_transform':observed['transform'],'actual':actual,'expected':expected,
        'component_equal':actual==expected,'pose_max_difference':max(abs(actual['pose'][key]-value) for key,value in expected['pose'].items())}
(current/'drop-2d-comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
view.grab().save(str(original/'drop-2d.png'))
view.close()
print(json.dumps({'component_equal':result['component_equal'],'pose_max_difference':result['pose_max_difference'],'accepted':result['accepted']}))
