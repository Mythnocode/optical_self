"""Capture native analysis controls using actual original gateway results."""
import json
import os
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication,QWidget,QLabel,QPushButton,QProgressBar
from PySide6.QtGui import QFontDatabase, QFontInfo, QFontMetrics
from frontend_pyside.core.ui_theme import apply_application_theme
from frontend_pyside.shared.font_fallback import configure_qt_font
from frontend_pyside.modules.teaching.shell import TeachingImagingCouplingPopup,TeachingAnalysisVisual
from shared_presentation.teaching_physics import PhysicsResult

app=QApplication([])
# The offscreen platform does not enumerate Windows system fonts. Register the
# installed UI family so this reference uses the original Windows UI font,
# rather than silently substituting the bundled Droid fallback.
for name in ('msyh.ttc','msyhbd.ttc'):
    font_path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/name
    if font_path.exists():QFontDatabase.addApplicationFont(str(font_path))
apply_application_theme(app)
configure_qt_font(app)
target=root/'tests/golden/ui-baseline/teaching/analysis'
target.mkdir(parents=True,exist_ok=True)
popup=TeachingImagingCouplingPopup()
popup.show()
geometry={}
def capture(name):
    for _ in range(8):app.processEvents()
    popup.grab().save(str(target/f'{name}.png'))
    controls=[]
    for w in popup.findChildren(QWidget):
        if not w.isVisible() or not isinstance(w,(QLabel,QPushButton,QProgressBar,TeachingAnalysisVisual)):continue
        p=w.mapTo(popup,w.rect().topLeft())
        controls.append({'kind':type(w).__name__,'text':w.text() if hasattr(w,'text') else '',
                         'object_name':w.objectName(),'bounds':[p.x(),p.y(),w.width(),w.height()]})
    geometry[name]={'size':[popup.width(),popup.height()],'controls':controls}
    for record,w in zip(controls,[w for w in popup.findChildren(QWidget) if w.isVisible() and isinstance(w,(QLabel,QPushButton,QProgressBar,TeachingAnalysisVisual))]):
        font=w.font();info=QFontInfo(font);fm=QFontMetrics(font);record['font']={'family':font.family(),'resolved_family':info.family(),'pixel_size':info.pixelSize(),'point_size':font.pointSizeF(),'weight':font.weight(),'ascent':fm.ascent(),'descent':fm.descent(),'height':fm.height()}
        if isinstance(w,QLabel):record['indent']=w.indent();record['margin']=w.margin()
capture('empty')
popup.set_running('spot');capture('running-spot')
popup.set_busy(True,'正在计算光斑，界面仍可继续操作');capture('running-controller-spot')
popup.set_running('coupling');capture('running-coupling')
popup.set_busy(True,'正在计算耦合，界面仍可继续操作');capture('running-controller-coupling')
for analysis in ('spot','coupling'):
    data=json.loads((target/f'original-{analysis}.json').read_text(encoding='utf-8'))
    popup.set_result(analysis,PhysicsResult(**data))
    if analysis=='spot':
        popup.set_busy(True,'正在计算耦合，界面仍可继续操作');capture('running-after-spot-coupling')
popup.set_running('',done=True);capture('completed')
popup.set_busy(True,'正在计算光斑，界面仍可继续操作');capture('running-update-spot')
popup.set_running('',done=True)
popup.set_scene_revision(data['scene_revision']+1);capture('stale')
popup.set_busy(False,'请先放一个启用的激光器。');capture('blocked')
for analysis in ('spot','coupling'):
    data=json.loads((root/'tests/golden/ui-baseline/teaching/sync'/f'original-engineering-{analysis}.json').read_text(encoding='utf-8')) if (root/'tests/golden/ui-baseline/teaching/sync'/f'original-engineering-{analysis}.json').exists() else None
    if data is not None:popup.set_result(analysis,PhysicsResult(**data))
if data is not None:
    popup.set_running('',done=True);capture('engineering-completed')
for scenario in ('ordinary', 'imported', 'edited-source'):
    lifecycle = root/'tests/golden/ui-baseline/teaching/sync/lifecycle'
    if not all((lifecycle/f'{scenario}-{analysis}-physics.json').exists() for analysis in ('spot', 'coupling')):
        continue
    for analysis in ('spot', 'coupling'):
        data=json.loads((lifecycle/f'{scenario}-{analysis}-physics.json').read_text(encoding='utf-8'))
        popup.set_result(analysis,PhysicsResult(**data))
    popup.set_running('',done=True);capture(f'{scenario}-completed')
popup.close()
(target/'geometry.json').write_text(json.dumps(geometry,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({key:value['size'] for key,value in geometry.items()}))
