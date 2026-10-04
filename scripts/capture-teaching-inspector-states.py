"""Capture original inspector after settled selection, then a real details click."""
import json
import os
from pathlib import Path
import subprocess
import sys
import types
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtGui import QFontDatabase,QFontInfo
from PySide6.QtWidgets import QApplication,QWidget,QLabel,QDoubleSpinBox,QLineEdit,QPushButton,QToolButton,QCheckBox,QComboBox
from frontend_pyside.core.ui_theme import apply_application_theme
from frontend_pyside.shared.font_fallback import configure_qt_font
from frontend_pyside.features.teaching_v2.model import SceneStore,PLACEABLE_KINDS,Pose
app=QApplication([])
for name in ('msyh.ttc','msyhbd.ttc'):
    path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/name
    if path.exists():QFontDatabase.addApplicationFont(str(path))
apply_application_theme(app)
configure_qt_font(app)
legacy=types.ModuleType('frontend_pyside.features.teaching_v2._states_original_inspector')
legacy.__package__='frontend_pyside.features.teaching_v2'
sys.modules[legacy.__name__]=legacy
source=subprocess.check_output(['git','show','HEAD:frontend_pyside/features/teaching_v2/inspector.py'],cwd=root).decode('utf-8')
exec(compile(source,'original-inspector-states.py','exec'),legacy.__dict__)
target=root/'tests/golden/ui-baseline/teaching/inspector-states'
target.mkdir(parents=True,exist_ok=True)
base=json.loads((root/'tests/golden/ui-baseline/teaching/sync/lifecycle/before-first-submission-scene.json').read_text(encoding='utf-8'))
record={}
def settle():
    for _ in range(8):app.processEvents()
def capture(inspector,name):
    settle()
    inspector.grab().save(str(target/(name+'.png')))
    controls=[]
    for w in inspector.findChildren(QWidget):
        if not w.isVisible() or not isinstance(w,(QLabel,QDoubleSpinBox,QLineEdit,QPushButton,QToolButton,QCheckBox,QComboBox)):continue
        if isinstance(w,QLineEdit) and isinstance(w.parentWidget(),QDoubleSpinBox):continue
        p=w.mapTo(inspector,w.rect().topLeft())
        text=w.text() if hasattr(w,'text') else str(w.value()) if hasattr(w,'value') else w.currentText() if isinstance(w,QComboBox) else ''
        controls.append({'kind':type(w).__name__,'text':text,'bounds':[p.x(),p.y(),w.width(),w.height()], 'font':{'family':QFontInfo(w.font()).family(),'pixel_size':QFontInfo(w.font()).pixelSize()}})
    scrollbar=inspector.object_scroll.verticalScrollBar()
    record[name]={'size':[inspector.width(),inspector.height()],'controls':controls,'scrollbar':{'minimum':scrollbar.minimum(),'maximum':scrollbar.maximum(),'page_step':scrollbar.pageStep(),'value':scrollbar.value()}}
for kind in ['empty']+[kind for kind,_ in PLACEABLE_KINDS]:
    store=SceneStore(start_empty=True)
    store.restore_dict(base)
    existing=next((item for item in store.components.values() if item.kind==kind),None)
    if kind=='empty':store.select(None)
    elif existing:store.select(existing.component_id)
    else:store.add_component(kind,pose=Pose(180.0,40.0,25.0))
    (target/(kind+'-scene.json')).write_text(json.dumps(store.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
    inspector=legacy.Inspector(store)
    inspector.show()
    capture(inspector,kind+'-collapsed')
    if kind!='empty':
        inspector.detail_button.click()
        capture(inspector,kind+'-expanded')
        inspector.object_scroll.verticalScrollBar().setValue(inspector.object_scroll.verticalScrollBar().maximum())
        capture(inspector,kind+'-bottom')
    inspector.close()
    settle()
# Editing the bound object updates its controls without rebuilding/refitting the window.
store=SceneStore(start_empty=True)
store.restore_dict(base)
laser=next(item for item in store.components.values() if item.kind=='laser')
store.select(laser.component_id)
inspector=legacy.Inspector(store)
inspector.show()
settle()
inspector.detail_button.click()
settle()
store.update_pose(laser.component_id,Pose(laser.pose.x_mm,40.0,laser.pose.z_mm),reason='Inspector visual acceptance')
capture(inspector,'laser-edited-warning')
inspector._enabled_box.click()
capture(inspector,'laser-edited-disabled')
inspector.hide()
settle()
inspector.show()
capture(inspector,'laser-reopened')
inspector.object_scroll.verticalScrollBar().setValue(inspector.object_scroll.verticalScrollBar().maximum())
inspector.hide()
settle()
inspector.show()
capture(inspector,'laser-reopened-bottom')
inspector.close()
(target/'geometry.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({name:value['size'] for name,value in record.items()}))
