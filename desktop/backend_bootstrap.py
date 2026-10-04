"""Desktop entry point for the existing Python backend.

Some optional SHAP/OpenCV installations leave their package directory at the
front of sys.path, shadowing Python's typing module in Windows spawn workers.
Import SHAP before the service graph starts, and restore the import path before
any worker can inherit it. Computation and backend routes stay in Python.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    import_path = sys.path[:]
    try:
        import shap  # noqa: F401
    except Exception:
        # SHAP is optional; the backend reports its absence on explain routes.
        pass
    finally:
        sys.path[:] = import_path

    from run_backend import main as run_backend

    run_backend()


if __name__ == "__main__":
    main()
