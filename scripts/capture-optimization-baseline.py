"""Capture the original optimization controls and submitted request, without running jobs."""
import json, os, sys, tempfile
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
isolation = Path(tempfile.mkdtemp(prefix='optical-optimization-baseline-'))
os.environ.update(QT_QPA_PLATFORM='offscreen', APPDATA=str(isolation/'appdata'), LOCALAPPDATA=str(isolation/'localappdata'), OPTICAL_USAGE_DIR=str(isolation/'usage'), USER_DATA_DIR=str(isolation/'data'))
from PySide6.QtCore import QSettings, QTimer, QEventLoop, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QDoubleSpinBox, QLineEdit, QComboBox, QPushButton, QToolButton, QCheckBox, QRadioButton
from frontend_pyside.app.bootstrap import create_main_window
from frontend_pyside.core.ui_theme import apply_application_theme
app = QApplication([])
for font in ['msyh.ttc', 'msyhbd.ttc']:
    QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/font))
app.setOrganizationName('OpticalMigrationVisualCapture'); app.setApplicationName('OptimizationBaseline')
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(isolation/'settings'))
apply_application_theme(app)
window = create_main_window(); window.resize(1280,800); window.show()
target = root/'tests/golden/ui-baseline/optimization'; target.mkdir(parents=True, exist_ok=True)
records = {}
def capture(name, document):
    # Let layout and deferred Matplotlib drawing settle before recording the
    # same frame's geometry and pixels. A tight processEvents loop is too short.
    loop=QEventLoop(); QTimer.singleShot(120,loop.quit); loop.exec()
    window.grab()
    loop=QEventLoop(); QTimer.singleShot(120,loop.quit); loop.exec()
    window.grab().save(str(target/(name+'.png')))
    controls = []
    for scope in [document, window.workbench.object_rail]:
        for w in scope.findChildren(QWidget):
            if not w.isVisible() or not isinstance(w,(QLabel,QDoubleSpinBox,QLineEdit,QComboBox,QPushButton,QToolButton,QCheckBox,QRadioButton)): continue
            if isinstance(w,QLineEdit) and isinstance(w.parentWidget(),QDoubleSpinBox): continue
            p=w.mapTo(window,w.rect().topLeft())
            controls.append({'kind':type(w).__name__,'text':w.currentText() if isinstance(w,QComboBox) else w.text(),'bounds':[p.x(),p.y(),w.width(),w.height()]})
    for scope in [document, window.workbench.object_rail]:
        for w in scope.findChildren(QWidget):
            if not w.isVisible() or type(w).__name__ not in {'PlotCanvas','QTableWidget'}: continue
            p=w.mapTo(window,w.rect().topLeft())
            controls.append({'kind':type(w).__name__,'text':'','bounds':[p.x(),p.y(),w.width(),w.height()]})
    records[name] = controls
def run():
    try:
        window.open_document('optimization','opt_vars')
        shell=window.workbench; doc=shell._widgets['optimization:opt_vars']; rail=shell.object_rail
        capture('empty', doc)
        selected={'surfaces[0].radius_mm','surfaces[0].distance_to_next_mm','surfaces[1].distance_to_next_mm'}
        shell._selected_optimization=selected; doc.set_selected(selected)
        for index in range(rail.list.count()):
            item=rail.list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) in selected:
                item.setCheckState(Qt.CheckState.Checked)
        capture('selected',doc)
        rail.optimization_more_button.click(); capture('advanced',doc)
        rail.goal_inspector.collimation.setChecked(True); capture('collimation',doc)
        rail.goal_inspector.collimation.setChecked(False)
        doc.surrogate_option.setChecked(True); capture('surrogate',doc)
        doc.formal_option.setChecked(True)
        captured=[]
        shell._jobs.submit=lambda kind,payload:captured.append({'kind':kind,'payload':payload}) or None
        shell.start_optimization()
        capture('result-empty',shell._widgets['optimization:opt_result'])
        result_path=root/'tests/golden/ui-current/optimization/formal-job-result.json'
        if result_path.exists():
            result=json.loads(result_path.read_text(encoding='utf-8-sig'))['data']
            result_doc=shell._widgets['optimization:opt_result']
            result_doc.apply_opt_result(result)
            capture('result-line',result_doc)
            result_doc.chart.setCurrentText('候选对照')
            capture('result-bar',result_doc)
        (target/'requests.json').write_text(json.dumps(captured,ensure_ascii=False,indent=2),encoding='utf-8')
        (target/'geometry.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({name:len(value) for name,value in records.items()}))
    finally:
        window.context.services.usage.close(); app.quit()
QTimer.singleShot(500,run)
app.exec()
