
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ComponentDrawingScheme:
    label: str
    group: str
    role: str
    silhouette: str
    keep: tuple[str, ...]
    omit: tuple[str, ...]


DRAWING_SCHEMES: dict[str, ComponentDrawingScheme] = {
    "laser": ComponentDrawingScheme(
        "激光器", "光源与偏振", "提供808 nm入射光束", "长方体机身＋前端出光口",
        ("机身", "出光端口", "底脚"), ("散热片细节", "铭牌文字", "反光"),
    ),
    "isolator": ComponentDrawingScheme(
        "光隔离器", "光源与偏振", "抑制回返光", "短圆柱光路体＋方向箭头",
        ("圆柱端口", "中央主体", "方向箭头"), ("内部磁体", "刻度", "高光"),
    ),
    "half_wave_plate": ComponentDrawingScheme(
        "半波片", "光源与偏振", "旋转线偏振方向", "圆形旋转架＋透明圆片",
        ("外环", "透明片", "快轴刻线"), ("刻度数字", "锁紧螺纹", "玻璃反光"),
    ),
    "pbs": ComponentDrawingScheme(
        "PBS偏振分束器", "光源与偏振", "按偏振分离或调节功率", "方形安装座＋透明立方体",
        ("立方体", "45°分光面", "正交出射方向"), ("笼式杆件", "螺纹接口", "多层反光"),
    ),
    "beam_sampler": ComponentDrawingScheme(
        "楔形取样片", "光路与取样", "提取少量参考或诊断功率", "倾斜薄片＋立柱",
        ("薄玻璃片", "倾斜方向", "支架"), ("楔角夸张建模", "镀膜光谱", "反射光晕"),
    ),
    "splitter": ComponentDrawingScheme(
        "分束器", "光路与取样", "产生主路与测量支路", "方形安装座＋透明分光块",
        ("透明块", "45°分光线", "安装座"), ("笼式结构", "多旋钮", "材质高光"),
    ),
    "mirror": ComponentDrawingScheme(
        "反射镜", "光路与取样", "折转或解耦光束位置和角度", "开放式镜架＋圆镜面",
        ("圆镜片", "L形/方形镜架", "两个调节旋钮"), ("镜面反光", "细螺纹", "多余固定件"),
    ),
    "aperture": ComponentDrawingScheme(
        "光阑", "光路与取样", "限制通光孔径或辅助对准", "圆盘＋中央孔",
        ("黑色圆盘", "中央孔", "单个调节柄"), ("叶片数量", "刻度环", "金属高光"),
    ),
    "lens": ComponentDrawingScheme(
        "球面/非球面透镜", "整形与耦合", "组成双、三或四透镜耦合组", "圆形镜架＋蓝色镜片",
        ("镜架", "透明镜片", "立柱"), ("真实曲面网格", "压圈螺纹", "玻璃反光"),
    ),
    "beam_expander": ComponentDrawingScheme(
        "可调球面扩束器", "整形与耦合", "改变输入q参数和束径", "短导轨＋一小一大两镜环",
        ("两片镜", "相对间距", "共同底座"), ("镜筒螺纹", "焦距刻字", "渐变材质"),
    ),
    "cylindrical_lens": ComponentDrawingScheme(
        "柱面镜", "整形与耦合", "调节椭圆率和像散", "矩形镜架＋窄蓝色柱面光学区",
        ("矩形外框", "单轴曲率标记", "旋转方向"), ("真实柱面网格", "边缘高光", "夹具细节"),
    ),
    "fiber": ComponentDrawingScheme(
        "五轴光纤架", "整形与耦合", "承载单模光纤并调节XYZ和角度", "块状主体＋中央夹头",
        ("底座", "光纤夹头", "三个代表性旋钮"), ("全部五个旋钮", "微分头刻度", "螺纹"),
    ),
    "power_meter": ComponentDrawingScheme(
        "功率计", "测量仪器", "测量参考或输出功率", "圆柱/短盒探头＋圆形接收面",
        ("探头主体", "接收面", "支架"), ("表头按键", "线缆", "显示数字"),
    ),
    "beam_analyzer": ComponentDrawingScheme(
        "光束分析仪", "测量仪器", "测量光斑尺寸、中心和椭圆率", "相机式机身＋圆形入口",
        ("矩形机身", "前端接口", "小型传感面"), ("散热孔", "接口文字", "屏幕数值"),
    ),
    "imaging_camera": ComponentDrawingScheme(
        "近场/远场相机", "测量仪器", "采集近场或远场光斑", "小型工业相机＋镜头接口",
        ("相机盒", "圆形镜头口", "底座"), ("品牌外形", "线缆", "传感器像素"),
    ),
    "focus_scan_module": ComponentDrawingScheme(
        "焦面扫描模块", "测量仪器", "沿z方向测量多位置束径", "短直线导轨＋移动相机",
        ("导轨", "滑台", "相机接收口"), ("丝杠", "电机细节", "编码器"),
    ),
    "wavefront_sensor": ComponentDrawingScheme(
        "波前传感器", "测量仪器", "测量倾斜、曲率和像散", "宽矩形机身＋方形接收窗",
        ("宽机身", "方形窗口", "支架"), ("微透镜阵列纹理", "接口", "反光"),
    ),
    "photodetector": ComponentDrawingScheme(
        "光电探测器", "测量仪器", "将光信号转换为电信号", "短圆柱探头＋接收面",
        ("圆形接收面", "短主体", "支架"), ("线缆", "放大器内部", "高光"),
    ),
    "oscilloscope": ComponentDrawingScheme(
        "示波器", "测量仪器", "显示探测器电信号", "矩形机箱＋简化屏幕",
        ("机箱", "屏幕", "单个波形符号"), ("旋钮阵列", "端口", "网格细节"),
    ),
}

NODE_LABELS = {kind: scheme.label for kind, scheme in DRAWING_SCHEMES.items()}

SOURCE_POLARIZATION_KINDS = (
    "laser", "isolator", "half_wave_plate", "pbs",
)
ROUTING_SAMPLING_KINDS = (
    "beam_sampler", "splitter", "mirror", "aperture",
)
SHAPING_COUPLING_KINDS = (
    "lens", "beam_expander", "cylindrical_lens", "fiber",
)
MEASUREMENT_KINDS = (
    "power_meter", "beam_analyzer", "imaging_camera", "focus_scan_module",
    "wavefront_sensor", "photodetector",
)
AUXILIARY_INSTRUMENT_KINDS = ("oscilloscope",)

OPTICAL_KINDS = SOURCE_POLARIZATION_KINDS + ROUTING_SAMPLING_KINDS + SHAPING_COUPLING_KINDS
INSTRUMENT_KINDS = MEASUREMENT_KINDS + AUXILIARY_INSTRUMENT_KINDS
TERMINAL_KINDS = (
    "power_meter", "beam_analyzer", "imaging_camera", "focus_scan_module",
    "wavefront_sensor", "oscilloscope",
)


def schemes_as_rows() -> list[dict[str, str]]:

    rows: list[dict[str, str]] = []
    for kind, scheme in DRAWING_SCHEMES.items():
        rows.append({
            "kind": kind,
            "名称": scheme.label,
            "分组": scheme.group,
            "实验作用": scheme.role,
            "简化轮廓": scheme.silhouette,
            "保留特征": "；".join(scheme.keep),
            "省略细节": "；".join(scheme.omit),
        })
    return rows
