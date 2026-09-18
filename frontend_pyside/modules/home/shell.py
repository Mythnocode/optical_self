"""光学工作台的「首页」——工作流总览页。

页面形态
    「首页」是一个**五等分栏**的工作流地图：横向平分出 5 栏，每栏是一个
    业务阶段（教学 / 仿真 / 模型 / 优化 / 解释），栏内竖向排列若干可点击的
    卡片。窗口变窄时整排栏会横向滚动，而不是把栏挤扁。

怎么改这个页面
    页面内容**全部**由下面的 :data:`HOME_SECTIONS` 这张表描述。改栏标题、
    换图标、增删栏、增删卡片，都只改这张表，不要动下面的控件类。
    详情见 :data:`HOME_SECTIONS` 上方的说明。

跳转是怎么接出去的（重要）
    本页面**只负责发信号，不负责路由**，因此改版时不会碰到壳层代码：

    * ``nodeRequested(module, kind)`` —— 点了某张卡片。由
      ``app/main_window.py`` 的 ``_open_workflow_node()`` 接住，转成
      ``open_document(module, kind)``；``module == "teaching"`` 时改走
      ``navigate("teaching")``（教学是独立的一套壳，没有文档页签）。
    * ``homeActionRequested(action)`` —— 首页顶部的动作条。该动作条已移除，
      这条信号目前没有发射方，保留是为了不动壳层那边的连接。

    只要这两个信号的**名字和参数顺序不变**，首页怎么重画都不影响跳转。
    样式在 ``frontend_pyside/resources/qss/light.qss``（搜 ``WorkflowNode``
    那段），靠 objectName 匹配，改样式不用动 Python。
"""

from __future__ import annotations

from dataclasses import dataclass

from frontend_pyside.modules import shared as _shared

# 把 shared 模块的公开名字（Qt 控件类、icon()、_button() 等）灌进本模块的
# 全局命名空间，省掉一长串 import。
#
# 注意：这意味着像 QPushButton / QLabel / QVBoxLayout / Signal / icon 这类
# 名字在本文件里**没有显式 import**，直接写就能用。新写代码时如果用到
# shared 里没有的 Qt 类，会直接 NameError——那就得在本文件顶部显式 import。
globals().update(
    {
        name: value
        for name, value in vars(_shared).items()
        if not name.startswith("__")
    }
)


# ---------------------------------------------------------------------------
# 页面内容 —— 要改页面就改这一段
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NodeSpec:
    """一张可点击的工作流卡片。

    ``module`` 和 ``kind`` 会原封不动透传给壳层，用来决定「点开哪个页面」，
    所以必须落在下面这份已批准的词表里：

    * ``teaching`` —— 只认模块名，``kind`` 填什么都无所谓，点了直接切教学壳；
    * ``simulation`` —— ``lens_data`` / ``ray_layout`` / ``spot`` / ``coupling``；
    * ``model`` —— ``dataset`` / ``train_result`` / ``predict``；
    * ``optimization`` —— ``opt_vars`` / ``scan`` / ``opt_result``；
    * ``explainability`` —— ``global_contrib`` / ``param_trend`` / ``current_system``。

    填了词表以外的 ``kind`` **不会报错**，但点开的是一个空白占位页
    （``workbench_shell.py`` 里 ``document_factory`` 取不到就回退
    ``EmptyDocument``）。要接一个全新的页面，得先在
    ``modules/<模块>/`` 下建 ``PageSpec`` 并登记进该模块的 ``catalog.py``。

    另外注意：字段顺序是 ``(kind, module, ...)``，跟直觉相反。写反了不会报错，
    只会点开错的页——**建议一律写 ``kind=`` / ``module=`` 关键字**。
    """

    kind: str
    module: str
    title: str
    subtitle: str
    icon: str


