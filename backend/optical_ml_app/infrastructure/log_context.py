from contextlib import contextmanager
from contextvars import ContextVar

trace_id_var = ContextVar("trace_id", default="")
job_id_var = ContextVar("job_id", default="")
request_id_var = ContextVar("request_id", default="")
project_fingerprint_var = ContextVar("project_fingerprint", default="")
engine_var = ContextVar("engine", default="")


@contextmanager
def log_context(**values):
    tokens = []
    mapping = {
        "trace_id": trace_id_var,
        "job_id": job_id_var,
        "request_id": request_id_var,
        "project_fingerprint": project_fingerprint_var,
        "engine": engine_var,
    }
    try:
        for name, value in values.items():
            if name in mapping:
                tokens.append((mapping[name], mapping[name].set(str(value or ""))))
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)
