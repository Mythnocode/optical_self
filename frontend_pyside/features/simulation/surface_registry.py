"""Qt compatibility imports for the shared surface presentation registry."""
from shared_presentation.surface_registry import (
    SurfaceParameterSpec,
    SurfaceTypeSpec,
    SURFACE_TYPES,
    surface_type_names,
    get_surface_type,
    ensure_surface_defaults,
    apply_type_defaults,
    surface_feature_summary,
    extra_parameter_columns,
    extra_header_label,
    surface_uses_parameter,
    format_parameter_cell,
    parse_parameter_cell,
    next_group_id,
)
