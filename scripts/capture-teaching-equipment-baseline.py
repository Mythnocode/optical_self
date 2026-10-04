"""Capture original Teaching equipment window client and control geometry."""
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
target=ROOT/'tests/golden/ui-baseline/teaching/equipment'
target.mkdir(parents=True,exist_ok=True)
# Qt's default offscreen screen is 800 x 800 and clips adjustSize popups.
# Use the supported platform config to capture the original 1080p layout.
screen_config=target/'screen.json'
screen_config.write_text(json.dumps({'screens':[{'name':'reference','x':0,'y':0,'width':1920,'height':1080,'logicalDpi':96,'logicalBaseDpi':96,'dpr':1.0}]}),encoding='utf-8')
os.chdir(ROOT)
os.environ['QT_QPA_PLATFORM']=f'offscreen:configfile={screen_config.relative_to(ROOT).as_posix()}'
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QLineEdit, QComboBox, QPushButton, QToolButton, QDoubleSpinBox, QScrollArea
from frontend_pyside.core.ui_theme import apply_application_theme
from frontend_pyside.shared.font_fallback import configure_qt_font
from frontend_pyside.modules.teaching.shell import TeachingEquipmentPopup

app=QApplication([])
apply_application_theme(app)
configure_qt_font(app)
popup=TeachingEquipmentPopup()
popup.show()
search=next(w for w in popup.findChildren(QLineEdit) if w.placeholderText()=='搜索器材…')
geometry={}

def capture(name):
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    for _ in range(8):app.processEvents()
    popup.grab().save(str(target/f'{name}.png'))
    controls=[]
    for w in popup.findChildren(QWidget):
        if not w.isVisible() or not isinstance(w,(QLabel,QLineEdit,QComboBox,QPushButton,QToolButton,QDoubleSpinBox,QScrollArea)):continue
        pos=w.mapTo(popup,w.rect().topLeft())
        text=w.currentText() if isinstance(w,QComboBox) else w.text() if hasattr(w,'text') else ''
        controls.append({'kind':type(w).__name__,'text':text,'placeholder':w.placeholderText() if isinstance(w,QLineEdit) else '',
                         'bounds':[pos.x(),pos.y(),w.width(),w.height()],'object_name':w.objectName()})
    screen=app.primaryScreen().availableGeometry()
    geometry[name]={'size':[popup.width(),popup.height()],'screen':[screen.width(),screen.height()],'controls':controls}

capture('default')
search.setText('lens');capture('search-lens')
search.setText('no-such-equipment');capture('search-empty')
search.setText('')
for kind in ('laser','lens','mirror','aperture','fiber','ccd','oscilloscope'):
    popup._select_equipment(kind)
    capture(f'preset-{kind}')
    if kind=='laser':
        popup.preset_box.setCurrentIndex(popup.preset_box.count()-1)
        capture('preset-laser-custom')
(target/'geometry.json').write_text(json.dumps(geometry,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
popup.close()
print('Captured original Teaching equipment states.')
