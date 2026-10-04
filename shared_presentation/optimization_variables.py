"""Original editable variable values and ranges, without a Qt dependency."""
def current_value(project, key: str) -> str:
    if key.startswith('surfaces['):
        try:
            index = int(key.split('[', 1)[1].split(']', 1)[0])
            field = key.split('].', 1)[1]
            surface = list(getattr(project, 'surfaces', ()) or ())[index]
            attribute = {'radius_mm': 'radius_mm', 'distance_to_next_mm': 'thickness_mm', 'semi_aperture_mm': 'semi_aperture_mm'}.get(field)
            if attribute:
                return f'{float(getattr(surface, attribute)):.2f}'
        except (ValueError, IndexError, AttributeError, TypeError):
            pass
    return '—'

def variable_range(value: str) -> tuple[str, str]:
    try:
        number = float(value)
        span = max(abs(number) * .10, 1e-6)
        return f'{number - span:g}', f'{number + span:g}'
    except ValueError:
        return '—', '—'
