"""Railway application entrypoint.

Loads the existing ODS/router Flask application, then registers auxiliary bots
that share the same Railway web service.
"""
from ods_router import app
from household_bot import init_household_bot

init_household_bot(app)
