from __future__ import annotations

"""Shared visual tokens for the teaching ExperimentScene projections.

The 2-D side/top engineering projections deliberately mirror the visual language
of the Quick3D workbench.  The values below are plain strings so tests can also
verify that the QML scene uses the same palette without importing Qt.
"""

SCENE_BACKGROUND = "#F4F7FA"
TABLE_SURFACE = "#DCE5EA"
TABLE_EDGE = "#BAC7CF"
TABLE_HOLE = "#AEBBC4"
AXIS = "#475467"
TEXT = "#101828"
TEXT_SECONDARY = "#475467"

FRAME = "#222C35"
BODY = "#26313A"
LASER_BODY = "#E7ECEF"
POST = "#9AA7B1"
BASE = "#35414A"
GLASS = "#6DD5E7"
GLASS_EDGE = "#51B6D6"
SPLITTER_GLASS = "#A8E0EA"
MIRROR_FACE = "#DDE4EA"
BEAM = "#FF0000"
SELECTION = "#155EEF"

__all__ = [
    "SCENE_BACKGROUND", "TABLE_SURFACE", "TABLE_EDGE", "TABLE_HOLE",
    "AXIS", "TEXT", "TEXT_SECONDARY",
    "FRAME", "BODY", "LASER_BODY", "POST", "BASE", "GLASS", "GLASS_EDGE",
    "SPLITTER_GLASS", "MIRROR_FACE", "BEAM", "SELECTION",
]
