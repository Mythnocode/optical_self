"""Qt signals around the shared authoritative teaching scene model."""
from shared_presentation.teaching_model import (
    BENCH_ORIGIN_X_MM,
    CCD_SENSOR_HEIGHT_MM,
    CCD_SENSOR_WIDTH_MM,
    ComponentKind,
    DEFAULT_BEAM_RADIUS_MM,
    DEFAULT_CENTER_THICKNESS_MM,
    DEFAULT_LENS_INDEX,
    FLOAT_PARAM_NAMES,
    KIND_DEFAULT_PARAMS,
    KIND_PARAM_SPECS,
    MIRROR_RUNTIME_FOLD_DEG,
    OPTIONAL_UNSET_PARAM_NAMES,
    OpticalComponent,
    PITCH_DEG_MAX,
    PITCH_RAD_MAX,
    PLACEABLE_KINDS,
    Pose,
    RESERVED_COMPONENT_IDS,
    RESERVED_COMPONENT_ID_PREFIXES,
    RUNTIME_KIND_ALIAS,
    ResultKind,
    SceneReference,
    SceneSnapshot,
    TEACHING_KIND_MIME,
    _filter_fields,
    _optional_nonzero,
    compile_component_params,
    component_id_is_reserved,
    component_kind_label,
    default_params_for_kind,
    normalize_component_params,
    runtime_kind,
)
from shared_presentation.teaching_model import SceneStore as _SceneState, __all__
from .qt_compat import QObject, Signal

class SceneStore(QObject, _SceneState):
    sceneChanged = Signal(object, str)
    selectionChanged = Signal(object)
    resultChanged = Signal(str, object)
    saved = Signal(str)

    def __init__(self, parent: QObject | None = None, *, start_empty: bool = False) -> None:
        QObject.__init__(self, parent)
        _SceneState.__init__(self, start_empty=start_empty)
