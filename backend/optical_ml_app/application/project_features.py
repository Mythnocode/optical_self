"""Transport adapter for the existing project and physics feature builders."""
from math import isfinite
import re
from collections.abc import Mapping

from machine_learning.features.coupling_physics import (
    PHYSICS_RESIDUAL_FEATURE_PATHS,
    derive_coupling_physics_features,
)
from shared_contracts.project import ProjectSnapshot

_PATH = re.compile(r"([^\.\[\]]+)|\[(\d+)\]")


def project_features(project: ProjectSnapshot, paths: list[str]) -> dict[str, float]:
    physics = derive_coupling_physics_features(project) if any(path in PHYSICS_RESIDUAL_FEATURE_PATHS for path in paths) else {}
    data = project.model_dump()
    values = {}
    for original in paths:
        path = original
        legacy = re.fullmatch(r"surface\.(\d+)\.(.+)", path)
        if legacy:
            field = "distance_to_next_mm" if legacy[2] == "thickness_mm" else legacy[2]
            path = f"surfaces[{legacy[1]}].{field}"
        if path == "wavelength_nm": path = "source.wavelength_nm"
        if path in physics:
            value = physics[path]
        else:
            active = re.fullmatch(r"surfaces\[(\d+)\]\.active", path)
            if active:
                index = int(active[1])
                value = index < len(project.surfaces) and project.surfaces[index].enabled
            else:
                tokens = _PATH.findall(path)
                reconstructed = "".join(f"[{index}]" if index else (("." if i else "") + name) for i, (name, index) in enumerate(tokens))
                if not tokens or reconstructed != path: raise ValueError(f"无效特征路径：{original}")
                value = data
                for name, index in tokens:
                    if index:
                        if not isinstance(value, list) or int(index) >= len(value): raise ValueError(f"当前项目缺少特征：{original}")
                        value = value[int(index)]
                    elif isinstance(value, Mapping) and name in value: value = value[name]
                    else: raise ValueError(f"当前项目缺少特征：{original}")
        try: number = float(value)
        except (TypeError, ValueError) as exc: raise ValueError(f"当前项目特征不是数值：{original}") from exc
        if not isfinite(number): raise ValueError(f"当前项目特征不是有限数值：{original}")
        values[original] = number
    return values
