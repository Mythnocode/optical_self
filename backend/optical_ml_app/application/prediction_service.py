class PredictionApplicationService:
    def __init__(self, predictor):
        self.predictor = predictor

    def predict(self, request):
        return self.predictor.predict(request)
