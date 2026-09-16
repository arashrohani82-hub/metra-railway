"""Runtime bootstrap patches loaded automatically by Python."""
try:
    import ods_recovery  # noqa: F401
except Exception:
    # Never prevent Gunicorn from starting if an optional recovery patch fails.
    pass
