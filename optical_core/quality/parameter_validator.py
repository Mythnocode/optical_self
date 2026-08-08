SUPPORTED_PARAMETER_PREFIXES = (
    "surfaces[",
    "image_distance_mm",
    "receiver.",
    "source.",
)


def validate_parameter_path(path: str) -> None:
    if not path.startswith(SUPPORTED_PARAMETER_PREFIXES):
        raise ValueError("INVALID_PARAMETER_PATH: %s" % path)
