# OpticalMLPlatform 打包说明

将「激光耦合仿真系统及智能优化平台」打包为可安装的 Windows exe（Inno Setup 安装版）。

## 产物

- `dist\OpticalMLPlatform\`：PyInstaller onedir 应用目录（应用本体，约 2GB）
- `dist\installer\OpticalMLPlatform_Setup_v1.5.6.exe`：最终安装程序（LZMA 压缩）

## 架构

UI（PySide6）与后端（FastAPI on 127.0.0.1:8000）合并为一个入口 `OpticalMLPlatform.exe`（入口脚本 `launch.py`）：

- 无参数（双击）：编排模式——先探测已运行的后端（复用），否则以后端子进程启动
  （`--backend`，CREATE_NO_WINDOW，stdout/stderr 重定向到 `user_data\logs\backend_console.log`），
  轮询 `/api/v1/health` 就绪后**进程内**运行前端主循环；GUI 退出后 taskkill 清理本次启动的后端进程树。
- `--backend`：仅启动后端（FastAPI/uvicorn + multiprocessing spawn 工作进程池）
- `--frontend`：仅启动前端（无后端连通性检查，直接用）
- `--backend-only`：编排模式下只启动后端并保持运行
- `--stop-backend-on-exit`：开发模式关闭前端时同时关闭后端（打包模式默认如此）

frozen 模式下（`sys.frozen`）：

- `os.chdir(exe 所在目录)`，`USER_DATA_DIR`/`OPTICAL_USAGE_DIR`/`OPTICAL_PERF_LOG_PATH`
  指向 `{exe dir}\user_data`（安装版为 `%LOCALAPPDATA%\Programs\OpticalMLPlatform`，目录可写）
- 资源定位：所有 `Path(__file__).resolve().parents[N]` 在 onedir `_internal` 下由 spec 的
  `datas` 镜像仓库布局自动成立，**未修改任何现有源码**

### 数据目录（运行时可写）

- `user_data\`（数据集/模型/任务/日志/用量/导出），位于安装目录下
- 卸载时保留（Inno 默认只删除安装过的文件，运行期创建的文件不受影响）

### 关键技术点（spec）

- 入口 `launch.py`：首行 `multiprocessing.freeze_support()`，顶层无副作用（spawn 工作进程需
  以 `--multiprocessing-fork` 重进 exe 且不应再执行编排逻辑）
- 9 个项目包使用 `collect_submodules` 收编（封面 page_registry 动态导入、cloudpickle worker 函数）
- **`PySide6.QtQuick3D` 必须是 hiddenimport**：Python 侧从不 import 它，仅 `.qml` 里
  `import QtQuick3D`（教学 3D 页面）
- datas 镜像：`resources/`（demo_assets + help 知识库）、`frontend_pyside` 包内资源
  （icons/qss/qml/images/presets）、`optical_core/materials/data`（玻璃材料表）、
  `data_templates`、`assets_3d`
- 禁用 UPX（避免 av 误报）

## 构建前置

1. conda 环境 `optical`（Python 3.12），已含 PyInstaller 6.21.0 + hooks-contrib 2026.6、
   torch(cpu)/PySide6/scipy/sklearn/xgboost/shap 等（与 requirements.txt 版本有差异，
   以环境实际版本为准，保持 dev 一致）
2. Inno Setup 6（如 `%LOCALAPPDATA%\Programs\Inno Setup 6`），自带上英文 + 中文简体语言包

## 重建步骤

```bat
packaging\build_installer.bat
```

或手动：

```bat
D:\anacondanew\envs\optical\python.exe -m PyInstaller --noconfirm --clean packaging\optical_ml.spec
"C:\Users\qingxue\AppData\Local\Programs\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

图标：`packaging\generate_icon.py`（QSvgRenderer 渲染 `frontend_pyside\resources\icons\logo.svg`
→ Pillow 多尺寸 ICO → `packaging\app.ico`）。

## 验证（打包前/后）

打包前（源码态基线）：

```bat
D:\anacondanew\envs\optical\python.exe -m pytest tests\ -q
D:\anacondanew\envs\optical\python.exe tools\feature_conservation_audit.py
```

打包后（frozen 态）：

```bat
dist\OpticalMLPlatform\OpticalMLPlatform.exe --backend
curl http://127.0.0.1:8000/api/v1/health
```

提交一个小仿真任务验证 spawn worker / cloudpickle / ws 事件；完整启动验证 GUI、qss、
教学 3D QML（QtQuick3D）、助手知识库（help.db）；关闭 GUI 后 `tasklist` 确认无残留进程。

## 已知风险

- 体积：安装后约 2GB；setup.exe 约 1GB+（torch 压缩率低）
- 无代码签名：SmartScreen/杀软可能告警，需用户放行
- 本地 LLM（llama.cpp + GGUF）仓库本就缺模型文件：打包后同 dev 一样优雅降级
  （助手走 help.db 知识库检索）
