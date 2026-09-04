from __future__ import annotations


from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.basic import (
    Badge,
    Card,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared.components.tables import DataTable
from frontend_pyside.shared.icons import icon
from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.lifecycle import Debouncer

from .surface_delegate import MaterialDelegate, SurfaceFloatDelegate, SurfaceTypeDelegate


from .editor_parts import SurfaceCommandMixin, SurfacePropertyMixin, SurfaceTableMixin

class OpticalSystemEditor(SurfacePropertyMixin, SurfaceTableMixin, SurfaceCommandMixin, QWidget):


    changed = Signal()
    operationCommitted = Signal(str)
    surfaceSelected = Signal(int)
    surfaceActivated = Signal(int)

    COL_NUMBER = 0
    COL_GROUP = 1
    COL_NAME = 2
    COL_TYPE = 3
    COL_RADIUS = 4
    COL_THICKNESS = 5
    COL_MATERIAL = 6
    COL_APERTURE = 7
    COL_FEATURE = 8
    COL_ENABLED = 9

    def __init__(self, project_context, parent=None):
        super().__init__(parent)
        self.context = project_context
        self._loading_table = False
        self._loading_properties = False
        self._dynamic_controls: dict[str, QWidget] = {}
        self._dynamic_specs = {}
        self._search_debouncer = Debouncer(250, self._filter_rows, self)

        root = QVBoxLayout(self)
        root.setContentsMargins(7, 7, 7, 7)
        root.setSpacing(7)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        # Surface count is already shown once in the window header.  Keep the
        # compatibility badge object for mixins, but do not repeat the same count
        # in the editing toolbar.
        self.stats_badge = Badge("", "info")
        self.stats_badge.hide()

        self.search_toggle = QToolButton()
        self.search_toggle.setObjectName("editorActionButton")
        self.search_toggle.setText("搜索")
        self.search_toggle.setCheckable(True)
        self.search_toggle.setToolTip("按面号、元件组、名称、材料、类型或关键参数搜索；Ctrl+F 也可聚焦搜索")
        toolbar.addWidget(self.search_toggle)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索 Surface…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(220)
        self.search.setVisible(False)
        toolbar.addWidget(self.search, 1)

        self.lens_filter = QComboBox()
        self.lens_filter.setMinimumWidth(118)
        self.lens_filter.setMaximumWidth(150)
        self.lens_filter.setToolTip("可选：按元件组筛选；Surface 顺序本身不依赖固定双表面镜片结构")
        toolbar.addWidget(self.lens_filter)
        toolbar.addStretch(1)

        add_button = QToolButton()
        add_button.setObjectName("editorActionButton")
        add_button.setText("新增")
        add_button.setIcon(icon("add", theme.PRIMARY, 17))
        add_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        add_menu = QMenu(add_button)
        add_lens_action = add_menu.addAction(icon("add", theme.PRIMARY, 16), "新增双面透镜")
        add_surface_to_group_action = add_menu.addAction(icon("add", theme.PRIMARY, 16), "插入面到当前元件组")
        add_surface_action = add_menu.addAction(icon("add", theme.PRIMARY, 16), "新增独立表面")
        add_menu.addSeparator()
        special_menu = add_menu.addMenu("新增特殊表面")
        special_actions = {}
        for type_name in ("光阑", "反射镜", "衍射光栅", "坐标断点", "二元衍射面", "探测器/像面", "用户自定义面"):
            special_actions[type_name] = special_menu.addAction(type_name)
        add_menu.addSeparator()
        duplicate_surface_action = add_menu.addAction(icon("copy", theme.PRIMARY, 16), "复制当前表面")
        duplicate_group_action = add_menu.addAction(icon("copy", theme.PRIMARY, 16), "复制当前元件组")
        add_button.setMenu(add_menu)
        toolbar.addWidget(add_button)

        remove_button = QToolButton()
        remove_button.setObjectName("editorActionButton")
        remove_button.setText("删除面")
        remove_button.setIcon(icon("delete", theme.ERROR, 17))
        remove_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        remove_button.setToolTip("删除当前选中的光学表面")
        toolbar.addWidget(remove_button)

        columns_button = QToolButton()
        columns_button.setObjectName("editorActionButton")
        columns_button.setText("列设置")
        columns_button.setIcon(icon("list", theme.PRIMARY, 17))
        columns_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        columns_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        columns_menu = QMenu(columns_button)
        for label, column, checked in [
            ("元件组", self.COL_GROUP, True),
            ("表面类型", self.COL_TYPE, True),
            ("半口径", self.COL_APERTURE, True),
            ("关键参数", self.COL_FEATURE, True),
            ("启用状态", self.COL_ENABLED, False),
        ]:
            action = QAction(label, columns_menu)
            action.setCheckable(True)
            action.setChecked(checked)
            action.toggled.connect(lambda visible, col=column: self._set_column_visible(col, visible))
            columns_menu.addAction(action)
        columns_button.setMenu(columns_menu)
        toolbar.addWidget(columns_button)

        self.properties_button = QToolButton()
        self.properties_button.setObjectName("editorActionButton")
        self.properties_button.setText("表面属性…")
        self.properties_button.setToolTip("打开选中 Surface 的高级参数窗口；常用公共参数可直接在表格中编辑")
        toolbar.addWidget(self.properties_button)
        root.addLayout(toolbar)

        self.table_card = Card("顺序表面编辑器", compact=True)
        table_header = QHBoxLayout()
        hint = QLabel("按 Surface 顺序编辑；公共列双击直接修改，高级参数使用“表面属性…”。元件组只是可选标记，不限制一个元件必须有两个表面。")
        hint.setObjectName("helperText")
        hint.setWordWrap(True)
        table_header.addWidget(hint, 1)
        self.visible_count = Badge("0 / 0 面", "info")
        self.visible_count.setVisible(False)
        table_header.addWidget(self.visible_count)
        self.table_card.body.addLayout(table_header)

        self.table = DataTable(0, 10)
        self.table.setObjectName("lensDataTable")
        self.table.setHorizontalHeaderLabels([
            "面号", "元件组", "表面名称", "表面类型",
            "曲率半径 R / mm", "厚度或后间隔 / mm", "材料/介质",
            "半口径 / mm", "关键参数", "启用",
        ])
        self.table.setMinimumHeight(330)
        self.table.setTabKeyNavigation(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.setItemDelegateForColumn(self.COL_TYPE, SurfaceTypeDelegate(self.table))
        self.table.setItemDelegateForColumn(self.COL_RADIUS, SurfaceFloatDelegate(self.table))
        self.table.setItemDelegateForColumn(self.COL_THICKNESS, SurfaceFloatDelegate(self.table, minimum=0.0))
        self.table.setItemDelegateForColumn(self.COL_MATERIAL, MaterialDelegate(self.table))
        self.table.setItemDelegateForColumn(self.COL_APERTURE, SurfaceFloatDelegate(self.table, minimum=1.0e-9))
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self.COL_NUMBER, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_GROUP, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_FEATURE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_ENABLED, QHeaderView.ResizeMode.Fixed)
        widths = {
            self.COL_NUMBER: 58,
            self.COL_GROUP: 84,
            self.COL_TYPE: 108,
            self.COL_RADIUS: 135,
            self.COL_THICKNESS: 150,
            self.COL_MATERIAL: 110,
            self.COL_APERTURE: 112,
            self.COL_FEATURE: 210,
            self.COL_ENABLED: 66,
        }
        for column, width in widths.items():
            self.table.setColumnWidth(column, width)
        self.table.setColumnHidden(self.COL_ENABLED, True)
        self.table_card.body.addWidget(self.table, 1)
        root.addWidget(self.table_card, 1)

        self.detail_card = QFrame()
        self.detail_card.setObjectName("propertyDrawer")
        drawer = QVBoxLayout(self.detail_card)
        drawer.setContentsMargins(10, 7, 10, 9)
        drawer.setSpacing(6)

        detail_header = QHBoxLayout()
        detail_header.setSpacing(7)
        self.detail_toggle = QToolButton()
        self.detail_toggle.setObjectName("propertyDrawerToggle")
        self.detail_toggle.setCheckable(True)
        self.detail_toggle.setChecked(False)
        self.detail_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.detail_toggle.setText("展开表面属性")
        self.detail_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        detail_header.addWidget(self.detail_toggle)
        self.selected_badge = Badge("未选择", "info")
        detail_header.addWidget(self.selected_badge)
        self.selection_context = QLabel("选择表面后，可编辑公共参数及该类型独有参数。")
        self.selection_context.setObjectName("helperText")
        self.selection_context.setWordWrap(True)
        detail_header.addWidget(self.selection_context, 1)
        drawer.addLayout(detail_header)

        self.detail_content = QWidget()
        detail_body = QVBoxLayout(self.detail_content)
        detail_body.setContentsMargins(0, 0, 0, 0)
        detail_body.setSpacing(6)
        self.property_tabs = QTabWidget()
        self.property_tabs.setDocumentMode(True)
        self.property_tabs.addTab(self._build_basic_properties(), "公共参数")
        self.property_tabs.addTab(self._build_profile_properties(), "面形与孔径")
        self.dynamic_content = QWidget()
        self.dynamic_layout = QGridLayout(self.dynamic_content)
        self.dynamic_layout.setContentsMargins(10, 8, 10, 8)
        self.dynamic_layout.setHorizontalSpacing(0)
        self.dynamic_layout.setVerticalSpacing(9)
        self.dynamic_page = self._scroll_page(self.dynamic_content)
        self.dynamic_tab_index = self.property_tabs.addTab(self.dynamic_page, "类型专用参数")
        self.property_tabs.addTab(self._build_engineering_properties(), "制造与备注")
        detail_body.addWidget(self.property_tabs)

        footer = QHBoxLayout()
        self.previous_button = SecondaryButton("上一面")
        self.next_button = SecondaryButton("下一面")
        self.reset_button = SecondaryButton("重新载入当前表面")
        self.apply_button = PrimaryButton("已自动应用")
        self.reset_button.setVisible(False)
        self.apply_button.setVisible(False)
        self.previous_button.setIcon(icon("previous", theme.PRIMARY, 16))
        self.next_button.setIcon(icon("next", theme.PRIMARY, 16))
        self.reset_button.setIcon(icon("reset", theme.PRIMARY, 16))
        self.apply_button.setIcon(icon("check", theme.TEXT_INVERSE, 16))
        footer.addWidget(self.previous_button)
        footer.addWidget(self.next_button)
        auto_apply_hint = QLabel("修改完成后自动写入当前项目，并由完整镜头编辑器记录撤销历史。")
        auto_apply_hint.setObjectName("helperText")
        auto_apply_hint.setWordWrap(True)
        auto_apply_hint.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        footer.addWidget(auto_apply_hint, 1)
        footer.addWidget(self.reset_button)
        footer.addWidget(self.apply_button)
        detail_body.addLayout(footer)
        self.detail_content.setVisible(False)
        drawer.addWidget(self.detail_content)
        root.addWidget(self.detail_card)

        add_lens_action.triggered.connect(self._add_lens)
        add_surface_to_group_action.triggered.connect(self._add_surface_to_current_group)
        add_surface_action.triggered.connect(lambda: self._add_surface_type("球面"))
        for type_name, action in special_actions.items():
            action.triggered.connect(lambda checked=False, name=type_name: self._add_surface_type(name))
        duplicate_surface_action.triggered.connect(self._duplicate_surface)
        duplicate_group_action.triggered.connect(self._duplicate_group)
        remove_button.clicked.connect(self._remove)
        self.detail_toggle.toggled.connect(self._toggle_detail)
        self.properties_button.clicked.connect(lambda: self._activate_surface(self.table.currentRow(), self.COL_NAME))
        self.table.currentCellChanged.connect(self._select)
        self.table.cellDoubleClicked.connect(self._table_double_clicked)
        self.table.itemChanged.connect(self._table_item_changed)
        self.apply_button.clicked.connect(self._apply)
        self.reset_button.clicked.connect(self._reset_current)
        self.previous_button.clicked.connect(lambda: self._step_selection(-1))
        self.next_button.clicked.connect(lambda: self._step_selection(1))
        self.search_toggle.toggled.connect(self.search.setVisible)
        self.search_toggle.toggled.connect(lambda checked: self.search.setFocus() if checked else None)
        self.search.textChanged.connect(self._search_debouncer.trigger)
        self.lens_filter.currentIndexChanged.connect(self._filter_rows)
        self.surface_type.currentTextChanged.connect(self._surface_type_changed)
        for control in (
            self.group_id, self.surface_name, self.radius, self.thickness,
            self.aperture, self.conic, self.clear_aperture, self.roughness,
            self.mechanical, self.note,
        ):
            signal = getattr(control, "editingFinished", None)
            if signal is not None:
                signal.connect(self._auto_apply_properties)
        for combo in (self.surface_type, self.material, self.aperture_type, self.coating):
            combo.currentIndexChanged.connect(self._auto_apply_properties)
            if combo.isEditable() and combo.lineEdit() is not None:
                combo.lineEdit().editingFinished.connect(self._auto_apply_properties)
        self.enabled.toggled.connect(self._auto_apply_properties)
        self.context.project_changed.connect(lambda _: self.reload())
        self.reload()

    def _auto_apply_properties(self, *_args) -> None:
        if self._loading_table or self._loading_properties:
            return
        self._apply()
