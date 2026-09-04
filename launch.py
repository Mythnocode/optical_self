from __future__ import annotations

import multiprocessing

multiprocessing.freeze_support()

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else ROOT

HEALTH_URL = "http://127.0.0.1:8000/api/v1/health"
BACKEND_STARTUP_TIMEOUT_S = 45.0


def _healthy() -> bool:
    try:
        import httpx

        response = httpx.get(HEALTH_URL, timeout=0.8)
        body = response.json() if response.status_code == 200 else {}
        return bool(
            response.status_code == 200
            and body.get("code") == "OK"
            and (body.get("data") or {}).get("status") == "healthy"
        )
    except Exception:
        return False


def _wait_backend(timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _healthy():
            return
        time.sleep(0.25)
    raise RuntimeError(f"后端在 {timeout:.0f} 秒内没有进入 healthy 状态")


def _backend_console_log() -> Path:
    if FROZEN:
        path = APP_DIR / "user_data" / "logs" / "backend_console.log"
    else:
        path = ROOT / "logs" / "backend_console.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _backend_popen() -> tuple[subprocess.Popen, object]:
    log_handle = _backend_console_log().open("a", encoding="utf-8", buffering=1)
    if FROZEN:
        command = [sys.executable, "--backend"]
    else:
        command = [sys.executable, str(ROOT / "run_backend.py")]
    kwargs: dict[str, object] = {
        "cwd": str(APP_DIR),
        "env": os.environ.copy(),
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    return process, log_handle


def _stop_backend_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
        )
    except Exception:
        try:
            process.terminate()
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()


def _fatal_box(title: str, message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        try:
            print(f"{title}: {message}", file=sys.stderr)
        except Exception:
            pass


def _redirect_console_to_log(stream_name: str = "frontend_console.log") -> None:
    if not FROZEN or (sys.stdout is not None and sys.stderr is not None):
        return
    path = APP_DIR / "user_data" / "logs" / stream_name
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8", buffering=1)
        sys.stdout = handle
        sys.stderr = handle
    except Exception:
        pass


def _run_backend() -> int:
    _redirect_console_to_log("backend_console.log")
    from run_backend import main

    return int(main() or 0)


def _run_frontend() -> int:
    _redirect_console_to_log("frontend_console.log")
    import faulthandler

    from frontend_pyside.app.startup import configure_process_environment

    configure_process_environment()
    if not FROZEN:
        import run_frontend

        run_frontend._check_runtime()
    from frontend_pyside.app.main import main

    faulthandler.enable()
    return int(main() or 0)


def _run_orchestrator(args: argparse.Namespace) -> int:
    if FROZEN:
        os.chdir(str(APP_DIR))
        os.environ.setdefault("USER_DATA_DIR", str(APP_DIR / "user_data"))
        os.environ.setdefault("OPTICAL_USAGE_DIR", str(APP_DIR / "user_data" / "usage"))
        os.environ.setdefault(
            "OPTICAL_PERF_LOG_PATH",
            str(APP_DIR / "user_data" / "logs" / "frontend_performance.jsonl"),
        )
        _redirect_console_to_log("frontend_console.log")

    backend = None
    backend_log_handle = None
    started_here = False
    if not _healthy():
        try:
            backend, backend_log_handle = _backend_popen()
            started_here = True
            _wait_backend(BACKEND_STARTUP_TIMEOUT_S)
        except Exception as exc:
            if backend is not None:
                _stop_backend_tree(backend)
            if backend_log_handle is not None:
                backend_log_handle.close()
            _fatal_box("后端启动失败", f"{exc}\n\n请查看日志：{_backend_console_log()}")
            return 1

    if args.backend_only:
        if not started_here:
            return 0
        try:
            return int(backend.wait() or 0) if backend is not None else 0
        except KeyboardInterrupt:
            _stop_backend_tree(backend)
            return 130
        finally:
            if backend_log_handle is not None:
                backend_log_handle.close()

    try:
        return _run_frontend()
    finally:
        if (
            started_here
            and backend is not None
            and backend.poll() is None
            and (FROZEN or args.stop_backend_on_exit)
        ):
            _stop_backend_tree(backend)
        if backend_log_handle is not None:
            backend_log_handle.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="激光耦合仿真系统及智能优化平台启动器")
    parser.add_argument("--backend", action="store_true", help="仅启动后端")
    parser.add_argument("--frontend", action="store_true", help="仅启动前端")
    parser.add_argument("--backend-only", action="store_true", help="编排模式下只启动后端并保持运行")
    parser.add_argument(
        "--stop-backend-on-exit",
        action="store_true",
        help="开发模式下关闭前端时同时关闭本次启动的后端（打包模式默认如此）",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.backend:
        return _run_backend()
    if args.frontend:
        return _run_frontend()
    return _run_orchestrator(args)


if __name__ == "__main__":
    raise SystemExit(main())