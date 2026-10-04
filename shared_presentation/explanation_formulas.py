"""Original optical formula metadata shared by Qt and Web presentation."""
from __future__ import annotations
import re

FORMULA_CATALOG: dict[str, dict[str, str]] = {
    "总耦合效率": {
        "复场重叠": r"\eta_{\mathrm{overlap}}=\frac{|\int\!\!\int E_sE_f^*\,dA|^2}{\int\!\!\int|E_s|^2dA\;\int\!\!\int|E_f|^2dA}",
        "系统传输": r"\eta_{\mathrm{total}}=\eta_{\mathrm{transmission}}\eta_{\mathrm{overlap}}\eta_{\mathrm{facet}}\eta_{\mathrm{propagation}}",
        "端面效率": r"\eta_{\mathrm{facet}}=1-R_{\mathrm{facet}}",
    },
    "对准误差": {
        "横向偏移": r"u_r=\frac{\sqrt{\Delta x^2+\Delta y^2}}{w_f},\quad \eta/\eta_0=\exp(-u_r^2)",
        "角度偏移": r"u_\theta=\frac{\pi w_f\sqrt{\theta_x^2+\theta_y^2}}{\lambda},\quad \eta/\eta_0=\exp(-u_\theta^2)",
        "轴向离焦": r"u_z=\frac{\Delta z}{z_R},\quad z_R=\frac{\pi w_f^2}{\lambda}",
    },
    "模式失配": {
        "尺寸失配": r"\rho=\frac{w_b}{w_f},\quad \eta_{\mathrm{size}}=\left(\frac{2\rho}{1+\rho^2}\right)^2",
        "曲率失配": r"u_R=\frac{k w_f^2}{4}\left(\frac{1}{R_b}-\frac{1}{R_f}\right),\quad \eta/\eta_0=\frac{1}{1+u_R^2}",
    },
    "波前质量": {
        "OPD": r"\mathrm{OPD}(x,y)=W(x,y)-\overline{W}",
        "Zernike": r"W(\rho,\phi)=\sum_j a_jZ_j(\rho,\phi)",
        "Strehl": r"S\approx\exp[-(2\pi\sigma_W/\lambda)^2]",
    },
    "成像质量": {
        "PSF": r"\mathrm{PSF}=|\mathcal{F}\{P\exp(i2\pi W/\lambda)\}|^2",
        "MTF": r"\mathrm{MTF}=|\mathcal{F}\{\mathrm{PSF}\}|",
        "Airy 半径": r"r_{\mathrm{Airy}}=1.22\lambda f/ D",
    },
    "结构参数": {
        "曲率半径": r"\Phi_s\approx\frac{n_2-n_1}{R}",
        "厚度与间隔": r"M_t=\begin{pmatrix}1&t/n\\0&1\end{pmatrix}",
        "圆锥系数": r"z(r)=\frac{cr^2}{1+\sqrt{1-(1+k)c^2r^2}}",
    },
}


def feature_display_name(feature_name: str) -> str:

    from shared_presentation.feature_labels import display_feature_name

    return display_feature_name(feature_name)


