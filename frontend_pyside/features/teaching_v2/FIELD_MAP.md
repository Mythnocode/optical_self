# 教学中心器材与字段

语义冻结：Pose = 光心 / 光口；`z_mm` = 离台面；默认梁高 25 mm 是台属性不是 561 的 79.4；镜子 `yaw=0` = runtime 已 45° 折转，网格不预旋；`diameter_mm` = 外径，引擎半径 = D/2；教学 `ccd` 编译为 `imaging_camera`。光学参数不决定壳体毫米（见外壳表）。

台上可添加 **6 种已接**（含隔离器）；主线+拓展再加 **光阑、柱面**（runtime 已认识，教学 kind 未露出）。不要上图鉴 19 类。

## 每件都有（身份 / 姿态）

| 字段 | 检查器 | 缺省 | 去向 |
| --- | --- | --- | --- |
| `component_id` | 否 | `laser-001` 等 | JSON / 引擎 node id |
| `kind` | 否 | 见下表 | 编译、网格 `asset_key` |
| `label` | 标题 | 激光器 / L1 透镜 / … | 显示 |
| `enabled` | 是 | true | 禁用则不进追迹 |
| `asset_key` | 否 | = `kind` | `assets/<key>.glb` |
| `pose.x_mm` | 沿导轨 | 按场景 | 光轴位置 |
| `pose.y_mm` | 横向 | 0 | 引擎接收偏移；光纤 y 进耦合 |
| `pose.z_mm` | 离台高度 | 25 | 光心高度；支柱长 = z |
| `pose.yaw/pitch/roll` | 度 | 0 | 内部 rad；正式追迹 `tilt_*`（opt-in SO3） |

JSON 姿态存 rad。渲染坐标只在视图桥，不进 JSON。

## 已接器材与光学参数

检查器只显示 `KIND_PARAM_SPECS`。括号为编译/别名，界面隐藏。

### 激光器 `laser`

壳体 Ø11×40 mm（CPS635），出光面 = Pose。一台场景只允许一枚启用激光。

| 字段 | 缺省 | 去向 |
| --- | --- | --- |
| `wavelength_nm` | 780 | 引擎 |
| `power_mw` | 100 | 引擎 |
| `beam_radius_mm` | 0.72 | 引擎束腰；**不**缩放壳体 |

课包可改 650/850，不必新 kind。椭圆束腰 \(w_x,w_y\)、M²：**未接**（拓展准直/M² 再用，不要做成第二台激光器）。

### 透镜 `lens`

壳体随 `diameter_mm` × `center_thickness_mm`。可多枚（L1/L2、4f）。

| 字段 | 缺省 | 去向 |
| --- | --- | --- |
| `focal_length_mm`（`focal_mm`） | 添加=25；标准场景 L1=50、L2=12 | 无 R1/R2 时双凸等效 |
| `diameter_mm` | 12.7 | 引擎 D/2；视图口径 |
| `material` | N-BK7 | 引擎 |
| `radius1_mm` / `radius2_mm` | 0=未设 | 皆非 0 才用真实面 |
| `center_thickness_mm` | 2 | 等效与显式共用 |
| `clear_aperture_mm` | 未设 | 孔径半径，优先于 `aperture_radius_mm` > D/2 |
| `design_refractive_index` | 1.5168 | 仅编译，检查器无 |

非球面圆锥/A4：**未接**（拓展准直用，仍是 `lens` 不是新 kind）。

### 光纤 `fiber`（界面「光纤架」）

壳体 Ø11×18 mm（F220），入光面 = Pose。五轴 = 本件 Pose，不是独立架。再添一枚即纤–纤。无光纤则拒绝耦合/场/波前。

| 字段 | 缺省 | 去向 |
| --- | --- | --- |
| `mfd_um` | 5.6 | 耦合基模 |
| `na` | 0.12 | 接收 NA |

### CCD `ccd`

壳体 30×30×21.8 mm（Zelux 前壳），靶面 = Pose。编译 kind = `imaging_camera`。光斑需要 CCD 或光纤。

| 字段 | 缺省 | 去向 |
| --- | --- | --- |
| `sensor_width_mm` | 4.968 | 编译直径取 max(宽,高) |
| `sensor_height_mm` | 3.726 | 同上 |

