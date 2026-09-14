from backend.optical_ml_app.domain.errors import BackendApplicationError


class PredictionApplicationService:
    def __init__(self, predictor):
        self.predictor = predictor

    def predict(self, request):
        try:
            return self.predictor.predict(request)
        except FileNotFoundError as exc:
            raise BackendApplicationError(
                code="MODEL_NOT_FOUND",
                stage="model.predict",
                message=f"模型 {request.model_id} 不存在或文件不完整",
                context={"model_id": request.model_id},
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            text = str(exc)
            if "缺少特征" in text or "feature" in text.lower():
                code = "MODEL_FEATURE_MISSING"
            elif "测试 R²" in text or "模型质量" in text:
                code = "MODEL_QUALITY_REJECTED"
            else:
                code = "MODEL_PREDICTION_FAILED"
            raise BackendApplicationError(
                code=code,
                stage="model.predict",
                message=text or "模型没有返回有效预测",
                context={"model_id": request.model_id},
            ) from exc
        except Exception as exc:
            # Do not let an unexpected predictor/runtime exception escape as a
            # bare HTTP 500.  The UI can then keep the failure attached to the
            # prediction task and tell the user what to do next.
            raise BackendApplicationError(
                code="MODEL_PREDICTION_FAILED",
                stage="model.predict",
                message=f"模型预测失败：{type(exc).__name__}: {exc}",
                context={"model_id": request.model_id},
            ) from exc
