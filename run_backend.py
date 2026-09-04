from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    # Keep the FastAPI app import inside the real parent entry point. The job
    # manager uses multiprocessing "spawn"; spawned workers re-import the
    # parent's main module as __mp_main__. Importing backend.main at module scope
    # would therefore create a second service graph inside every worker and run
    # restart-recovery against the parent's live job repository.
    import uvicorn
    from backend.optical_ml_app.main import app

    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
