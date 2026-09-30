"""Net Value Flask application factory."""

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from .database import close_db
from .responses import failure


def create_app(test_config=None):
    # Build the app with its settings, routes, and shared error handlers.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    app = Flask(__name__)
    app.config.from_mapping(
        # Use the test database unless a DATABASE_URL is explicitly supplied.
        DATABASE_URL=os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL"),
        CORS_ORIGINS=os.getenv(
            "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
        ).split(","),
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    if test_config is not None:
        # Tests can override settings without changing the local .env file.
        app.config.update(test_config)
    # Let the configured frontend origins read API responses in the browser.
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})
    # Clean up database connections after requests, including failed ones.
    app.teardown_appcontext(close_db)

    from .routes.catalog import catalog
    from .routes.health import health
    from .routes.pending import pending
    from .routes.projections import projections

    for blueprint in (catalog, health, pending, projections):
        # Each route group shares the /api URL prefix.
        app.register_blueprint(blueprint, url_prefix="/api")

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        # Return JSON for HTTP errors instead of Flask's default HTML page.
        response, status = failure(
            error.name.upper().replace(" ", "_"), error.description, error.code
        )
        # Keep headers such as Allow, which lists the permitted HTTP methods.
        original = error.get_response()
        original.set_data(response.get_data())
        original.content_type = "application/json"
        return original, status

    @app.errorhandler(psycopg2.Error)
    def handle_database_error(error):
        # Do not log exception text: connection errors may contain credentials.
        app.logger.error("Database operation failed (%s)", type(error).__name__)
        return failure("DATABASE_UNAVAILABLE", "The database is unavailable.", 503)

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.error("Request failed (%s)", type(error).__name__)
        return failure("INTERNAL_ERROR", "An unexpected error occurred.", 500)

    return app
