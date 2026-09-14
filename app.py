"""Optical Two 一键启动入口：FastAPI 后端 + 重构后的 PySide6 工作台。

用法（项目根目录）::

    py -3.12 app.py
    py -3.12 app.py --frontend-only

行为：
- 检测 127.0.0.1:8000 的 /api/v1/health；后端已在运行则直接复用，
  否则以子进程启动 run_backend.py 并等待就绪（超时后前端以本地近似模式兜底）；
- 前端在主线程运行（Qt 要求），关闭主窗口后优雅停掉后端（CTRL_BREAK → 强制兜底）；
- 后端单独崩溃只打印提示，前端自动进入"后端未连接"降级模式。
- 默认入口使用新的主窗口：一级栏 + 二级栏 + 对象栏 + 文档页签；教学为独立大画布；
- ``--frontend-only`` 用于不启动子进程后端的 UI 调试/布局检查。

注意：后端任务管理器使用 multiprocessing spawn，其子进程会以 __mp_main__
重导入父入口模块——因此这里不在模块层导入 backend/uvicorn，全部留在函数内，
与 run_backend.py 的约定保持一致。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
HEALTH_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}/api/v1/health"
HEALTH_TIMEOUT_S = 25.0  # 后端冷启动（含任务恢复）的最长等待


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="启动 Optical Two 的 PySide6 光学研究工作台。"
    )
    parser.add_argument(
        "--frontend-only",
        action="store_true",
        help="只启动新的 PySide 画布前端，不自动启动或停止 FastAPI 后端。",
    )
    return parser.parse_args(argv)


def _backend_healthy(timeout: float = 1.5) -> bool:
    try:
        with urlopen(HEALTH_URL, timeout=timeout) as resp:
            return resp.status == 200
    except (URLError, OSError):
        return False


def _start_backend() -> subprocess.Popen:
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # 允许 CTRL_BREAK 优雅停机
    return subprocess.Popen(
        [sys.executable, str(ROOT / "run_backend.py")],
        cwd=str(ROOT),
        creationflags=creationflags,
    )


def _wait_backend_ready() -> bool:
    print(f"[app] 等待后端就绪 {HEALTH_URL} ...", flush=True)
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        if _backend_healthy():
            print("[app] 后端已就绪", flush=True)
            return True
        time.sleep(0.4)
    print("[app] 后端超时未就绪；前端将以本地近似模式启动", flush=True)
    return False


def _watch_backend(proc: subprocess.Popen, stopping: threading.Event) -> None:
    """后端子进程意外退出时在控制台提示（前端自身有未连接降级）。"""
    code = proc.wait()
    if code != 0 and not stopping.is_set():
        print(f"[app] 后端进程退出（code={code}）；前端进入本地近似模式", flush=True)


def _stop_backend(proc: subprocess.Popen | None, stopping: threading.Event) -> None:
    if proc is None or proc.poll() is not None:
        return
    print("[app] 正在停止后端 ...", flush=True)
    stopping.set()
    try:
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)  # uvicorn 优雅关停
        else:
            proc.terminate()
        proc.wait(timeout=8)
        print("[app] 后端已退出", flush=True)
    except Exception:
        proc.kill()
        print("[app] 后端已强制结束", flush=True)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    backend: subprocess.Popen | None = None
    stopping = threading.Event()
    if args.frontend_only:
        print("[app] 仅启动 PySide6 前端；不管理 FastAPI 后端", flush=True)
    elif _backend_healthy():
        print("[app] 检测到后端已在运行，直接复用", flush=True)
    else:
        print("[app] 启动后端 run_backend.py ...", flush=True)
        backend = _start_backend()
        threading.Thread(target=_watch_backend, args=(backend, stopping), daemon=True).start()
        _wait_backend_ready()

    code = 0
    try:
        # 前端（Qt 必须占主线程）；main.py 内含 shiboken×six 导入加固
        from frontend_pyside.app.startup import configure_process_environment

        configure_process_environment()
        from frontend_pyside.app.main import main as frontend_main

        code = frontend_main()
    finally:
        _stop_backend(backend, stopping)
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
