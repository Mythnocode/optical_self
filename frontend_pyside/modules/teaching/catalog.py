"""Navigation actions owned by the teaching primary entry."""

SECONDARY_ITEMS = (
    ("scheme", "方案", "切换单透镜、双透镜、三透镜或四透镜教学方案"),
    ("equipment", "器材库", "打开内置工程器材库"),
    ("display", "视角", "控制光线、标签和视图"),
    ("analysis", "成像与耦合", "正式计算光斑、模式重叠和总耦合效率"),
    ("calculate", "计算", "运行教学计算"),
    ("sync_to_simulation", "同步到仿真", "把教学场景写入当前工程"),
    ("sync_from_simulation", "从仿真更新", "读取当前工程几何和波长"),
)

__all__ = ["SECONDARY_ITEMS"]
