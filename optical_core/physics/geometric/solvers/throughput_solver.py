# 计算几何通光率。
# 根据最终有效光线数量计算简单的几何通光率。
from __future__ import annotations

import numpy as np

from optical_core.models.representations.trace import TraceBundle


def geometric_throughput(trace: TraceBundle) -> float:
    mask = np.asarray(trace.valid_mask, dtype=bool)
    if mask.size == 0:
        return 0.0
    return float(np.count_nonzero(mask) / mask.size)
