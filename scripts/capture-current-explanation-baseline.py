"""Capture the native current-system document using actual submitted results."""
import json,os,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
isolated=Path(tempfile.mkdtemp(prefix='optical-current-baseline-'))
os.environ.update(QT_QPA_PLATFORM='offscreen',APPDATA=str(isolated/'appdata'),LOCALAPPDATA=str(isolated/'localappdata'),USER_DATA_DIR=str(isolated/'data'),OPTICAL_USAGE_DIR=str(isolated/'usage'))
from PySide6.QtCore import QSettings,QTimer,QEventLoop,QCoreApplication,QEvent
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication,QWidget,QLabel,QComboBox,QAbstractButton
from frontend_pyside.app.bootstrap import create_main_window
from frontend_pyside.core.ui_theme import apply_application_theme
from frontend_pyside.infrastructure.api.clients import TrainingClient
from shared_contracts.project import ProjectSnapshot
app=QApplication([])
for name in ['msyh.ttc','msyhbd.ttc']:QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts')/name))
app.setOrganizationName('OpticalMigrationVisualCapture');app.setApplicationName('CurrentExplanationBaseline')
QSettings.setDefaultFormat(QSettings.Format.IniFormat);QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(isolated/'settings'))
apply_application_theme(app)
window=create_main_window();window.resize(1280,800);window.show()
target=root/'tests/golden/ui-baseline/current-explanation';target.mkdir(parents=True,exist_ok=True)
current=root/'tests/golden/ui-current/current-explanation';geometry={};requests=[]
def settle():
    loop=QEventLoop();QTimer.singleShot(160,loop.quit);loop.exec();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
def capture(name,doc):
    settle();window.grab();settle();window.grab().save(str(target/(name+'.png')))
    controls=[]
    for w in doc.findChildren(QWidget)+window.workbench.object_rail.findChildren(QWidget):
        if not w.isVisible():continue
        if isinstance(w,(QLabel,QComboBox,QAbstractButton)):text=w.currentText() if isinstance(w,QComboBox) else w.text()
        elif type(w).__name__ in ['PlotCanvas','FormulaImageLabel'] or w.objectName() in ['ExplainSummaryPanel','ExplainSummaryStack','ExplainFormulaCard']:text=w.objectName()
        else:continue
        p=w.mapTo(window,w.rect().topLeft());row=dict(kind=type(w).__name__,text=text,name=w.objectName(),bounds=[p.x(),p.y(),w.width(),w.height()])
        if type(w).__name__=='FormulaImageLabel':row['source_size']=[w._source_pixmap.width(),w._source_pixmap.height()]
        controls.append(row)
    geometry[name]=controls
def run():
    original=TrainingClient.explain_shap
    try:
        window.open_document('explainability','current_system');shell=window.workbench;doc=shell._widgets['explainability:current_system']
        shell._model_list_key='baseline-ignore-pending-model-list';shell._trained_models=[];shell.object_rail.set_catalogs([],[]);doc.set_trained_models([]);capture('empty',doc)
        catalog=root/'tests/golden/ui-current/explainability';records=[]
        for name in ['models','structure-models']:records+=json.loads((catalog/(name+'.json')).read_text(encoding='utf-8'))['data']['models']
        records.sort(key=lambda row:(row.get('created_at') or '9999',row['model_id']))
        shell._on_registry_models_changed(records);doc.set_trained_models(shell._trained_models);capture('selected',doc)
        doc.set_model(next(row['title'] for row in shell._trained_models if row['id']=='model-911a414b17b2'));capture('selected-uncomputed',doc)
        for model_name in ['rf','xgboost']:
            source=current/(model_name+'-result.json')
            if not source.exists():continue
            body=json.loads(source.read_text(encoding='utf-8'))['data']
            doc.set_model(next(row['title'] for row in shell._trained_models if row['id']==body['model_id']))
            project=ProjectSnapshot.model_validate(body['source_project'])
            signal=SimpleNamespace(connect=lambda callback:None)
            doc.context=SimpleNamespace(project=SimpleNamespace(project=project,formal_result=None),api_client=SimpleNamespace(completed=signal,failed=signal))
            TrainingClient.explain_shap=lambda self,token,model_id,payload:requests.append(dict(model=model_name,model_id=model_id,payload=payload))
            doc._current_cache.clear();doc._compute();doc._render_shap(body)
            for index,name in enumerate(['analysis','physics','next']):
                doc.summary_buttons[index].click();capture(model_name+'-'+name,doc)
        # Exercise the native programmatic compute guard; the user-facing button
        # is disabled and cannot submit this sequence model.
        doc.set_model(next(row['title'] for row in shell._trained_models if row['id']=='bilstm-a5731ab91eec'));doc._compute();capture('bilstm-compute-guard',doc)
        (target/'geometry.json').write_text(json.dumps(geometry,ensure_ascii=False,indent=2),encoding='utf-8')
        (target/'requests.json').write_text(json.dumps(requests,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Captured native current-system states and actual-source submission payloads.')
    finally:TrainingClient.explain_shap=original;window.close();app.quit()
QTimer.singleShot(0,run);app.exec()
