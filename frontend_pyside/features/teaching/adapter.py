class LocalTeachingAdapter:
    def __init__(self,service): self.service=service
    def catalog(self): return self.service.catalog()
    def evaluate(self,module,inputs): return self.service.evaluate(module,inputs)
    def prediction(self,module,payload): return self.service.prediction(module,payload)
    def scan(self,module,payload): return self.service.scan(module,payload)
    def diagnostics(self,module,payload): return self.service.diagnostics(module,payload)
    def score(self,module,payload): return self.service.score(module,payload)
    def report(self,module,payload): return self.service.report(module,payload)
