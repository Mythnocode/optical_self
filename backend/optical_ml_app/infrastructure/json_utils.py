

from __future__ import annotations

import math
from typing import Any


def _is_numpy(value: Any) -> bool:

    
    type_name = type(value).__module__
    if type_name != "numpy":
        return False
    
    import numpy as np  
    return isinstance(value, (np.ndarray, np.generic))


def _numpy_to_json(value: Any) -> Any:

    import numpy as np  
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def to_jsonable(value: Any) -> Any:

    
    if _is_numpy(value):
        value = _numpy_to_json(value)
        
        return to_jsonable(value)

    if hasattr(value, "model_dump"):
        
        
        raw = value.model_dump(mode="python")
        return _clean_value(raw)

    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    return value


def _clean_value(obj: Any) -> Any:

    if _is_numpy(obj):
        return _numpy_to_json(obj)

    if isinstance(obj, dict):
        return {k: _clean_value(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [_clean_value(v) for v in obj]

    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj

    return obj


def to_storage_value(value: Any) -> Any:

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="python")
    if _is_numpy(value):
        import numpy as np  
        if isinstance(value, np.ndarray):
            return value
        if isinstance(value, np.generic):
            return value.item()
    if isinstance(value, dict):
        return {str(k): to_storage_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_storage_value(v) for v in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


__all__ = ["to_jsonable", "to_storage_value"]
