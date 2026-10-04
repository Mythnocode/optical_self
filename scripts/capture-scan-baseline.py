"""Capture the original scan controls and submitted request, without running jobs."""
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
app.setOrganizationName('OpticalMigrationVisualCapture'); app.setApplicationName('ScanBaseline')
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(isolation/'settings'))
apply_application_theme(app)
window = create_main_window(); window.resize(1280,800); window.show()
target = root/'tests/golden/ui-baseline/scan'; target.mkdir(parents=True, exist_ok=True)
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
            if not w.isVisible() or type(w).__name__ not in {'PlotCanvas','QTableWidget','FastHeatmapWidget'}: continue
            p=w.mapTo(window,w.rect().topLeft())
            controls.append({'kind':type(w).__name__,'text':'','bounds':[p.x(),p.y(),w.width(),w.height()]})
    records[name] = controls
def run():
    try:
        window.open_document('optimization','scan')
        shell=window.workbench; doc=shell._widgets['optimization:scan']; rail=shell.object_rail
        captured=[]
        shell._jobs.submit=lambda kind,payload:captured.append({'kind':kind,'payload':payload}) or None
        def selection(paths):
            shell._selected_optimization=set(paths); doc.set_selected(set(paths))
            for i in range(rail.list.count()):
                item=rail.list.item(i)
                item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in paths else Qt.CheckState.Unchecked)
        selection([]); capture('empty',doc)
        selection(['surfaces[0].radius_mm']); capture('one',doc)
        shell._start_scan()
        doc.show_scan_progress(.42,'扫描中'); capture('progress',doc)
        doc.scan_progress_host.hide(); doc.run_button.setEnabled(True)
        doc.show_scan_status('勾选 1～2 个变量并运行后，这里显示响应曲线。')
        selection(['surfaces[0].radius_mm','surfaces[0].distance_to_next_mm'])
        doc.mode.setCurrentText('二维扫描'); capture('two',doc); shell._start_scan()
        for name,mode,paths in [('line','一维扫描',['surfaces[0].radius_mm']),('heatmap','二维扫描',['surfaces[0].radius_mm','surfaces[0].distance_to_next_mm'])]:
            source=root/('tests/golden/ui-current/scan/'+name+'-job-result.json')
            if not source.exists(): continue
            selection(paths); doc.mode.setCurrentText(mode);doc.points.setValue(5)
            result=json.loads(source.read_text(encoding='utf-8-sig'))['data']
            for col in range(len(paths)):
                axis=[point[col] for point in result['parameter_grid']]
                doc.range_table.item(col,1).setText(f'{min(axis):g}')
                doc.range_table.item(col,2).setText(f'{max(axis):g}')
            doc.apply_scan_result(result,'耦合效率')
            doc.show_scan_progress(1,'扫描完成',state='complete');doc.run_button.setEnabled(True)
            capture(name,doc)
        (target/'requests.json').write_text(json.dumps(captured,ensure_ascii=False,indent=2),encoding='utf-8')
        (target/'geometry.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({name:len(value) for name,value in records.items()}))
    finally:
        window.context.services.usage.close(); app.quit()
QTimer.singleShot(500,run)
app.exec()
