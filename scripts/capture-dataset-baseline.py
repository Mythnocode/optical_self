"""Capture original dataset controls and the original submitted generation contract."""
import argparse,json,os,sys,tempfile
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path)
parser.add_argument('--width',type=int,default=1280)
parser.add_argument('--height',type=int,default=800)
parser.add_argument('--scale',default='1')
parser.add_argument('--visual-only',action='store_true')
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
isolation=Path(tempfile.mkdtemp(prefix='optical-dataset-baseline-'))
os.environ.update(QT_QPA_PLATFORM='offscreen',QT_SCALE_FACTOR=args.scale,APPDATA=str(isolation/'appdata'),LOCALAPPDATA=str(isolation/'localappdata'),OPTICAL_USAGE_DIR=str(isolation/'usage'),USER_DATA_DIR=str(isolation/'data'))
from PySide6.QtCore import QSettings,QTimer,QEventLoop
from PySide6.QtGui import QFontDatabase,QFontInfo,QPalette
from PySide6.QtWidgets import QApplication,QWidget,QLabel,QDoubleSpinBox,QLineEdit,QComboBox,QPushButton,QToolButton,QCheckBox,QFrame
from frontend_pyside.app.bootstrap import create_main_window
from frontend_pyside.core.ui_theme import apply_application_theme
app=QApplication([])
for name in ['msyh.ttc','msyhbd.ttc']:
    QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/name))
app.setOrganizationName('OpticalMigrationVisualCapture');app.setApplicationName('DatasetBaseline')
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(isolation/'settings'))
apply_application_theme(app)
window=create_main_window();window.resize(args.width,args.height);window.show()
target=args.output or root/'tests/golden/ui-baseline/dataset'
target.mkdir(parents=True,exist_ok=True)
records={}
def settle():
    loop=QEventLoop();QTimer.singleShot(120,loop.quit);loop.exec()

def font_details(widget):
    font=QFontInfo(widget.font());metrics=widget.fontMetrics()
    return dict(family=font.family(),pixel_size=font.pixelSize(),point_size=font.pointSizeF(),weight=font.weight(),height=metrics.height(),ascent=metrics.ascent(),descent=metrics.descent())
def capture(name,document):
    settle()
    window.grab().save(str(target/(name+'.png')))
    controls=[]
    for w in document.findChildren(QWidget):
        if not w.isVisible() or not isinstance(w,(QLabel,QDoubleSpinBox,QLineEdit,QComboBox,QPushButton,QToolButton,QCheckBox)):continue
        if isinstance(w,QLineEdit) and isinstance(w.parentWidget(),QDoubleSpinBox):continue
        p=w.mapTo(window,w.rect().topLeft())
        controls.append({'kind':type(w).__name__,'text':w.currentText() if isinstance(w,QComboBox) else w.text(),'bounds':[p.x(),p.y(),w.width(),w.height()], 'font':font_details(w),'enabled':w.isEnabled(),'foreground':w.palette().color(QPalette.ColorRole.Text if isinstance(w,(QLineEdit,QDoubleSpinBox,QComboBox)) else QPalette.ColorRole.ButtonText if isinstance(w,(QPushButton,QToolButton)) else QPalette.ColorRole.WindowText).name()})
    rail=window.workbench.object_rail
    rail_controls=[]
    for w in rail.findChildren(QLabel):
        if not w.isVisible():continue
        p=w.mapTo(window,w.rect().topLeft())
        rail_controls.append({'kind':type(w).__name__,'text':w.text(),'bounds':[p.x(),p.y(),w.width(),w.height()]})
    p=rail.list.mapTo(window,rail.list.rect().topLeft())
    frames=[]
    for frame in [window.findChild(QFrame,'PrimaryBar'),window.findChild(QFrame,'SecondaryBar'),document,document.data_group,document.training_group,rail]:
        if frame is None:continue
        position=frame.mapTo(window,frame.rect().topLeft())
        frames.append(dict(name=frame.objectName() or type(frame).__name__,bounds=[position.x(),position.y(),frame.width(),frame.height()]))
    records[name]={'controls':controls,'rail':rail_controls,'rail_list':[p.x(),p.y(),rail.list.width(),rail.list.height()], 'frames':frames,'device_pixel_ratio':window.devicePixelRatioF(),'window_size':[window.width(),window.height()]}
def run():
    try:
        window.open_document('model','dataset')
        document=window.workbench._widgets['model:dataset']
        capture('import-collapsed',document)
        document.training_more_button.click();capture('import-expanded',document)
        document.training_mode_button.click();capture('sequence-import',document)
        document.training_more_button.click();capture('sequence-training-expanded',document)
        document.source_mode.setCurrentIndex(document.source_mode.findData('generate'));capture('sequence-generation-collapsed',document)
        document.generate_more_button.click();capture('sequence-generation-expanded',document)
        document.sequence_variable_button.click();capture('sequence-variables-expanded',document)
        document.generation_mode_button.click();capture('fixed-generation-expanded',document)
        document.generate_more_button.click();capture('fixed-generation-collapsed',document)
        if args.visual_only:
            (target/'geometry.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'output':str(target),'states':len(records),'device_pixel_ratio':window.devicePixelRatioF()}))
            return
        captured=[]
        window.workbench._jobs.submit=lambda kind,payload:captured.append({'kind':kind,'payload':payload}) or None
        document.samples.setValue(8);document.precision.setCurrentText('129×129')
        window.workbench._start_dataset_generation()
        document.generation_mode_button.click();window.workbench._start_dataset_generation()
        (target/'generation-requests.json').write_text(json.dumps(captured,ensure_ascii=False,indent=2),encoding='utf-8')
        document.generate_more_button.setChecked(False)
        capture('sequence-generation-pending',document)
        window.workbench._update_pending_generated_dataset(.37)
        capture('sequence-generation-progress',document)
        window.workbench._set_pending_generated_dataset_state('generated_failed','生成失败',error='序列模型至少需要 10 个有效系统样本')
        capture('sequence-generation-failed',document)
        (target/'geometry.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({key:len(value['controls']) for key,value in records.items()}))
    finally:
        window.context.services.usage.close();app.quit()
QTimer.singleShot(500,run)
app.exec()