@dataclass(frozen=True, slots=True)
class SectionSpec:
    """五等分栏中的一栏：一个标题头 + 可选的一段介绍文字 + 一竖排卡片。

    ``key`` 是本栏的稳定标识（跟跳转无关）。它还有一个副作用：会被挂到本栏
    每个部件上作为 Qt 动态属性 ``sectionKey``，于是 QSS 可以用属性选择器
    单独给某一栏设样式，例如::

        QLabel#WorkflowSectionTitle[sectionKey="teaching"] { ... }

    目前五栏共用同一套外观（见 light.qss 的通用规则），``sectionKey`` 只是
    留给"以后要突出某一栏"的接口；改了 ``key`` 只会让已有的专属规则失效
    （不报错，退回通用外观）。

    ``icon`` 是 ``resources/icons/`` 下的文件名，写错只会图标空白、不会报错。
    ``intro`` 留空 ``""`` 就不显示介绍段落；``nodes`` 留空 ``()`` 就是这一栏
    暂时不放卡片。两者可以只留其一。
    """

    key: str
    title: str
    subtitle: str
    icon: str
    nodes: tuple[NodeSpec, ...] = ()
    # 栏内介绍段落，显示在标题头和卡片之间，自动换行。留空则不占位。
    intro: str = ""
    # 本栏的强调色，用于标题条里的图标。五栏标题条都是深蓝实心、图标底为白色，
    # 所以这里的颜色要在白底上看得清；默认全局主蓝。
    accent: str = "#155EEF"


# 首页的全部内容。增删一栏就增删一个 SectionSpec，布局会自动重新等分，
# 没有别的地方需要同步修改。
#
# SectionSpec 字段：key（标识）/ title（栏标题）/ subtitle（栏标题下的灰字）/
#                   icon（栏图标）/ intro（栏内一段说明）/ nodes（栏内卡片）
# NodeSpec    字段：kind（页面） / module（一级入口）/ title（卡片标题）/
#                   subtitle（卡片副标题）/ icon（卡片图标）
#
# 每栏都写 intro，并给够本模块真实存在的入口——卡片点了要能落到那个页面上：
# 普通模块对应文档页，教学没有文档页签，kind 直接对应教学台的一个动作
# （见 main_window._open_workflow_node）。
HOME_SECTIONS: tuple[SectionSpec, ...] = (
    SectionSpec(
        key="teaching",
        title="教学",
        subtitle="认识器材与光路",
        icon="teaching",
        accent="#0E7490",
        intro=(
            "在实验台上摆好光源、镜片和接收端，画布即时显示光路示意。"
            "示意只说明光去了哪里；确认光路后再做正式波动光学计算，"
            "得到的成像与耦合数据才算结论。"
        ),
        nodes=(
            NodeSpec("teaching", "teaching", "教学入门", "打开教学实验台", "guide"),
            NodeSpec("equipment", "teaching", "器材库", "摆放光源与器件", "toolbox"),
            NodeSpec("analysis", "teaching", "成像与耦合", "正式计算光斑与效率", "intensity"),
            NodeSpec("sync_to_simulation", "teaching", "同步到仿真", "把教学场景写入工程", "next"),
        ),
    ),
    SectionSpec(
        key="simulation",
        title="仿真",
        subtitle="搭建、观察与测量",
        icon="simulation",
        intro=(
            "先建立镜头与光源，再由内核追迹光线并给出结果。"
            "四个入口按「搭—看—量—算」的顺序走，彼此共享同一份系统状态，"
            "任意一步改动的参数会自动让下游结果失效并标记为待重算。"
        ),
        nodes=(
            NodeSpec("lens_data", "simulation", "搭建系统", "进入仿真镜头表", "settings"),
            NodeSpec("ray_layout", "simulation", "观察结果", "进入仿真光路图", "chart"),
            NodeSpec("spot", "simulation", "测量数据", "进入仿真光斑图", "intensity"),
            NodeSpec("coupling", "simulation", "分析结果", "进入仿真光纤耦合", "phase"),
        ),
    ),
    SectionSpec(
        key="model",
        title="模型",
        subtitle="数据集与训练",
        icon="machine_learning",
        accent="#7C3AED",
        intro=(
            "先生成覆盖参数范围的样本，再用随机森林和 XGBoost 物理残差联合训练。"
            "数据集缺少解析物理特征时只训练随机森林，训练页会写明原因，"
            "不会把不完整的模型当作可用结果。"
        ),
        nodes=(
            NodeSpec("dataset", "model", "准备数据集", "生成样本或导入表格", "ml_dataset"),
            NodeSpec("train_result", "model", "训练模型", "随机森林与物理残差", "ml_train_result"),
            NodeSpec("predict", "model", "模型预测", "用当前镜头做推理", "ml_predict"),
        ),
    ),
    SectionSpec(
        key="optimization",
        title="优化",
        subtitle="目标与变量范围",
        icon="optimization",
        accent="#B45309",
        intro=(
            "先定优化目标和每个变量的取值范围，再运行扫描或寻优。"
            "代理模型只负责筛选候选，候选结果要经过正式光学计算复核，"
            "才允许写入镜头表。"
        ),
        nodes=(
            NodeSpec("opt_vars", "optimization", "优化变量", "选择变量与范围", "opt_vars"),
            NodeSpec("scan", "optimization", "参数扫描", "单变量与双变量扫描", "opt_scan"),
            NodeSpec("opt_result", "optimization", "优化结果", "候选对照与写入", "opt_result"),
        ),
    ),
    SectionSpec(
        key="explainability",
        title="解释",
        subtitle="模型为什么这样选",
        icon="explainability",
        accent="#155EEF",
        intro=(
            "用 SHAP 给出参数的平均贡献排序，再顺着物理公式链路回到"
            "曲率半径、厚度和圆锥系数。SHAP 只回答模型依赖谁，"
            "物理因果仍要用正式光学计算复核。"
        ),
        nodes=(
            NodeSpec("global_contrib", "explainability", "贡献排序", "平均 |SHAP| 排名", "explain_global"),
            NodeSpec("param_trend", "explainability", "物理链路", "参数 → 公式 → 目标", "explain_trend"),
            NodeSpec("current_system", "explainability", "当前系统验证", "把当前镜头当作样本", "explain_current"),
        ),
    ),
)

