from PySide6.QtCore import QObject, QRunnable, Signal, Slot

class WorkerSignals(QObject):
    result=Signal(object); error=Signal(str); finished=Signal()

class FunctionWorker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__(); self.fn=fn; self.args=args; self.kwargs=kwargs; self.signals=WorkerSignals()
    @Slot()
    def run(self):
        try: self.signals.result.emit(self.fn(*self.args, **self.kwargs))
        except Exception as exc: self.signals.error.emit(str(exc))
        finally: self.signals.finished.emit()
