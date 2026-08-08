from typing import List, Tuple
import numpy as np


def split_ids(ids: List[str], train_ratio: float, validation_ratio: float, seed: int) -> Tuple[List[str], List[str], List[str]]:
    rng = np.random.default_rng(seed)
    shuffled = list(ids)
    rng.shuffle(shuffled)
    n = len(shuffled)
    train_end = int(n * train_ratio)
    val_end = train_end + int(n * validation_ratio)
    return shuffled[:train_end], shuffled[train_end:val_end], shuffled[val_end:]
