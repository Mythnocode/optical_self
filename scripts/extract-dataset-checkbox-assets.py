"""Export Fusion checkbox indicators from the retained original Qt theme.

Run with --scale 1, 1.5 or 2. Only an offscreen source widget is rendered;
no user settings, projects or jobs are opened.
"""
import argparse
import json
import os
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--scale', type=float, choices=(1, 1.5, 2), required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_SCALE_FACTOR=str(args.scale))
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QCheckBox, QStyle, QStyleOptionButton
from frontend_pyside.core.ui_theme import apply_application_theme

app = QApplication([])
apply_application_theme(app)
checkbox = QCheckBox('L1 / L1 前表面 / 曲率')
checkbox.resize(300, 30)
checkbox.ensurePolished()
target = root / 'frontend_web/public/assets/dataset'
target.mkdir(parents=True, exist_ok=True)
records = []
for checked in (False, True):
    checkbox.setChecked(checked)
    option = QStyleOptionButton()
    checkbox.initStyleOption(option)
    indicator = checkbox.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, checkbox)
    image = QImage(round(indicator.width()*args.scale), round(indicator.height()*args.scale), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(args.scale)
    image.fill(0)
    option.rect = QRect(0, 0, indicator.width(), indicator.height())
    option.state &= ~(QStyle.StateFlag.State_HasFocus | QStyle.StateFlag.State_MouseOver)
    painter = QPainter(image)
    checkbox.style().drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorCheckBox, option, painter, checkbox)
    painter.end()
    name = f'checkbox-{"checked" if checked else "unchecked"}-{args.scale:g}x.png'
    if not image.save(str(target/name)):
        raise RuntimeError(f'Could not save {name}')
    records.append(dict(file=name, logical_size=[indicator.width(),indicator.height()], raster_size=[image.width(),image.height()], device_pixel_ratio=args.scale))
print(json.dumps(records))
