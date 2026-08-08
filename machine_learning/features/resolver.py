import re
from shared_contracts.parameters import ParameterChange
from shared_contracts.project import ProjectSnapshot

_SURFACE = re.compile(r"^surfaces\[(\d+)\]\.(.+)$")


class FeatureResolver:
    def get_value(self, project: ProjectSnapshot, path: str) -> float:
        match = _SURFACE.match(path)
        if match:
            index = int(match.group(1))
            field = match.group(2)
            return float(getattr(project.surfaces[index], field))
        current = project
        for part in path.split("."):
            current = getattr(current, part)
        return float(current)

    def create_change(self, path: str, value: float, unit: str = None) -> ParameterChange:
        return ParameterChange(path=path, value=value, unit=unit)