def formula_binding_for_feature(feature_name: str) -> tuple[str, str, str, str]:

    text = str(feature_name).lower().replace(" ", "")
    surface = re.fullmatch(r"(?:surfaces?|surface)(?:\[(\d+)\]|\.(\d+))\.(.+)", text)
    if surface:
        field = surface.group(3)
        surface_bindings = {
            "radius_mm": ("结构参数", "曲率半径", "间接", "该表面曲率半径改变折射光焦度"),
            "radius": ("结构参数", "曲率半径", "间接", "该表面曲率半径改变折射光焦度"),
            "curvature_radius_mm": ("结构参数", "曲率半径", "间接", "该表面曲率半径改变折射光焦度"),
            "distance_to_next_mm": ("结构参数", "厚度与间隔", "间接", "该表面后的介质厚度改变传播矩阵和光程"),
            "thickness_mm": ("结构参数", "厚度与间隔", "间接", "该表面后的介质厚度改变传播矩阵和光程"),
            "thickness": ("结构参数", "厚度与间隔", "间接", "该表面后的介质厚度改变传播矩阵和光程"),
            "air_gap_mm": ("结构参数", "厚度与间隔", "间接", "该空气间隔改变传播矩阵和光程"),
            "conic": ("结构参数", "圆锥系数", "间接", "该表面圆锥系数改变非球面矢高和波前"),
            "semi_aperture_mm": ("结构参数", "半口径", "间接", "该表面半口径决定瞳面截断范围"),
            "semi_diameter_mm": ("结构参数", "半口径", "间接", "该表面半口径决定瞳面截断范围"),
            "material": ("结构参数", "材料色散", "间接", "该表面后的材料折射率随波长变化"),
            "material_after": ("结构参数", "材料色散", "间接", "该表面后的材料折射率随波长变化"),
            "glass": ("结构参数", "材料色散", "间接", "该表面后的材料折射率随波长变化"),
        }
        if field in surface_bindings:
            return surface_bindings[field]
    if any(token in text for token in ("lateral_mismatch", "offset_x", "offset_y", "decenter", "横向", "x偏移", "y偏移")):
        return "对准误差", "横向偏移", "直接", "参数可直接构成横向失配无量纲量"
    if any(token in text for token in ("angular_mismatch", "tilt", "angle", "倾角", "角度")):
        return "对准误差", "角度偏移", "直接", "参数可直接构成角度失配无量纲量"
    if any(token in text for token in ("axial_mismatch", "axial", "defocus", "receiver.distance", "接收面", "离焦")):
        return "对准误差", "轴向离焦", "直接", "参数可直接构成轴向离焦无量纲量"
    if any(token in text for token in ("size_ratio", "waist", "mode_radius", "mode_field", "mfd", "束腰", "模场")):
        return "模式失配", "尺寸失配", "直接", "参数直接决定光斑与模场尺寸比"
    if any(token in text for token in ("curvature_mismatch", "wavefront_curvature", "mode_curvature_radius")):
        return "模式失配", "曲率失配", "直接", "参数直接描述二次相位曲率失配"
    if any(token in text for token in ("conic", "圆锥系数")):
        return "结构参数", "圆锥系数", "间接", "圆锥系数改变非球面面形和高阶像差"
    if any(token in text for token in ("thickness", "distance_to_next", "厚度", "air_gap", "spacing", "间隔")):
        return "结构参数", "厚度与间隔", "间接", "厚度和间隔改变群组传播距离与焦面位置"
    if any(token in text for token in (".radius", "radius_mm", "curvature", "曲率半径")):
        return "结构参数", "曲率半径", "间接", "曲率半径改变表面光焦度并影响后续焦面复场"
    if any(token in text for token in ("material", "glass")):
        return "结构参数", "材料色散", "间接", "材料色散和折射率通过表面光焦度与传播相位影响耦合"
    if "wavelength" in text or "波长" in text:
        return "传播相位", "波数", "直接", "波长决定波数、衍射尺度和材料色散的工作点"
    if any(token in text for token in ("semi_aperture", "semi_diameter", "aperture", "半口径")):
        return "结构参数", "半口径", "间接", "半口径定义瞳面截断范围"
    if any(token in text for token in ("strehl", "wavefront", "opd", "zernike")):
        return "波前质量", "Strehl", "直接", "参数属于波前质量指标"
    if any(token in text for token in ("psf", "spot")):
        return "成像质量", "PSF", "直接", "参数属于焦面成像质量指标"
    if "mtf" in text:
        return "成像质量", "MTF", "直接", "参数属于调制传递指标"
    return "", "", "未映射", "当前特征尚无可靠解析公式映射"


def formula_location_for_feature(feature_name: str) -> tuple[str, str]:
    category, item, _level, _note = formula_binding_for_feature(feature_name)
    return category, item


