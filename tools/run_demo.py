from __future__ import annotations

"""一键启动平台演示态。

- 启动后端并等待真实 /health 就绪；
- 默认启用包内真实示例数据/模型/SHAP缓存；
- 后端真正就绪后才启动前端；
- 默认把后端作为独立服务保留：关闭/重启 GUI 不会终止正在运行的科研任务；
- 可用 --stop-backend-on-exit 恢复“GUI 退出时关闭本次启动后端”的旧行为。
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
HEALTH = "http://127.0.0.1:8000/api/v1/health"
LOG_DIR = ROOT / "logs"
BACKEND_LOG = LOG_DIR / "demo_backend.log"


def _healthy() -> bool:
    try:
        r = requests.get(HEALTH, timeout=0.8)
        body = r.json() if r.ok else {}
        return bool(r.ok and body.get("code") == "OK" and (body.get("data") or {}).get("status") == "healthy")
    except Exception:
        return False


def _wait_backend(timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _healthy():
            return
        time.sleep(0.25)
    raise RuntimeError(f"后端在 {timeout:.0f} 秒内没有进入 healthy 状态")


def _backend_popen(env: dict[str, str]) -> tuple[subprocess.Popen, object]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = BACKEND_LOG.open("a", encoding="utf-8", buffering=1)
    kwargs: dict[str, object] = {
        "cwd": ROOT,
        "env": env,
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen([sys.executable, "run_backend.py"], **kwargs)
    return process, log_handle


def _stop_backend(backend: subprocess.Popen) -> None:
    if backend.poll() is not None:
        return
    backend.terminate()
    try:
        backend.wait(timeout=8)
    except subprocess.TimeoutExpired:
        backend.kill()
        backend.wait(timeout=3)


def main() -> int:
    parser = argparse.ArgumentParser(description="启动平台演示态；示例资产来自真实管线，不自动采用。")
    parser.add_argument("--backend-only", action="store_true", help="只启动后端并保持运行")
    parser.add_argument("--no-demo-assets", action="store_true", help="不自动安装包内示例资产")
    parser.add_argument("--startup-timeout", type=float, default=45.0)
    parser.add_argument(
        "--stop-backend-on-exit",
        action="store_true",
        help="关闭前端时同时关闭本次启动的后端；默认后端独立继续运行",
    )
    args = parser.parse_args()

    env = os.environ.copy()
    env["INSTALL_DEMO_ASSETS"] = "0" if args.no_demo_assets else "1"
    backend = None
    backend_log_handle = None
    started_here = False
    if not _healthy():
        backend, backend_log_handle = _backend_popen(env)
        started_here = True
        try:
            _wait_backend(args.startup_timeout)
        except Exception:
            _stop_backend(backend)
            if backend_log_handle is not None:
                backend_log_handle.close()
            raise
    print("后端已就绪。示例资产：" + ("关闭" if args.no_demo_assets else "启用（不会自动采用）"), flush=True)
    if started_here:
        print(f"后端日志：{BACKEND_LOG}", flush=True)

    if args.backend_only:
        if backend is None:
            print("检测到已有后端，未重复启动。", flush=True)
            return 0
        try:
            return int(backend.wait() or 0)
        except KeyboardInterrupt:
            _stop_backend(backend)
            return 130
        finally:
            if backend_log_handle is not None:
                backend_log_handle.close()

    try:
        return int(subprocess.call([sys.executable, "run_frontend.py"], cwd=ROOT, env=env) or 0)
    finally:
        if started_here and backend is not None and backend.poll() is None:
            if args.stop_backend_on_exit:
                _stop_backend(backend)
                print("前端已退出，本次启动的后端也已关闭。", flush=True)
            else:
                print("前端已退出；后端保持独立运行，正在计算的任务不会因 GUI 关闭而中断。", flush=True)
        if backend_log_handle is not None:
            backend_log_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