旧字段 `active_area_mm` 读入后拆成宽×高，不写回。

### 反射镜 `mirror`

壳体 `diameter_mm` × 6 mm（BB05），镀膜面 = Pose。

| 字段 | 缺省 | 去向 |
| --- | --- | --- |
| `diameter_mm` | 12.7 | 引擎 / 视图 |

### 隔离器 `isolator`

壳体 Ø25 × 36 mm（IO-3-780-HP 量级），光心 = Pose。放在激光后、第一片透镜前。半导体激光耦合回光会跳模，台上应有这一件。

| 字段 | 缺省 | 去向 |
| --- | --- | --- |
| `isolation_db` | 38 | 检查器；这一版不追回光 |
| `insertion_loss_db` | 0.4 | 示意功率 × 10^(−IL/10)；正式面只挡通光孔 |
| `clear_aperture_mm` | 1.8（半径，对应 Ø3.6） | 引擎孔径 |
| `diameter_mm` | 25 | 外壳，不进光学 |

默认短耦合线（L1 在 24 mm）放不下 36 mm 壳体，添加后请把透镜后移。

### 支柱（不是添加栏器材）

`post_stem.glb`，Ø12.7 × `pose.z_mm`（TR75/M）。每件自动带，无独立参数。

## 拓展器材（已可添加）

光阑、柱面、波片、PBS、分束、取样、扩束、光栅、功率计、WFS、示波器已进添加栏。波片/扩束/光栅这一版只占位（不追偏振/倍率/衍射级）。五轴不单独添加，用 `fiber_stage.glb` 跟光纤同一 Pose。

## 视图外壳与网格（不进光学）

台上尺寸以 `HOUSING_SPECS` 为准。交给建模的完整表在 `assets/MODELING_BRIEF.md`（20 个 glb）。文件轴：**+X 光轴，+Z 上**。镜子/分束/取样/光栅不得预旋 45°。五轴只做 `fiber_stage.glb` 换皮，高度不是 561 的 79.4。

| kind | 台上外壳 | 锚点 | 网格 |
| --- | --- | --- | --- |
| breadboard | 450×300×12.7 | 上表面中心 | `breadboard.glb` |
| post_stem | Ø12.7×1 模板 | 顶端=光心 | `post_stem.glb` |
| laser | Ø11×40 | 出光面 | `laser.glb` |
| isolator | Ø25×36 | 光心 | `isolator.glb` |
| waveplate | Ø12.7×6 | 光心 | `waveplate.glb` |
| lens | 外径×厚度 | 光心 | `lens.glb` |
| cylindrical_lens | 同透镜 | 光心 | `cylindrical_lens.glb` |
| beam_expander | Ø25×45 | 光心 | `beam_expander.glb` |
| aperture | 孔径×0.5 | 孔面中心 | `aperture.glb` |
| pbs | 12.7 立方 | 中心 | `pbs.glb` |
| splitter | Ø12.7×3 | 镀膜面 | `splitter.glb` |
| beam_sampler | Ø12.7×1 | 镀膜面 | `beam_sampler.glb` |
| grating | 12.7×12.7×6 | 刻线面 | `grating.glb` |
| mirror | Ø12.7×6 | 镀膜面 | `mirror.glb` |
| fiber | Ø11×18 | 入光面 | `fiber.glb` |
| fiber_stage | 36×44×40 座 | 光口，座在下方 | `fiber_stage.glb`（不单独添加） |
| ccd | 30×30×21.8 | 靶面 | `ccd.glb` |
| power_meter | Ø30×22 | 靶面 | `power_meter.glb` |
| wavefront_sensor | 40×40×32 | 靶面 | `wavefront_sensor.glb` |
| oscilloscope | 120×80×50 | 底面坐台 | `oscilloscope.glb` |

## 不做进教学台

不要上 EDFA、HeNe 腔镜、DOE（用光栅）、大蜂窝台桌腿。2D `pixels_per_mm` 不做。不改 `teaching_runtime` 激光原点。五轴不要做成 79.4 mm 的 561 整架。
