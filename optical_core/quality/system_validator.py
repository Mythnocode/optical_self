from optical_core.models.domain.system import SequentialOpticalSystem
from optical_core.quality.errors import OpticalValidationError


def validate_system(system: SequentialOpticalSystem) -> None:
    if not system.surfaces:
        raise OpticalValidationError("INVALID_PROJECT", "光学系统至少需要一个曲面")
    if system.pupil_radius_mm <= 0:
        raise OpticalValidationError("INVALID_PROJECT", "pupil_radius_mm 必须大于 0")
    if system.wavelength_nm <= 0:
        raise OpticalValidationError("INVALID_PROJECT", "wavelength_nm 必须大于 0")
    for surface in system.surfaces:
        if surface.clear_aperture_mm is not None and surface.clear_aperture_mm <= 0:
            raise OpticalValidationError("INVALID_PROJECT", f"第 {surface.index} 面 clear_aperture_mm 必须大于 0")
