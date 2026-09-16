"""Navigation actions owned by the teaching primary entry."""

SECONDARY_ITEMS = (
    ("scheme", "方案", "切换单透镜、双透镜、三透镜或四透镜教学方案"),
    ("equipment", "器材库", "打开内置工程器材库"),
    ("inspector", "属性", "打开当前对象悬浮窗"),
    ("display", "显示", "控制光线、标签和视图"),
    ("measure", "测量", "测量距离、角度和光斑"),
    ("imaging", "成像", "正式计算光斑、像面位置和偏心"),
    ("coupling", "耦合", "正式计算模式重叠和总耦合效率"),
    ("calculate", "计算", "运行教学计算"),
    ("result", "结果", "打开悬浮结果窗"),
    ("sync_to_simulation", "同步到仿真", "把教学场景写入当前工程"),
    ("sync_from_simulation", "从仿真更新", "读取当前工程几何和波长"),
)

__all__ = ["SECONDARY_ITEMS"]
