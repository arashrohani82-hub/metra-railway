"""Runtime bootstrap patches loaded automatically by Python.

Railway/Gunicorn loads this module before runtime.py. Install the complete ODS
department stack here so the Telegram callback path is department-aware before
Flask/Gunicorn starts serving requests.
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

try:
    import department_contract_templates  # noqa: F401
    _bootlog.warning('BOOTSTRAP: department contract templates loaded')
except Exception:
    _bootlog.exception('BOOTSTRAP: department contract templates failed')

try:
    import department_assumption_questions  # noqa: F401
    _bootlog.warning('BOOTSTRAP: CIV/GEO ASSUMPTION QUESTIONS LOADED')
except Exception:
    _bootlog.exception('BOOTSTRAP: CIV/GEO assumption questions failed')

try:
    import justify_pdf_text  # noqa: F401
    _bootlog.warning('BOOTSTRAP: PDF justification loaded')
except Exception:
    _bootlog.exception('BOOTSTRAP: PDF justification failed')