def physical_mechanism_for_feature(feature_name: str) -> str:
    category, item, level, _note = formula_binding_for_feature(feature_name)
    direct = {
        ("对准误差", "横向偏移"): "入射场质心与光纤模式中心分离，使横截面复场投影减小。",
        ("对准误差", "角度偏移"): "倾斜引入线性相位，积分时不同位置的复振幅发生抵消。",
        ("对准误差", "轴向离焦"): "接收面偏离最佳焦面，同时改变光斑尺寸和波前曲率。",
        ("模式失配", "尺寸失配"): "入射光斑半径与光纤模场半径不一致，降低模式重叠。",
        ("模式失配", "曲率失配"): "强度轮廓相近时，二次相位曲率不一致仍会降低复场重叠。",
        ("波前质量", "Strehl"): "波前均方误差增大使焦面能量从主峰扩散。",
        ("成像质量", "PSF"): "焦面点扩散函数变化反映孔径和像差对聚焦场的共同影响。",
        ("成像质量", "MTF"): "空间频率响应下降表示成像对细节调制的传递能力减弱。",
        ("结构参数", "曲率半径"): "曲率半径改变折射面光焦度，进而改变焦点位置、光斑尺寸和焦面波前。",
        ("结构参数", "厚度与间隔"): "厚度与空气间隔改变透镜组内传播距离，主要影响焦面位置和累计像差。",
        ("结构参数", "圆锥系数"): "圆锥系数改变非球面偏离基准球面的程度，主要用于校正高阶球差并改善焦面复场。",
        ("结构参数", "材料色散"): "材料折射率随波长变化，改变表面光焦度和透镜内传播相位。",
        ("结构参数", "半口径"): "半口径限定表面有效瞳区，影响截光和焦面振幅分布。",
        ("传播相位", "波数"): "波长决定真空波数与介质波数，并改变衍射和传播相位。",
    }
    if (category, item) in direct:
        return direct[(category, item)]
    if level == "间接":
        return "该镜头结构参数会改变光线传播、焦面振幅和相位，最终通过完整复场重叠影响耦合；不能归结为单一闭式损失项。"
    return "当前特征尚未建立可靠的物理公式映射，需要通过参数扫描和正式仿真定位机制。"


def suggested_action_for_feature(feature_name: str) -> str:
    category, item, level, _note = formula_binding_for_feature(feature_name)
    actions = {
        ("对准误差", "横向偏移"): "打开五轴对准或横向偏移扫描",
        ("对准误差", "角度偏移"): "检查倾角并运行角度参数扫描",
        ("对准误差", "轴向离焦"): "运行焦面扫描并重新寻找最佳接收面",
        ("模式失配", "尺寸失配"): "比较入射光斑半径与光纤模场半径",
        ("模式失配", "曲率失配"): "检查焦面波前曲率和离焦状态",
        ("波前质量", "Strehl"): "检查像差、波前RMS和光瞳采样",
        ("成像质量", "PSF"): "打开PSF及焦面光场诊断",
        ("成像质量", "MTF"): "打开MTF曲线并检查空间频率范围",
        ("结构参数", "曲率半径"): "对该曲率半径做正式单变量扫描，并检查接收面光斑和模式重叠",
        ("结构参数", "厚度与间隔"): "对该厚度或间隔做正式焦面扫描，再比较模式重叠",
        ("结构参数", "圆锥系数"): "对该圆锥系数做小范围正式扫描，并检查波前 RMS 和耦合效率",
        ("结构参数", "材料色散"): "检查材料折射率色散，并对工作波长做正式仿真",
        ("结构参数", "半口径"): "检查有效瞳径和截光，并运行正式仿真",
        ("传播相位", "波数"): "改变工作波长并比较衍射、焦面复场和耦合效率",
    }
    if (category, item) in actions:
        return actions[(category, item)]
    if level == "间接":
        return "进入参数研究，对该结构参数做正式扫描并查看焦面复场变化"
    return "补充特征物理映射后再作工程判断"


def formula_latex(category: str, item: str) -> str:
    return FORMULA_CATALOG.get(str(category), {}).get(str(item), "")


def formula_chain_for_feature(feature_name: str) -> tuple[tuple[str, str], ...]:
    """Return the feature-specific physics stages with indexed symbols."""
    from machine_learning.explainability.linkage_metadata import formula_linkage_for_feature

    linkage = formula_linkage_for_feature(str(feature_name))
    steps = tuple(
        (str(stage), str(latex))
        for stage, latex in getattr(linkage, "formula_steps", ())
        if str(stage).strip() and str(latex).strip()
    )
    if steps:
        return steps
    # A category-level equation cannot stand in for a feature-specific route.
    return ()

