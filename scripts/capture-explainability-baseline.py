"""Isolated original Qt contribution views using the actual API job result."""
import json, os, sys, tempfile
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
isolation = Path(tempfile.mkdtemp(prefix='optical-explain-baseline-'))
os.environ.update(QT_QPA_PLATFORM='offscreen', APPDATA=str(isolation/'appdata'), LOCALAPPDATA=str(isolation/'localappdata'), OPTICAL_USAGE_DIR=str(isolation/'usage'), USER_DATA_DIR=str(isolation/'data'))
from PySide6.QtCore import QSettings, QTimer, QEventLoop
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QComboBox, QPushButton
from frontend_pyside.app.bootstrap import create_main_window
from frontend_pyside.core.ui_theme import apply_application_theme
from shared_presentation.explainability import CHARTS
app = QApplication([])
for font in ['msyh.ttc','msyhbd.ttc']:
    QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts')/font))
app.setOrganizationName('OpticalMigrationVisualCapture'); app.setApplicationName('ExplainabilityBaseline')
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(isolation/'settings'))
apply_application_theme(app)
window=create_main_window();window.resize(1280,800);window.show()
target=root/'tests/golden/ui-baseline/explainability';target.mkdir(parents=True,exist_ok=True)
current=root/'tests/golden/ui-current/explainability';geometry={}
def settle():
    loop=QEventLoop();QTimer.singleShot(160,loop.quit);loop.exec()
def capture(name,doc):
    settle();window.grab();settle();window.grab().save(str(target/(name+'.png')))
    controls=[]
    for scope in [doc,window.workbench.object_rail]:
        for w in scope.findChildren(QWidget):
            if not w.isVisible():continue
            if isinstance(w,(QLabel,QComboBox,QPushButton)):
                text=w.currentText() if isinstance(w,QComboBox) else w.text()
            elif type(w).__name__=='PlotCanvas':text=''
            else:continue
            p=w.mapTo(window,w.rect().topLeft());controls.append({'kind':type(w).__name__,'text':text,'bounds':[p.x(),p.y(),w.width(),w.height()]})
    for w in [doc,window.workbench.object_rail,window.workbench.secondary,doc.workspace]:
        p=w.mapTo(window,w.rect().topLeft());controls.append({'kind':'layout:'+type(w).__name__,'text':w.objectName(),'bounds':[p.x(),p.y(),w.width(),w.height()]})
    geometry[name]=controls
def run():
    try:
        window.open_document('explainability','global_contrib')
        shell=window.workbench;doc=shell._widgets['explainability:global_contrib']
        shell._model_list_key='baseline-ignore-pending-model-list'
        shell._trained_models=[];shell.object_rail.set_catalogs([],[]);doc.set_trained_models([]);capture('empty',doc)
        records=[]
        for name in ['models','structure-models']:
            records+=json.loads((current/(name+'.json')).read_text(encoding='utf-8'))['data']['models']
        records.sort(key=lambda r:(r.get('created_at') or '9999',r['model_id']))
        shell._on_registry_models_changed(records)
        doc.set_trained_models(shell._trained_models)
        capture('selected',doc)
        body=json.loads((current/'design-result.json').read_text(encoding='utf-8'))['data']
        doc.set_model(next(r['title'] for r in shell._trained_models if r['id']==body['model_id']))
        doc._dataset_cache[doc._design_cache_key(body['model_id'])]=body
        for index,chart in enumerate(CHARTS):
            doc.shap_chart.setCurrentText(chart);doc._render_design_variable(body)
            capture(f'chart-{index}',doc)
        if (current/'xgboost-result.json').exists():
            residual=json.loads((current/'xgboost-result.json').read_text(encoding='utf-8'))['data']
            doc.set_model(next(r['title'] for r in shell._trained_models if r['id']==residual['model_id']))
            doc.shap_chart.setCurrentText('瀑布图');doc._render_design_variable(residual)
            capture('xgboost-waterfall',doc)
        (target/'geometry.json').write_text(json.dumps(geometry,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Captured empty, selected and six original charts')
    finally:window.close();app.quit()
QTimer.singleShot(0,run);app.exec()
