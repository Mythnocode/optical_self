def fmt(value, digits=3):
    try: return f"{float(value):.{digits}f}"
    except (TypeError, ValueError): return str(value)
