from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.preprocessing import StandardScaler


@dataclass
class PreparedData:
    X_train: object
    X_validation: object
    X_test: object
    y_train: object
    y_validation: object
    y_test: object


class PreprocessingPipeline:


    def __init__(self, *, scale_features: bool = True, scale_targets: bool = True):
        self.scale_features = bool(scale_features)
        self.scale_targets = bool(scale_targets)
        self.x_scaler = StandardScaler() if self.scale_features else None
        self.y_scaler = StandardScaler() if self.scale_targets else None

    def fit_transform(
        self,
        X_train,
        X_validation,
        X_test,
        y_train,
        y_validation,
        y_test,
    ):
        if self.x_scaler is not None:
            self.x_scaler.fit(X_train)
            X_train_out = self.x_scaler.transform(X_train)
            X_validation_out = self.x_scaler.transform(X_validation)
            X_test_out = self.x_scaler.transform(X_test)
        else:
            X_train_out = np.asarray(X_train, dtype=float)
            X_validation_out = np.asarray(X_validation, dtype=float)
            X_test_out = np.asarray(X_test, dtype=float)

        if self.y_scaler is not None:
            self.y_scaler.fit(y_train)
            y_train_out = self.y_scaler.transform(y_train)
            y_validation_out = self.y_scaler.transform(y_validation)
            y_test_out = self.y_scaler.transform(y_test)
        else:
            y_train_out = np.asarray(y_train, dtype=float)
            y_validation_out = np.asarray(y_validation, dtype=float)
            y_test_out = np.asarray(y_test, dtype=float)

        return PreparedData(
            X_train_out,
            X_validation_out,
            X_test_out,
            y_train_out,
            y_validation_out,
            y_test_out,
        )

    def transform_features(self, X):
        if self.x_scaler is None:
            return np.asarray(X, dtype=float)
        return self.x_scaler.transform(X)

    def inverse_targets(self, y):
        values = np.asarray(y, dtype=float)
        if values.ndim == 1:
            values = values.reshape(-1, 1)
        if self.y_scaler is None:
            return values
        return self.y_scaler.inverse_transform(values)
