"""Capture the original teaching inspector client and control geometry."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['OPTICAL_USAGE_DIR'] = tempfile.mkdtemp(prefix='optical-teaching-baseline-')
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QDoubleSpinBox, QLineEdit, QPushButton, QToolButton, QCheckBox
from frontend_pyside.core.ui_theme import apply_application_theme
from frontend_pyside.shared.font_fallback import configure_qt_font
from frontend_pyside.features.teaching_v2.model import SceneStore
from frontend_pyside.features.teaching_v2.inspector import Inspector

app = QApplication([])
apply_application_theme(app)
configure_qt_font(app)
store = SceneStore(start_empty=True)
store.apply_optical_scheme(4)
inspector = Inspector(store)
inspector.show()
target = ROOT / 'tests/golden/ui-baseline/teaching'
target.mkdir(parents=True, exist_ok=True)
geometry = {}

def capture(name):
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    for _ in range(8):
        app.processEvents()
    inspector.grab().save(str(target / f'{name}.png'))
    controls = []
    for widget in inspector.findChildren(QWidget):
        if not widget.isVisible() or not isinstance(widget, (QLabel, QDoubleSpinBox, QLineEdit, QPushButton, QToolButton, QCheckBox)):
            continue
        point = widget.mapTo(inspector, widget.rect().topLeft())
        text = widget.text() if hasattr(widget, 'text') else str(widget.value()) if hasattr(widget, 'value') else ''
        controls.append({'kind': type(widget).__name__, 'text': text, 'bounds': [point.x(),point.y(),widget.width(),widget.height()]})
    geometry[name] = {'size': [inspector.width(),inspector.height()], 'controls': controls}

capture('four-lens-default')
inspector.detail_button.setChecked(True)
capture('four-lens-more')
store.select(None)
capture('empty')
(target / 'inspector-geometry.json').write_text(json.dumps(geometry,ensure_ascii=False,indent=2),encoding='utf-8')
inspector.close()
print('Captured original Teaching inspector states.')
