"""Capture original inspector for the accepted ordinary sync scene, with Windows fonts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import types
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtGui import QFontDatabase,QFontInfo
from PySide6.QtWidgets import QApplication,QWidget,QLabel,QDoubleSpinBox,QLineEdit,QPushButton,QToolButton,QCheckBox,QComboBox
from frontend_pyside.core.ui_theme import apply_application_theme
from frontend_pyside.shared.font_fallback import configure_qt_font
from frontend_pyside.features.teaching_v2.model import SceneStore
app=QApplication([])
for name in ('msyh.ttc','msyhbd.ttc'):
    path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/name
    if path.exists():QFontDatabase.addApplicationFont(str(path))
apply_application_theme(app);configure_qt_font(app)
legacy=types.ModuleType('frontend_pyside.features.teaching_v2._lifecycle_original_inspector')
legacy.__package__='frontend_pyside.features.teaching_v2';sys.modules[legacy.__name__]=legacy
source=subprocess.check_output(['git','show','HEAD:frontend_pyside/features/teaching_v2/inspector.py'],cwd=root).decode('utf-8')
exec(compile(source,'original-lifecycle-inspector.py','exec'),legacy.__dict__)
folder=root/'tests/golden/ui-baseline/teaching/sync/lifecycle'
store=SceneStore(start_empty=True);store.restore_dict(json.loads((folder/'before-first-submission-scene.json').read_text(encoding='utf-8')));store.select('laser-001')
inspector=legacy.Inspector(store);inspector.show();inspector.detail_button.setChecked(True)
units={unit for specs in legacy.KIND_PARAM_SPECS.values() for _,_,unit in specs if unit}
unit_widths={unit:inspector._unit_label(unit).width() for unit in sorted(units)}
(root/'frontend_web/src/teaching/domain/unit-widths.json').write_text(json.dumps(unit_widths,ensure_ascii=False,indent=2),encoding='utf-8')
for _ in range(8):app.processEvents()
inspector.grab().save(str(folder/'before-submission-laser-inspector.png'))
controls=[]
for w in inspector.findChildren(QWidget):
    if not w.isVisible() or not isinstance(w,(QLabel,QDoubleSpinBox,QLineEdit,QPushButton,QToolButton,QCheckBox,QComboBox)):continue
    p=w.mapTo(inspector,w.rect().topLeft());text=w.text() if hasattr(w,'text') else str(w.value()) if hasattr(w,'value') else w.currentText() if isinstance(w,QComboBox) else ''
    controls.append({'kind':type(w).__name__,'text':text,'bounds':[p.x(),p.y(),w.width(),w.height()],
                    'font':{'family':w.font().family(),'resolved_family':QFontInfo(w.font()).family(),'pixel_size':QFontInfo(w.font()).pixelSize()}})
(folder/'inspector-geometry.json').write_text(json.dumps({'size':[inspector.width(),inspector.height()],'controls':controls},ensure_ascii=False,indent=2),encoding='utf-8')
print('Captured',inspector.width(),inspector.height(),'resolved font:',QFontInfo(app.font()).family())
inspector.detail_button.setChecked(False)
inspector._fit_to_content()
for _ in range(8):app.processEvents()
inspector.grab().save(str(folder/'before-submission-laser-collapsed.png'))
print('Collapsed',inspector.width(),inspector.height())
inspector.close()
