from backend.optical_ml_app.application.ports import TaskManagerPort


def _run_simulation_task(context, request):

    from optical_runtime import create_optical_simulation_engine
    getter = getattr(context, "get_or_create_resource", None)
    if callable(getter):
        engine = getter("optical_engine", create_optical_simulation_engine)
    else:
        engine = create_optical_simulation_engine()
    return engine.evaluate(request, context.cancellation, context.progress)


class SimulationApplicationService:


    def __init__(self, task_manager: TaskManagerPort, engine_registry=None):
        self.task_manager = task_manager
        self.engine_registry = engine_registry

    def submit(self, request):
        if self.engine_registry is None:
            def _task(context):
                return _run_simulation_task(context, request)
        else:
            
            
            
            engine = self.engine_registry.resolve(getattr(request, "engine", None))

            def _task(context):
                return engine.evaluate(request, None, context.progress)
        request_id = str(getattr(request, "request_id", "") or "").strip()
        return self.task_manager.submit(
            "simulation",
            _task,
            idempotency_key=(f"simulation:{request_id}" if request_id else ""),
        )
