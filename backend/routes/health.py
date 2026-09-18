"""Endpoints for checking whether the API and database are reachable."""

from flask import Blueprint

# Two dots refer to the parent package, backend.
from ..database import query
from ..responses import success

# Group these routes together. create_app() registers this blueprint with
# the /api prefix, so /health becomes /api/health.
health = Blueprint("health", __name__)


# A GET request to /api/health runs the function below.
@health.get("/health")
def health_check():
    # No database access, this confirms the application itself can respond.
    # success() wraps the dictionary in our standard JSON response format.
    return success({"status": "ok"})


@health.get("/health/db")
def database_check():
    # Execute a small, read-only query: return 1 in a column named "ready".
    # This checks connectivity and SQL execution, not project tables or data.
    # If it raises an error, Flask's error handlers produce the response;
    # execution will not reach the success return below.
    query("SELECT 1 AS ready")
    return success({"status": "ok", "database": "connected"})
