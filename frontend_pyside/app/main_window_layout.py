"""Layout assembly for the refactored optical workbench.

The application has two UI shells rather than one legacy page stack:

* the ordinary shell is ``一级栏 + 二级栏 + 对象栏 + 文档页签``;
* teaching is a separate full-canvas shell with floating tools.

The mode stack below only switches those three shell modes.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from frontend_pyside.app.workbench_shell import (
    PrimaryBar,
    WorkbenchShell,
)
from frontend_pyside.modules.home import WorkflowHome
from frontend_pyside.modules.teaching import TeachingShell


@dataclass(slots=True)
class MainWindowWidgets:
    central: QWidget
    primary: PrimaryBar
    mode_stack: QStackedWidget
    home: WorkflowHome
    workbench: WorkbenchShell
    teaching: TeachingShell


def build_main_window_layout(window: QMainWindow, context) -> MainWindowWidgets:
    central = QWidget(window)
    central.setObjectName("centralRoot")
    root = QVBoxLayout(central)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    primary = PrimaryBar(central)
    root.addWidget(primary)

    mode_stack = QStackedWidget(central)
    mode_stack.setObjectName("shellModeStack")

    home = WorkflowHome(mode_stack)
    workbench = WorkbenchShell(context, mode_stack)
    teaching = TeachingShell(context, mode_stack)
    mode_stack.addWidget(home)
    mode_stack.addWidget(workbench)
    mode_stack.addWidget(teaching)
    root.addWidget(mode_stack, 1)

    # There is intentionally no footer or permanent status bar.  Page metrics
    # belong to the active document, and teaching metrics belong to its floating
    # result window.  The main window uses its title/tooltip for transient notices.
    window.setCentralWidget(central)
    window.statusBar().hide()

    return MainWindowWidgets(
        central=central,
        primary=primary,
        mode_stack=mode_stack,
        home=home,
        workbench=workbench,
        teaching=teaching,
    )


__all__ = ["MainWindowWidgets", "build_main_window_layout"]
