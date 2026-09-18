
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from torch import Tensor, nn
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence
from torch.utils.data import DataLoader, Dataset


@dataclass(frozen=True)
class OpticalSequenceSample:
    system_id: str
    element_types: tuple[str, ...]
    numeric_values: np.ndarray
    targets: np.ndarray


@dataclass(frozen=True)
class BiLSTMConfig:
    embedding_dim: int = 16
    hidden_dim: int = 64
    num_layers: int = 2
    dropout: float = 0.15
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    batch_size: int = 32
    max_epochs: int = 200
    patience: int = 20
    random_seed: int = 42


class ElementVocabulary:
    def __init__(self, element_types: Iterable[str] = ()) -> None:
        unique = sorted({str(value) for value in element_types})
        self.to_id = {name: index + 1 for index, name in enumerate(unique)}

    def encode(self, values: Sequence[str]) -> np.ndarray:
        unknown = sorted({str(value) for value in values if str(value) not in self.to_id})
        if unknown:
            raise ValueError("BiLSTM遇到训练词表之外的元件类型: " + ", ".join(unknown))
        return np.asarray([self.to_id[str(value)] for value in values], dtype=np.int64)

    def to_dict(self) -> dict[str, int]:
        return dict(self.to_id)

    @classmethod
    def from_dict(cls, mapping: dict[str, int]) -> "ElementVocabulary":
        obj = cls()
        obj.to_id = {str(key): int(value) for key, value in mapping.items()}
        return obj


