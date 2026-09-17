"""Runtime bootstrap patches loaded automatically by Python.

IMPORTANT: Railway/Gunicorn loads this module before runtime.py. Therefore the
final ODS department patch must be installed here, after recovery, so the
Telegram handler that app.py's webhook resolves is department-aware from the
start.
"""
import logging

_bootlog = logging.getLogger('sitecustomize')

try:
    import ods_recovery  # noqa: F401
    _bootlog.warning('BOOTSTRAP: ODS recovery loaded')
except Exception:
    _bootlog.exception('BOOTSTRAP: ODS recovery failed')

try:
    import department_ods_patch  # noqa: F401
    _bootlog.warning('BOOTSTRAP: DEPARTMENT STR/CIV/GEO PATCH LOADED')
except Exception:
    _bootlog.exception('BOOTSTRAP: department ODS patch failed')
