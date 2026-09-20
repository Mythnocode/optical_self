"""Workbench-wide parameter catalog shared by the ordinary Qt workbench."""

from __future__ import annotations


MATERIAL_CHOICES = ("AIR", "N-BK7", "N-SF11", "F_SILICA", "MIRROR", "自定义")
APERTURE_TYPE_CHOICES = ("圆形通光孔径", "矩形孔径", "椭圆孔径", "用户孔径")
COATING_CHOICES = ("无", "增透膜", "高反膜", "金属膜", "自定义镀膜")
STOP_SHAPE_CHOICES = ("圆形", "矩形", "椭圆", "用户孔径")
STOP_ROLE_CHOICES = ("孔径光阑", "视场光阑", "遮拦", "普通孔径")
MIRROR_MODE_CHOICES = ("理想反射", "金属膜", "介质高反膜", "用户模型")
GRATING_MODE_CHOICES = ("反射式", "透射式")
GRATING_EFFICIENCY_CHOICES = ("理想", "标量近似", "RCWA 数据表", "用户模型")
DETECTOR_SAMPLING_CHOICES = ("中心采样", "面积积分", "用户响应")

SOURCE_TYPE_CHOICES = ("高斯模式", "均匀光瞳", "点光源")
POWER_UNIT_CHOICES = ("mW", "W", "μW")
RECEIVER_TYPE_CHOICES = ("单模光纤", "多模光纤", "用户模式")
RECEIVER_MODE_CHOICES = ("高斯近似", "LP01", "HE11", "导入复场")

CALC_PRECISION_CHOICES = ("129×129", "257×257", "513×513", "1025×1025")
DATASET_PRECISION_CHOICES = ("129×129", "257×257", "513×513")
OUTPUT_GRID_CHOICES = ("65 × 65", "129 × 129", "257 × 257", "513 × 513", "1025 × 1025")
LAYOUT_PUPIL_CHOICES = ("7 × 7", "9 × 9", "13 × 13", "17 × 17")
ANALYSIS_PUPIL_CHOICES = ("17 × 17", "33 × 33", "49 × 49", "65 × 65")
PROPAGATION_CHOICES = ("普通角谱", "带限角谱", "缩放角谱", "缩放 Fresnel", "ISSC", "Fresnel")

SCAN_MODE_CHOICES = ("一维扫描", "二维扫描", "多参数采样")
SCAN_RESPONSE_CHOICES = ("耦合效率", "RMS 光斑", "Strehl", "边缘功率")
SCAN_SCALE_CHOICES = ("线性采样", "对数采样", "自适应加密")
OPTIMIZATION_OBJECTIVE_CHOICES = ("最大化耦合效率", "最小化 RMS 光斑", "多目标加权")
OPTIMIZATION_ALGORITHM_CHOICES = ("智能全局搜索", "贝叶斯粗搜", "差分进化粗搜")
VARIABLE_FILTER_CHOICES = ("全部参数", "光源", "曲率半径", "厚度", "半口径", "光纤与装调", "其他参数")
VARIABLE_SCALE_CHOICES = ("线性", "对数", "相对百分比")
TOLERANCE_CANDIDATE_CHOICES = ("当前最优候选", "当前系统")
TOLERANCE_TEMPLATE_CHOICES = ("优化参数 + 常用装调", "常用装调", "自定义")
TOLERANCE_SAMPLING_CHOICES = ("LHS", "Sobol", "随机")
TOLERANCE_DISTRIBUTION_CHOICES = ("正态", "均匀", "三角")

DATASET_SAMPLING_CHOICES = ("Latin Hypercube", "Sobol低差异采样")
DATASET_TARGET_CHOICES = ("耦合损耗(dB)", "耦合效率", "RMS 光斑", "Strehl")
TABULAR_MODEL_CHOICES = ("随机森林", "XGBoost物理残差")
SEQUENCE_MODEL_CHOICES = ("BiLSTM",)
MODEL_TYPE_CHOICES = TABULAR_MODEL_CHOICES + SEQUENCE_MODEL_CHOICES
TABULAR_DATASET_CHOICES = (
    "内置演示·780 nm 四透镜八变量",
    "内置演示·物理残差样本",
)
SEQUENCE_DATASET_CHOICES = ("内置演示·结构序列（BiLSTM）",)
MAX_FEATURE_CHOICES = ("sqrt", "log2", "1.0")

VALIDATION_METRIC_CHOICES = ("E003 耦合效率", "E004 横向 3 dB 全宽", "E006 角度 3 dB 全宽", "自定义指标")
VALIDATION_REFERENCE_CHOICES = ("实验数据", "文献理论")


__all__ = [name for name in globals() if name.isupper()]
