"""Endpoints for checking whether the API and database are reachable."""

from flask import Blueprint

from ..database import query
from ..responses import success

# Group these routes together. create_app() registers this blueprint with
# the /api prefix, so /health becomes /api/health.
health = Blueprint("health", __name__)


@health.get("/health")
def health_check():
    # Check that the app responds without needing the database.
    return success({"status": "ok"})


@health.get("/health/db")
def database_check():
    # Test a database query without checking project tables or changing data.
    # A failed query goes to Flask's error handlers instead of returning success.
    query("SELECT 1 AS ready")
    return success({"status": "ok", "database": "connected"})