# 单栏的宽度下限（像素）。五栏总宽低于这个值 × 5 时，整排栏改为横向滚动，
# 而不是把卡片压到文字放不下。想「无论如何都硬挤成五等分」就把它调很小。
SECTION_MIN_WIDTH = 176
# 是否在同一栏内相邻两张卡片之间画一个向下的小箭头（表达先后顺序）。
# 觉得啰嗦就改成 False，只是不画箭头，不影响任何跳转。
SHOW_SECTION_CONNECTORS = True


# ---------------------------------------------------------------------------
# 控件实现 —— 一般不需要改
# ---------------------------------------------------------------------------


class WorkflowNodeButton(QPushButton):
    """一张卡片的控件本体。

    用 QPushButton 而不是自绘控件，是为了白拿 Qt 原生的键盘焦点、Tab 切换、
    回车/空格触发和无障碍属性——即「点击目标稳定」，不会出现点不中的情况。

    控件内的文字都用 QLabel 画，并且统一设了
    ``WA_TransparentForMouseEvents``，让鼠标事件穿透到按钮本身，
    否则点文字会没有反应。
    """

    def __init__(
        self,
        kind: str,
        title: str,
        subtitle: str,
        icon_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("WorkflowNode")
        # workflowKind 会透出到 QSS，可按卡片类型单独调样式，
        # 例如 light.qss 里的 QPushButton#WorkflowNode[workflowKind="teaching"]。
        self.setProperty("workflowKind", kind)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(70)
        # 宽度随栏拉伸，高度按内容自适应（副标题换行时卡片会变高）。
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        # 无障碍：读屏软件念的是这两个属性，而不是里面的 QLabel。
        self.setAccessibleName(title)
        self.setAccessibleDescription(subtitle)
        self.setToolTip(f"{title}：{subtitle}")
        # 字体族沿用全局设置（main.py 里统一配过），这里只让 QSS 调字号字重，
        # 保证首页和壳层其它地方看起来是一套。

        # 版式：第一行「图标 + 标题」，第二行副标题独占整行。
        # 副标题不跟图标挤在一行，是为了在窄栏里给中文留出尽可能长的行宽，
        # 避免出现「进入仿真镜头表」最后一个字被挤到第二行这种断字。
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(8)
        icon_label = QLabel()
        icon_label.setObjectName("WorkflowNodeIcon")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setFixedSize(36, 36)
        # 让点击穿透到按钮，否则点到图标区域不触发 clicked。
        icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # icon() 来自 shared：按名字取 resources/icons/<name>.svg 并按色号重新着色。
        # 图标名不存在时返回空 QIcon，表现为图标空白，不会抛异常。
        icon_label.setPixmap(icon(icon_name, "#155EEF", 22).pixmap(QSize(22, 22)))
        # 图标顶部对齐：副标题换行把卡片撑高时，图标不会跟着跑到中间。
        heading.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        title_label = QLabel(title)
        title_label.setObjectName("WorkflowNodeTitle")
        title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        heading.addWidget(title_label, 1)
        layout.addLayout(heading)

        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("WorkflowNodeSubtitle")
        # 允许换行，超长副标题会在卡片内折成两行而不是被截断。
        subtitle_label.setWordWrap(True)
        subtitle_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        subtitle_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(subtitle_label)


class WorkflowConnector(QWidget):
    """栏内卡片之间的连接箭头，用 QPainter 自绘。

    之所以不用 QLabel 塞一个「↓」字符：字符会被字体行高裁切，不同字号下
    时有时无。自绘的箭头只有线条，任何字号、任何缩放下都不会被裁。
    """

    def __init__(self, direction: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.direction = direction
        self.setObjectName("WorkflowConnector")
        # 纯装饰，不参与交互，直接让事件穿透。
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if direction == "down":
            self.setFixedSize(28, 26)
        else:
            self.setFixedSize(42, 26)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#155EEF"))
        pen.setWidthF(2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        # 箭头 = 一条主干线 + 两条斜线画出的「尖」。不依赖字体，所以不会被裁。
        if self.direction == "down":
            x = self.width() // 2
            tip_y = self.height() - 4
            shaft_end_y = tip_y - 7
            painter.drawLine(QPoint(x, 3), QPoint(x, shaft_end_y))
            painter.drawLine(QPoint(x - 5, shaft_end_y - 5), QPoint(x, tip_y))
            painter.drawLine(QPoint(x, tip_y), QPoint(x + 5, shaft_end_y - 5))
        else:
            center_y = self.height() // 2
            tip_x = self.width() - 4
            shaft_end_x = tip_x - 7
            painter.drawLine(QPoint(3, center_y), QPoint(shaft_end_x, center_y))
            painter.drawLine(QPoint(shaft_end_x - 5, center_y - 5), QPoint(tip_x, center_y))
            painter.drawLine(QPoint(tip_x, center_y), QPoint(shaft_end_x - 5, center_y + 5))


class WorkflowSection(QFrame):
    """五等分栏里的一栏。

    它自己不碰路由，只把「栏内某张卡片被点了」转成 ``nodeRequested`` 信号
    发出去，由 :class:`WorkflowHome` 原样转发给主窗口。
    """

    # 参数是 (module, kind)，顺序跟主窗口的 open_document 一致，别调换。
    nodeRequested = Signal(str, str)

    def __init__(self, spec: SectionSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spec = spec
        self.setObjectName("WorkflowSection")
        # 两个方向都 Expanding：五栏等高，跟随画布一起长高。
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(SECTION_MIN_WIDTH)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ---- 栏标题头：图标 + 栏名，下面一行灰色说明 ----
        header = QFrame()
        header.setObjectName("WorkflowSectionHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        section_icon = QLabel()
        section_icon.setObjectName("WorkflowSectionIcon")
        section_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        section_icon.setFixedSize(26, 26)
        section_icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # 图标颜色取本栏的 accent；把标题头改成深底时记得在 SectionSpec 里
        # 把 accent 改成浅色，否则深底 + 深蓝图标会看不清。
        section_icon.setPixmap(icon(spec.icon, spec.accent, 18).pixmap(QSize(18, 18)))
        section_title = QLabel(spec.title)
        section_title.setObjectName("WorkflowSectionTitle")
        section_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        title_row.addWidget(section_icon)
        title_row.addWidget(section_title)
        title_row.addStretch(1)
        header_layout.addLayout(title_row)

        # subtitle 允许留空；留空时这一行整个不加，标题头会变矮。
        hint = None
        if spec.subtitle:
            hint = QLabel(spec.subtitle)
            hint.setObjectName("WorkflowSectionHint")
            hint.setWordWrap(True)
            hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            header_layout.addWidget(hint)
        root.addWidget(header)

        # ---- 栏内介绍段落：夹在标题头和卡片之间，可留空 ----
        intro = None
        if spec.intro:
            intro = QLabel(spec.intro)
            intro.setObjectName("WorkflowSectionIntro")
            # 窄栏里必须换行，否则会把栏撑宽、挤掉其它四栏。
            intro.setWordWrap(True)
            intro.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            root.addWidget(intro)

        # 给本栏所有部件挂上 sectionKey，QSS 才能用
        # [sectionKey="simulation"] 这种属性选择器只挑出某一栏单独设样式。
        # 属性必须在控件显示之前设好才生效——这里是构造函数里，没问题；
        # 如果以后要运行时改，改完得补 style().unpolish/polish 才会重画。
        for widget in (self, header, section_icon, section_title, hint, intro):
            if widget is not None:
                widget.setProperty("sectionKey", spec.key)

        # ---- 卡片列：自上而下，按 spec.nodes 的顺序 ----
        cards = QVBoxLayout()
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(6)
        for index, node_spec in enumerate(spec.nodes):
            # 第一张卡片之前不画箭头，只在两两之间插入。
            if index and SHOW_SECTION_CONNECTORS:
                cards.addWidget(WorkflowConnector("down"), 0, Qt.AlignmentFlag.AlignHCenter)
            button = WorkflowNodeButton(
                node_spec.kind, node_spec.title, node_spec.subtitle, node_spec.icon
            )
            # 用默认参数 item=node_spec 把当前这张卡片的 spec 绑进闭包。
            # 不能直接用循环变量 node_spec：lambda 是延迟求值，循环结束后
            # 所有回调都会指向最后一张卡片，点哪张都跳同一个页面。
            button.clicked.connect(
                lambda _checked=False, item=node_spec: self.nodeRequested.emit(item.module, item.kind)
            )
            cards.addWidget(button)
        # 底部留白，让卡片靠上排；栏被拉高时不会把卡片摊开。
        cards.addStretch(1)
        root.addLayout(cards, 1)


class WorkflowHome(QWidget):
    """首页本体：顶部动作条 + 居中大标题 + 横向五等分栏。

    对外只有两个信号和 ``assistant_context()`` 是与壳层的契约，
    其余（版式、控件、样式）都可以自由重画。
    """

    # 契约一：点了某张工作流卡片。参数 (module, kind)，由主窗口接住并打开页面。
    nodeRequested = Signal(str, str)
    # 契约二：首页顶部动作条的动作键（"quick_start" / "help"）。
    # 动作条已按需求移除，当前没有发射方；信号保留是为了不对壳层做改动
    # （main_window.py 仍在 connect 它）。要恢复动作条就在这里 emit。
    homeActionRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("WorkflowHome")
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 14, 22, 22)
        root.setSpacing(10)

        # 顶部原来有一条「快速开始 / 帮助」动作条，已按需求移除。
        # 页面现在直接从主画布开始，画布因此拿到全部高度。
        #
        # homeActionRequested 信号、MainWindow._home_action() 处理函数、
        # modules/home/catalog.py 里的 SECONDARY_ITEMS 都还保留着，但已经
        # 没有地方会触发它们了。要把这条动作条加回来，就在下面重画一行并在
        # 按钮的 clicked 里 emit(homeActionRequested)。

        # ---- 主画布：白底圆角卡片，里面装标题和五栏 ----
        canvas = QFrame()
        canvas.setObjectName("WorkflowCanvas")
        canvas_layout = QVBoxLayout(canvas)
        canvas_layout.setContentsMargins(20, 16, 20, 20)
        canvas_layout.setSpacing(12)

        # 标题行：左右各一条横线把标题夹在中间。两条线都取 stretch=1，
        # 所以始终等长、标题始终居中，跟窗口宽度无关。
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(14)
        title = QLabel("光学研究工作流")
        title.setObjectName("HomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_rule = QFrame()
        left_rule.setObjectName("WorkflowTitleRule")
        left_rule.setFrameShape(QFrame.Shape.HLine)
        left_rule.setFrameShadow(QFrame.Shadow.Plain)
        right_rule = QFrame()
        right_rule.setObjectName("WorkflowTitleRule")
        right_rule.setFrameShape(QFrame.Shape.HLine)
        right_rule.setFrameShadow(QFrame.Shadow.Plain)
        title_row.addWidget(left_rule, 1)
        title_row.addWidget(title)
        title_row.addWidget(right_rule, 1)
        canvas_layout.addLayout(title_row)

        # ---- 五栏区域 ----
        # 用 QScrollArea 包一层，是为了在窗口很窄时整排栏横向滚动，
        # 而不是把栏压到卡片文字放不下。窗口够宽时它完全透明、不显示滚动条。
        scroll = QScrollArea()
        scroll.setObjectName("WorkflowColumns")
        # widgetResizable=True：内容跟随视口变大变小。
        # 下方给 host 设了最小宽度，所以「跟随」有下限，超出下限才出现滚动条。
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        host = QWidget()
        host.setObjectName("WorkflowColumnsHost")
        columns = QHBoxLayout(host)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(12)
        sections = HOME_SECTIONS
        for spec in sections:
            section = WorkflowSection(spec, host)
            # 直接连到自己的信号：栏只管上报 (module, kind)，首页原样往外发，
            # 中间不做任何翻译，保证「页面结构」和「路由规则」彻底解耦。
            section.nodeRequested.connect(self.nodeRequested.emit)
            # stretch=1 对每一栏都一样 —— 这就是「水平平分」的实现方式。
            # 想让某栏更宽，就给它单独的 stretch 值（例如 2）。
            columns.addWidget(section, 1)
        # 最小宽 = 栏数 × 单栏下限 + 栏间距。低于它就横向滚动。
        host.setMinimumWidth(
            len(sections) * SECTION_MIN_WIDTH + max(0, len(sections) - 1) * columns.spacing()
        )
        scroll.setWidget(host)
        canvas_layout.addWidget(scroll, 1)
        root.addWidget(canvas, 1)

    def assistant_context(self) -> dict:
        """契约三：告诉 AI 助手「当前停在首页」。

        主窗口 ``assistant_context()`` 会反射调用本方法，取不到就退回模块名。
        """
        return {"page": "首页", "current_view": "平台总览"}


__all__ = [
    "HOME_SECTIONS",
    "SECTION_MIN_WIDTH",
    "SHOW_SECTION_CONNECTORS",
    "NodeSpec",
    "SectionSpec",
    "WorkflowConnector",
    "WorkflowHome",
    "WorkflowNodeButton",
    "WorkflowSection",
]
