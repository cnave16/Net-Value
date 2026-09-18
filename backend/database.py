"""Request-scoped, read-only PostgreSQL connections; no startup writes."""

import psycopg2
from flask import current_app, g
from psycopg2.extras import RealDictCursor
from werkzeug.exceptions import ServiceUnavailable


def get_db():
    """Return this request's connection, opening a read-only connection if needed."""
    # Flask's g holds data for the current application context (normally one
    # request), so multiple queries in that request reuse the same connection.
    if "db" not in g:
        url = current_app.config.get("DATABASE_URL")
        if not url:
            raise ServiceUnavailable("Database connection is not configured.")
        # This timeout limits connection establishment, not SQL execution.
        connection = psycopg2.connect(url, connect_timeout=5)
        try:
            connection.set_session(readonly=True)
            # Neon poolers may reject PostgreSQL startup options. Set the
            # timeout inside this request's transaction instead. SET LOCAL
            # applies only to that transaction; 5000 milliseconds = 5 seconds.
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = 5000")
        except Exception:
            # If setup fails, close the new connection before passing the
            # original error to Flask's error handlers. Bare raise re-raises it.
            connection.close()
            raise
        g.db = connection
    return g.db


def query(sql, parameters=()):
    """Execute a read query and return its rows as a list of dictionaries.

    Supply values separately in parameters for SQL placeholders such as %s.
    A query with no matching rows returns an empty list.
    """
    # RealDictCursor exposes columns by name. The with block closes the cursor
    # afterward, while leaving the connection available for this request.
    with get_db().cursor(cursor_factory=RealDictCursor) as cursor:
        # Let the driver bind values safely instead of inserting user input
        # into the SQL string. An empty tuple means there are no parameters.
        cursor.execute(sql, parameters)
        # fetchall() loads all result rows; list endpoints should limit their
        # SQL results. Convert each row to a regular Python dictionary.
        return [dict(row) for row in cursor.fetchall()]


def close_db(error=None):
    """Close the connection during Flask cleanup, even after a failed request.

    Flask may pass an error to this callback; cleanup is the same either way.
    """
    # pop removes and returns the connection, or None if none was opened.
    connection = g.pop("db", None)
    if connection is not None:
        # Closing also ends the transaction. These reads need no commit.
        connection.close()