class OpticalElementBiLSTM(nn.Module):
    def __init__(
        self,
        *,
        element_type_count: int,
        numeric_feature_count: int,
        target_count: int,
        config: BiLSTMConfig,
    ) -> None:
        super().__init__()
        self.element_embedding = nn.Embedding(
            element_type_count + 1,
            config.embedding_dim,
            padding_idx=0,
        )
        token_dim = config.embedding_dim + numeric_feature_count * 2
        self.token_encoder = nn.Sequential(
            nn.Linear(token_dim, config.hidden_dim),
            nn.LayerNorm(config.hidden_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
        )
        self.bilstm = nn.LSTM(
            input_size=config.hidden_dim,
            hidden_size=config.hidden_dim,
            num_layers=config.num_layers,
            batch_first=True,
            bidirectional=True,
            dropout=config.dropout if config.num_layers > 1 else 0.0,
        )
        encoded_dim = config.hidden_dim * 2
        self.attention = nn.Sequential(
            nn.Linear(encoded_dim, max(16, config.hidden_dim // 2)),
            nn.Tanh(),
            nn.Linear(max(16, config.hidden_dim // 2), 1),
        )
        self.output_head = nn.Sequential(
            nn.LayerNorm(encoded_dim),
            nn.Linear(encoded_dim, config.hidden_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim, target_count),
        )

    def forward(
        self,
        element_ids: Tensor,
        values: Tensor,
        observed: Tensor,
        lengths: Tensor,
    ) -> tuple[Tensor, Tensor]:
        embeddings = self.element_embedding(element_ids)
        tokens = torch.cat([embeddings, values, observed], dim=-1)
        tokens = self.token_encoder(tokens)
        packed = pack_padded_sequence(
            tokens,
            lengths.cpu(),
            batch_first=True,
            enforce_sorted=False,
        )
        packed_output, _ = self.bilstm(packed)
        encoded, _ = pad_packed_sequence(
            packed_output,
            batch_first=True,
            total_length=values.size(1),
        )
        positions = torch.arange(values.size(1), device=values.device).unsqueeze(0)
        valid = positions < lengths.unsqueeze(1)
        scores = self.attention(encoded).squeeze(-1)
        scores = scores.masked_fill(~valid, torch.finfo(scores.dtype).min)
        weights = torch.softmax(scores, dim=1)
        pooled = torch.sum(encoded * weights.unsqueeze(-1), dim=1)
        return self.output_head(pooled), weights


class _SequenceDataset(Dataset):
    def __init__(
        self,
        samples: Sequence[OpticalSequenceSample],
        vocabulary: ElementVocabulary,
        feature_scaler: StandardScaler,
        target_scaler: StandardScaler,
    ) -> None:
        self.samples = list(samples)
        self.vocabulary = vocabulary
        self.feature_scaler = feature_scaler
        self.target_scaler = target_scaler

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> dict[str, Any]:
        sample = self.samples[index]
        observed = np.isfinite(sample.numeric_values)
        filled = np.where(observed, sample.numeric_values, self.feature_scaler.mean_)
        scaled = self.feature_scaler.transform(filled)
        targets = self.target_scaler.transform(sample.targets.reshape(1, -1))[0]
        return {
            "system_id": sample.system_id,
            "element_ids": torch.from_numpy(self.vocabulary.encode(sample.element_types)),
            "values": torch.tensor(scaled, dtype=torch.float32),
            "observed": torch.tensor(observed.astype(np.float32), dtype=torch.float32),
            "targets": torch.tensor(targets, dtype=torch.float32),
        }


def _collate(batch: list[dict[str, Any]]) -> dict[str, Any]:
    lengths = torch.tensor([len(item["element_ids"]) for item in batch], dtype=torch.long)
    max_length = int(lengths.max())
    feature_count = int(batch[0]["values"].shape[1])
    batch_size = len(batch)
    element_ids = torch.zeros((batch_size, max_length), dtype=torch.long)
    values = torch.zeros((batch_size, max_length, feature_count), dtype=torch.float32)
    observed = torch.zeros_like(values)
    for row, item in enumerate(batch):
        length = len(item["element_ids"])
        element_ids[row, :length] = item["element_ids"]
        values[row, :length] = item["values"]
        observed[row, :length] = item["observed"]
    return {
        "system_id": [item["system_id"] for item in batch],
        "element_ids": element_ids,
        "values": values,
        "observed": observed,
        "lengths": lengths,
        "targets": torch.stack([item["targets"] for item in batch]),
    }


def load_long_format_sequences(
    path: str | Path,
    *,
    system_id_column: str = "system_id",
    order_column: str = "element_index",
    element_type_column: str = "element_type",
    numeric_feature_columns: Sequence[str],
    target_columns: Sequence[str],
) -> list[OpticalSequenceSample]:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        frame = pd.read_csv(path)
    elif path.suffix.lower() == ".xlsx":
        frame = pd.read_excel(path, engine="openpyxl")
    elif path.suffix.lower() == ".xls":
        raise ValueError("旧版XLS文件请先转换为XLSX或CSV格式")
    else:
        raise ValueError("BiLSTM结构数据只支持CSV或XLSX长表")

    required = {
        system_id_column,
        order_column,
        element_type_column,
        *numeric_feature_columns,
        *target_columns,
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("BiLSTM结构数据缺少列: " + ", ".join(missing))

    samples: list[OpticalSequenceSample] = []
    for system_id, group in frame.groupby(system_id_column, sort=False):
        group = group.sort_values(order_column, kind="stable")
        target_rows = group.loc[:, list(target_columns)].apply(pd.to_numeric, errors="coerce")
        if target_rows.isna().any().any():
            raise ValueError(f"系统{system_id}存在无效目标值")
        target = target_rows.iloc[0].to_numpy(dtype=float)
        if not np.allclose(target_rows.to_numpy(dtype=float), target, rtol=0.0, atol=1e-12):
            raise ValueError(f"系统{system_id}的目标值在各元件行之间不一致")
        numeric = group.loc[:, list(numeric_feature_columns)].apply(
            pd.to_numeric, errors="coerce"
        ).to_numpy(dtype=float)
        if len(group) < 1:
            continue
        samples.append(
            OpticalSequenceSample(
                system_id=str(system_id),
                element_types=tuple(group[element_type_column].astype(str)),
                numeric_values=numeric,
                targets=target,
            )
        )
    if len(samples) < 10:
        raise ValueError("BiLSTM至少需要10个独立光学系统样本")
    return samples


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def _predict_loader(model: nn.Module, loader: DataLoader, device: torch.device):
    predictions: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    model.eval()
    with torch.no_grad():
        for batch in loader:
            output, _ = model(
                batch["element_ids"].to(device),
                batch["values"].to(device),
                batch["observed"].to(device),
                batch["lengths"].to(device),
            )
            predictions.append(output.cpu().numpy())
            targets.append(batch["targets"].numpy())
    return np.vstack(predictions), np.vstack(targets)


def train_bilstm(
    samples: Sequence[OpticalSequenceSample],
    *,
    numeric_feature_names: Sequence[str],
    target_names: Sequence[str],
    config: BiLSTMConfig | None = None,
    progress: Any | None = None,
    cancellation: Any | None = None,
) -> dict[str, Any]:
    config = config or BiLSTMConfig()
    _seed_everything(config.random_seed)
    samples = list(samples)
    if any(sample.numeric_values.shape[1] != len(numeric_feature_names) for sample in samples):
        raise ValueError("BiLSTM数值特征维度与numeric_feature_names不一致")
    if any(sample.targets.size != len(target_names) for sample in samples):
        raise ValueError("BiLSTM目标维度与target_names不一致")

    train_samples, temporary = train_test_split(
        samples,
        test_size=0.30,
        random_state=config.random_seed,
    )
    validation_samples, test_samples = train_test_split(
        temporary,
        test_size=0.50,
        random_state=config.random_seed + 1,
    )
    vocabulary = ElementVocabulary(
        element_type for sample in train_samples for element_type in sample.element_types
    )
    train_features = np.vstack([sample.numeric_values for sample in train_samples])
    feature_scaler = StandardScaler().fit(
        np.where(np.isfinite(train_features), train_features, np.nan)
    )
    
    
    feature_scaler.mean_ = np.nan_to_num(feature_scaler.mean_, nan=0.0)
    feature_scaler.scale_ = np.nan_to_num(feature_scaler.scale_, nan=1.0, posinf=1.0)
    feature_scaler.scale_[feature_scaler.scale_ == 0.0] = 1.0
    target_scaler = StandardScaler().fit(
        np.vstack([sample.targets for sample in train_samples])
    )

    datasets = [
        _SequenceDataset(split, vocabulary, feature_scaler, target_scaler)
        for split in (train_samples, validation_samples, test_samples)
    ]
    loaders = [
        DataLoader(
            dataset,
            batch_size=config.batch_size,
            shuffle=index == 0,
            collate_fn=_collate,
        )
        for index, dataset in enumerate(datasets)
    ]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = OpticalElementBiLSTM(
        element_type_count=len(vocabulary.to_id),
        numeric_feature_count=len(numeric_feature_names),
        target_count=len(target_names),
        config=config,
    ).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    loss_fn = nn.SmoothL1Loss()
    best_state: dict[str, Tensor] | None = None
    best_validation = float("inf")
    stale_epochs = 0
    history: list[dict[str, float]] = []

    for epoch in range(config.max_epochs):
        if cancellation is not None and cancellation.is_cancelled:
            raise RuntimeError("BiLSTM训练已取消")
        model.train()
        train_losses: list[float] = []
        for batch in loaders[0]:
            optimizer.zero_grad(set_to_none=True)
            output, _ = model(
                batch["element_ids"].to(device),
                batch["values"].to(device),
                batch["observed"].to(device),
                batch["lengths"].to(device),
            )
            loss = loss_fn(output, batch["targets"].to(device))
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
            optimizer.step()
            train_losses.append(float(loss.detach().cpu()))

        validation_pred, validation_true = _predict_loader(model, loaders[1], device)
        validation_loss = float(np.mean((validation_pred - validation_true) ** 2))
        history.append(
            {
                "epoch": float(epoch + 1),
                "train_loss": float(np.mean(train_losses)),
                "validation_mse_scaled": validation_loss,
            }
        )
        if progress is not None:
            progress.update(
                min((epoch + 1) / config.max_epochs, 0.99),
                "training.bilstm",
                completed_items=epoch + 1,
                total_items=config.max_epochs,
            )
        if validation_loss < best_validation - 1e-8:
            best_validation = validation_loss
            best_state = {
                key: value.detach().cpu().clone()
                for key, value in model.state_dict().items()
            }
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= config.patience:
                break

    if best_state is None:
        raise RuntimeError("BiLSTM训练未产生有效权重")
    model.load_state_dict(best_state)
    model.to(device)
    test_scaled, test_true_scaled = _predict_loader(model, loaders[2], device)
    test_prediction = target_scaler.inverse_transform(test_scaled)
    test_truth = target_scaler.inverse_transform(test_true_scaled)
    metrics: dict[str, dict[str, float]] = {}
    for index, target_name in enumerate(target_names):
        truth = test_truth[:, index]
        prediction = test_prediction[:, index]
        metrics[str(target_name)] = {
            "r2": float(r2_score(truth, prediction)) if len(truth) > 1 else float("nan"),
            "mae": float(mean_absolute_error(truth, prediction)),
            "rmse": float(np.sqrt(mean_squared_error(truth, prediction))),
        }

    # Keep the point-level test split alongside aggregate metrics.  The
    # desktop training-result page uses this same evaluation contract as the
    # tree models to draw residual and measured-vs-predicted charts.
    evaluation = {
        "sample_ids": [str(sample.system_id) for sample in test_samples],
        "actual": test_truth.tolist(),
        "predicted": test_prediction.tolist(),
        "residual": (test_prediction - test_truth).tolist(),
    }

    return {
        "state_dict": best_state,
        "config": asdict(config),
        "vocabulary": vocabulary.to_dict(),
        "feature_scaler": feature_scaler,
        "target_scaler": target_scaler,
        "numeric_feature_names": list(numeric_feature_names),
        "target_names": list(target_names),
        "metrics": metrics,
        "history": history,
        "split_counts": {
            "train": len(train_samples),
            "validation": len(validation_samples),
            "test": len(test_samples),
        },
        "evaluation": evaluation,
    }


def save_bilstm(artifact: dict[str, Any], model_dir: str | Path) -> Path:
    import joblib

    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    torch.save(artifact["state_dict"], model_dir / "model_state.pt")
    joblib.dump(artifact["feature_scaler"], model_dir / "feature_scaler.joblib")
    joblib.dump(artifact["target_scaler"], model_dir / "target_scaler.joblib")
    metadata = {
        key: artifact[key]
        for key in (
            "config",
            "vocabulary",
            "numeric_feature_names",
            "target_names",
            "metrics",
            "history",
            "split_counts",
            "evaluation",
        )
    }
    (model_dir / "manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return model_dir


def load_bilstm(model_dir: str | Path) -> dict[str, Any]:
    import joblib

    model_dir = Path(model_dir)
    metadata = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
    metadata["state_dict"] = torch.load(
        model_dir / "model_state.pt",
        map_location="cpu",
        weights_only=True,
    )
    metadata["feature_scaler"] = joblib.load(model_dir / "feature_scaler.joblib")
    metadata["target_scaler"] = joblib.load(model_dir / "target_scaler.joblib")
    return metadata


def predict_bilstm(
    artifact: dict[str, Any],
    *,
    element_types: Sequence[str],
    numeric_values: Sequence[Sequence[float]],
) -> dict[str, Any]:
    config = BiLSTMConfig(**artifact["config"])
    vocabulary = ElementVocabulary.from_dict(artifact["vocabulary"])
    values_array = np.asarray(numeric_values, dtype=float)
    if values_array.ndim != 2:
        raise ValueError("numeric_values必须是[元件数, 数值特征数]二维数组")
    if len(element_types) != len(values_array):
        raise ValueError("element_types与numeric_values的元件数量不一致")
    sample = OpticalSequenceSample(
        system_id="prediction",
        element_types=tuple(element_types),
        numeric_values=values_array,
        targets=np.zeros(len(artifact["target_names"]), dtype=float),
    )
    dataset = _SequenceDataset(
        [sample],
        vocabulary,
        artifact["feature_scaler"],
        artifact["target_scaler"],
    )
    batch = _collate([dataset[0]])
    model = OpticalElementBiLSTM(
        element_type_count=len(vocabulary.to_id),
        numeric_feature_count=len(artifact["numeric_feature_names"]),
        target_count=len(artifact["target_names"]),
        config=config,
    )
    model.load_state_dict(artifact["state_dict"])
    model.eval()
    with torch.no_grad():
        scaled, attention = model(
            batch["element_ids"],
            batch["values"],
            batch["observed"],
            batch["lengths"],
        )
    prediction = artifact["target_scaler"].inverse_transform(scaled.numpy())[0]
    return {
        "predictions": {
            name: float(prediction[index])
            for index, name in enumerate(artifact["target_names"])
        },
        "attention": attention.numpy()[0, : len(element_types)].tolist(),
        "element_types": list(element_types),
    }
