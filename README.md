# Net-Value
Net Value is developed by University of Missouri-Columbia students Bronson Juette, Chase Nave, Elias Nelson, and Vincent Dawson as their capstone project. Net Value seeks to help educate NBA front offices and fans alike in the areas concerning roster construction.

## Backend development

The initial backend uses Flask and the existing psycopg2 PostgreSQL driver.
Python 3.9 or newer is required. Run these commands from the repository root:

```sh
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements-dev.txt
# Only if you do not already have a .env file:
cp -n .env.example .env
python -m flask --app backend run --port 5001
```

Set `TEST_DATABASE_URL` in `.env` to the team's Neon development database.
An explicit `DATABASE_URL` takes precedence (useful for deployment).
The API never automatically selects `PROD_DATABASE_URL`.
Keep `.env` private; `.env.example` contains placeholders only.

Check `http://localhost:5001/api/health` for app availability and
`http://localhost:5001/api/health/db` for a read-only connection check.
The latter does not verify that tables or data have been loaded.
If port 5001 is occupied, use `--port 5000` and update the frontend API URL.

The API expects the tables defined in `database_config/databasesetup.py`.
It does not create tables or import data at startup. Coordinate database setup
and ingestion with Chase and Vincent. The existing standalone
`testdatabaseconnection.py` checks both test and production; use the API's
database health endpoint for a development-only check.

```sh
python -m pytest -q
```

Tests use mocked database connections and do not require network access.
See [the API contract](docs/api.md) for endpoints, examples, and integration gaps.

## Structure

```text
backend/
  __init__.py          Flask factory, configuration, CORS, error handling
  database.py          Read-only PostgreSQL connection lifecycle and queries
  responses.py         Shared JSON response format
  routes/
    health.py          App and database health checks
    catalog.py         Players, teams, seasons
    pending.py         Reserved valuation, trade, and pick routes
database_config/      Existing database setup scripts
docs/api.md           Frontend/backend contract
tests/                Backend tests
```

The project proposal mentions SQLAlchemy; this first increment reuses psycopg2
already present in the repository. Database access is isolated in `database.py`
to keep a later transition manageable. The current queries target PostgreSQL,
not SQLite. The development server is for local use; production deployment and
a production WSGI server remain a later milestone.
