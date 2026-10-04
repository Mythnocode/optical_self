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
    import socket
    import uvicorn

    # Reserve the port before constructing services. A second launcher must
    # fail before restart recovery can touch an already running server's jobs.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 8000))
        listener.listen(128)
        from backend.optical_ml_app.main import app

        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, reload=False))
        server.run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    main()
