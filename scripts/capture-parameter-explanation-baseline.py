"""Isolated original Qt parameter page, using a real service result."""
import json, os, sys, tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
isolation=Path(tempfile.mkdtemp(prefix='optical-parameter-baseline-'))
os.environ.update(QT_QPA_PLATFORM='offscreen',APPDATA=str(isolation/'appdata'),LOCALAPPDATA=str(isolation/'localappdata'),OPTICAL_USAGE_DIR=str(isolation/'usage'),USER_DATA_DIR=str(isolation/'data'))
from PySide6.QtCore import QSettings, QTimer, QEventLoop, Qt, QCoreApplication, QEvent
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication,QWidget,QLabel,QComboBox,QAbstractButton,QListWidget,QLineEdit
from frontend_pyside.app.bootstrap import create_main_window
from frontend_pyside.core.ui_theme import apply_application_theme
app=QApplication([])
for font in ['msyh.ttc','msyhbd.ttc']:QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts')/font))
app.setOrganizationName('OpticalMigrationVisualCapture');app.setApplicationName('ParameterBaseline')
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(isolation/'settings'))
apply_application_theme(app)
window=create_main_window();window.resize(1280,800);window.show()
target=root/'tests/golden/ui-baseline/parameter-explanation';target.mkdir(parents=True,exist_ok=True)
current=root/'tests/golden/ui-current/explainability';geometry={}
def settle():
    loop=QEventLoop();QTimer.singleShot(160,loop.quit);loop.exec();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
def capture(name,doc):
    settle();window.grab();settle();window.grab().save(str(target/(name+'.png')))
    controls=[]
    for w in doc.findChildren(QWidget) + window.workbench.object_rail.findChildren(QWidget):
        if not w.isVisible():continue
        if isinstance(w,(QLabel,QComboBox,QAbstractButton,QLineEdit)):
            text=w.currentText() if isinstance(w,QComboBox) else w.text()
        elif type(w).__name__ in ['PlotCanvas','FormulaImageLabel','QListWidget'] or w.objectName() in ['ExplainSelectionCard','ExplainChainCard','ExplainChainScroll','ExplainFeaturePicker']:
            text=w.objectName()
        else:continue
        p=w.mapTo(window,w.rect().topLeft());row={'kind':type(w).__name__,'text':text,'bounds':[p.x(),p.y(),w.width(),w.height()], 'font':{'family':w.font().family(),'point_size':w.font().pointSizeF(),'pixel_size':w.font().pixelSize()}}
        if type(w).__name__=='FormulaImageLabel':row['source_size']=[w._source_pixmap.width(),w._source_pixmap.height()]
        controls.append(row)
    if doc.feature_picker.isVisible():
        for i in range(doc.feature_picker.count()):
            item=doc.feature_picker.item(i);rect=doc.feature_picker.visualItemRect(item);p=doc.feature_picker.viewport().mapTo(window,rect.topLeft())
            controls.append({'kind':'ranking-row','text':item.text(),'bounds':[p.x(),p.y(),rect.width(),rect.height()]})
    rail=window.workbench.object_rail.list
    for i in range(rail.count()):
        item=rail.item(i);rect=rail.visualItemRect(item);p=rail.viewport().mapTo(window,rect.topLeft())
        controls.append({'kind':'parameter-row','text':item.text(),'bounds':[p.x(),p.y(),rect.width(),rect.height()]})
    geometry[name]=controls
def run():
    try:
        window.open_document('explainability','param_trend');shell=window.workbench;doc=shell._widgets['explainability:param_trend']
        shell._model_list_key='baseline-ignore-pending-model-list';shell._trained_models=[];shell.object_rail.set_catalogs([],[]);doc.set_trained_models([]);capture('empty',doc)
        records=[]
        for name in ['models','structure-models']:records+=json.loads((current/(name+'.json')).read_text(encoding='utf-8'))['data']['models']
        records.sort(key=lambda r:(r.get('created_at') or '9999',r['model_id']))
        shell._on_registry_models_changed(records);doc.set_trained_models(shell._trained_models);capture('selected',doc)
        body=json.loads((current/'param-native-result.json').read_text(encoding='utf-8'))['data']
        doc.set_model(next(r['title'] for r in shell._trained_models if r['id']==body['model_id']))
        doc._render_shap(body);capture('curve',doc)
        doc.set_selected('surfaces[0].radius_mm');shell.object_rail.list.setCurrentRow(0)
        doc._render_shap(body);capture('curve-l1',doc)
        doc.set_selected('surfaces[0].conic');shell.object_rail.list.setCurrentRow(1)
        doc._render_shap(body);capture('curve-unavailable',doc)
        doc.set_selected('');shell.object_rail.list.setCurrentRow(-1);doc._render_shap(body)
        doc.param_view_buttons[1].click();capture('chain-three',doc)
        doc.chain_view.verticalScrollBar().setValue(doc.chain_view.verticalScrollBar().maximum());capture('chain-bottom',doc)
        doc.chain_view.verticalScrollBar().setValue(0)
        for i in range(doc.feature_picker.count()):doc.feature_picker.item(i).setCheckState(Qt.CheckState.Unchecked)
        capture('chain-none',doc)
        doc.feature_picker.item(0).setCheckState(Qt.CheckState.Checked);capture('chain-one',doc)
        residual=json.loads((current/'param-xgboost-native-result.json').read_text(encoding='utf-8'))['data']
        doc.set_model(next(r['title'] for r in shell._trained_models if r['id']==residual['model_id']))
        doc.set_selected('surfaces[0].radius_mm');shell.object_rail.list.setCurrentRow(0)
        doc.param_view_buttons[0].click();doc._render_shap(residual);capture('xgboost-curve',doc)
        doc.param_view_buttons[1].click();capture('xgboost-chain-three',doc)
        (target/'geometry.json').write_text(json.dumps(geometry,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Captured original parameter curve and four chain selection/scroll states.')
    finally:window.close();app.quit()
QTimer.singleShot(0,run);app.exec()
