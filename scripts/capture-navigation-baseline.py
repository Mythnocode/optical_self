"""Render original navigation with its actual Qt font metrics, isolated from user settings."""
import argparse,json,os,sys,tempfile
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('--scale',default='1')
parser.add_argument('--width',type=int,default=1280)
parser.add_argument('--height',type=int,default=800)
parser.add_argument('--module',choices=['model','simulation','optimization','explainability'])
args=parser.parse_args()
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
isolated=Path(tempfile.mkdtemp(prefix='optical-nav-baseline-'))
os.environ.update(QT_QPA_PLATFORM='offscreen',QT_SCALE_FACTOR=args.scale,APPDATA=str(isolated/'appdata'),LOCALAPPDATA=str(isolated/'localappdata'),USER_DATA_DIR=str(isolated/'data'),OPTICAL_USAGE_DIR=str(isolated/'usage'))
from PySide6.QtCore import QSettings,QTimer,QEventLoop,QCoreApplication,QEvent
from PySide6.QtGui import QFontDatabase,QFontInfo
from PySide6.QtWidgets import QApplication,QToolButton,QFrame
from frontend_pyside.app.bootstrap import create_main_window
from frontend_pyside.core.ui_theme import apply_application_theme
app=QApplication([])
for name in ['msyh.ttc','msyhbd.ttc']:QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
app.setOrganizationName('OpticalMigrationVisualCapture');app.setApplicationName('NavigationBaseline')
QSettings.setDefaultFormat(QSettings.Format.IniFormat);QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(isolated/'settings'))
apply_application_theme(app)
window=create_main_window();window.resize(args.width,args.height);window.show()
directory=root/'tests/golden/ui-baseline/navigation'/('scale-'+args.scale+'-'+str(args.width)+'x'+str(args.height)+('-'+args.module if args.module else ''));directory.mkdir(parents=True,exist_ok=True)
records={}
def settle():
    loop=QEventLoop();QTimer.singleShot(120,loop.quit);loop.exec();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
def capture(name):
    settle();window.grab().save(str(directory/(name+'.png')))
    controls=[]
    for frame_name in ['PrimaryBar','SecondaryBar']:
        frame=window.findChild(QFrame,frame_name)
        if frame is None or not frame.isVisible():continue
        for widget in [frame]+frame.findChildren(QToolButton):
            if not widget.isVisible():continue
            pt=widget.mapTo(window,widget.rect().topLeft());font=QFontInfo(widget.font());fm=widget.fontMetrics()
            controls.append(dict(name=widget.objectName(),text=widget.text() if isinstance(widget,QToolButton) else frame_name,tooltip=widget.toolTip(),checked=widget.isChecked() if isinstance(widget,QToolButton) else False,bounds=[pt.x(),pt.y(),widget.width(),widget.height()],font=dict(family=font.family(),point_size=font.pointSizeF(),pixel_size=font.pixelSize(),weight=font.weight(),height=fm.height(),ascent=fm.ascent(),descent=fm.descent()),icon_size=[widget.iconSize().width(),widget.iconSize().height()] if isinstance(widget,QToolButton) else None,logical_dpi=widget.logicalDpiX(),device_pixel_ratio=widget.devicePixelRatioF()))
    records[name]=controls
def run():
    try:
        for module,page in [('model','dataset'),('simulation','lens_data'),('optimization','opt_vars'),('explainability','global_contrib')]:
            if args.module and args.module!=module:continue
            window.open_document(module,page);capture(module)
        # The original stacked document layout also affects ribbon height.
        # Use the existing, actually calculated model evidence for the populated state.
        current=root/'tests/golden/ui-current/explainability'
        if args.module in (None,'explainability') and (current/'models.json').exists() and (current/'design-result.json').exists():
            records_models=[]
            for catalog in ['models','structure-models']:
                records_models+=json.loads((current/(catalog+'.json')).read_text(encoding='utf-8'))['data']['models']
            records_models.sort(key=lambda row:(row.get('created_at') or '9999',row['model_id']))
            shell=window.workbench;doc=shell._widgets['explainability:global_contrib']
            shell._model_list_key='navigation-ignore-pending-model-list'
            shell._on_registry_models_changed(records_models);doc.set_trained_models(shell._trained_models)
            body=json.loads((current/'design-result.json').read_text(encoding='utf-8'))['data']
            doc.set_model(next(row['title'] for row in shell._trained_models if row['id']==body['model_id']))
            doc._dataset_cache[doc._design_cache_key(body['model_id'])]=body
            doc._render_design_variable(body);capture('explainability-populated')
        (directory/'geometry.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({key:[row for row in rows if row['name']=='PrimaryModuleButton'][:1] for key,rows in records.items()},ensure_ascii=True))
    finally:window.context.services.usage.close();window.close();app.quit()
QTimer.singleShot(300,run);app.exec()
