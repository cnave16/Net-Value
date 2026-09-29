"""Request-scoped, read-only PostgreSQL connections; no startup writes."""

import psycopg2
from flask import current_app, g
from psycopg2.extras import RealDictCursor
from werkzeug.exceptions import ServiceUnavailable


def get_db():
    """Return this request's connection, opening a read-only connection if needed."""
    # g keeps this connection for one app context, normally a single request.
    if "db" not in g:
        url = current_app.config.get("DATABASE_URL")
        if not url:
            raise ServiceUnavailable("Database connection is not configured.")
        # This timeout limits connection establishment, not SQL execution.
        connection = psycopg2.connect(url, connect_timeout=5)
        try:
            connection.set_session(readonly=True)
            # Set this after connecting because Neon's pooler rejects startup
            # options. The 5-second limit applies to this transaction only.
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = 5000")
        except Exception:
            # Close a failed connection, then pass the same error to Flask.
            connection.close()
            raise
        g.db = connection
    return g.db


def query(sql, parameters=()):
    """Execute a read query and return its rows as a list of dictionaries.

    Supply values separately in parameters for SQL placeholders such as %s.
    A query with no matching rows returns an empty list.
    """
    # Read columns by name. This block closes the cursor, not the connection.
    with get_db().cursor(cursor_factory=RealDictCursor) as cursor:
        # Bind values separately so user input cannot become SQL instructions.
        cursor.execute(sql, parameters)
        # Load all rows as dictionaries; large lists need a LIMIT in their SQL.
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
