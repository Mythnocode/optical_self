from typing import List, Sequence, Tuple
import numpy as np


def split_ids(ids: List[str], train_ratio: float, validation_ratio: float, seed: int) -> Tuple[List[str], List[str], List[str]]:
    rng = np.random.default_rng(seed)
    shuffled = list(ids)
    rng.shuffle(shuffled)
    n = len(shuffled)
    if n == 0:
        return [], [], []
    train_ratio = max(0.0, float(train_ratio))
    validation_ratio = max(0.0, float(validation_ratio))
    if n >= 3:
        rest = n - 3
        n_train = 1 + int(rest * train_ratio)
        n_val = 1 + int(rest * validation_ratio)
        n_test = n - n_train - n_val
        if n_test < 1:
            n_train = max(1, n_train - (1 - n_test))
            n_test = 1
        return shuffled[:n_train], shuffled[n_train:n_train + n_val], shuffled[n_train + n_val:]
    train_end = int(n * train_ratio)
    val_end = train_end + int(n * validation_ratio)
    return shuffled[:train_end], shuffled[train_end:val_end], shuffled[val_end:]


def resolve_training_splits(
    sample_ids: Sequence[str],
    train_ids: Sequence[str],
    validation_ids: Sequence[str],
    test_ids: Sequence[str],
    *,
    seed: int,
    train_ratio: float = 0.7,
    validation_ratio: float = 0.15,
) -> Tuple[List[str], List[str], List[str]]:
    """Reuse a stored split when all three parts have samples; otherwise rebuild."""
    present = set(sample_ids)
    train = [item for item in train_ids if item in present]
    validation = [item for item in validation_ids if item in present]
    test = [item for item in test_ids if item in present]
    if train and validation and test:
        return train, validation, test
    if len(present) < 3:
        return train, validation, test
    return split_ids(list(sample_ids), train_ratio, validation_ratio, int(seed))


def too_few_samples_message(valid_count: int | None = None) -> str:
    if valid_count is None:
        return (
            "可用样本太少，模型学不成。"
            "请打开「数据管理」，把样本数调到 50 以上后重新点 ▶ 生成，再回来训练。"
        )
    if valid_count <= 0:
        return (
            "没有算出可用的样本，模型没法学习。"
            "请先确认镜头组能完成耦合计算，再打开「数据管理」重新点 ▶ 生成数据集。"
        )
    return (
        f"现在只有 {int(valid_count)} 条可用样本，数量不够，模型学不成。"
        "请打开「数据管理」，把样本数调到 50 以上后重新点 ▶ 生成，再回来训练。"
    )
