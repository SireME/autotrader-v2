def safe_float(val, default=None):
    try:
        return float(val)
    except Exception:
        return default
