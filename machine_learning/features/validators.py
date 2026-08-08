def validate_bounds(lower: float, upper: float) -> None:
    if lower >= upper:
        raise ValueError("lower_bound 必须小于 upper_bound")
