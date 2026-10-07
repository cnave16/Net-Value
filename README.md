# Net-Value
Net Value is developed by University of Missouri-Columbia students Bronson Juette, Chase Nave, Elias Nelson, and Vincent Dawson as their capstone project. Net Value seeks to help educate NBA front offices and fans alike in the areas concerning roster construction.

## Backend development

The initial backend uses Flask and the existing psycopg2 PostgreSQL driver.
Python 3.9 or newer is required. Run these commands from the repository root:

```sh
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements-dev.txt
```

If you do not already have a `.env`, copy `.env.example` to `.env` and replace
the database placeholders before starting Flask. Do not overwrite an existing
`.env`. On Windows PowerShell, activate the environment with
`.\venv\Scripts\Activate.ps1` instead of `source venv/bin/activate`.

Set `TEST_DATABASE_URL` in `.env` to the team's Neon development database.
An explicit `DATABASE_URL` takes precedence (useful for deployment).
The API never automatically selects `PROD_DATABASE_URL`.
Keep `.env` private; `.env.example` contains placeholders only.

```sh
python -m flask --app backend run --port 5001
```

Check `http://localhost:5001/api/health` for app availability and
`http://localhost:5001/api/health/db` for a read-only connection check.
The latter does not verify that tables or data have been loaded.
If port 5001 is occupied, use `--port 5002` and update the frontend API URL.
Port 5000 can conflict with macOS AirPlay. Keep the terminal running while
using the API; press Control+C to stop it.

The API expects the tables defined in `database_config/databasesetup.py`.
It does not create tables or import data at startup. Coordinate database setup
and ingestion with the team. The existing standalone
`testdatabaseconnection.py` checks both test and production; use the API's
database health endpoint to check only the API's configured database.

```sh
python -m pytest -q
```

Tests use mocked database connections and do not require network access.
See [the API contract](docs/api.md) for endpoints, examples, and integration gaps.
For React setup and a first end-to-end request, see the
[frontend handoff](docs/frontend-setup.md).

## Frontend development

Elias's React app lives in `frontend/`. In a second terminal, with Node.js
22.12 or newer installed, run `npm ci` and `npm run dev` from that folder.
It defaults to sample data. Set `VITE_USE_MOCK=false` in `frontend/.env.local`
and restart Vite to connect to Flask on port 5001 through the `/api` proxy.
Player search and details are available; draft and trade screens are placeholders.

Run `npm run lint` and `npm run build` from `frontend/` to check frontend changes.

## What is ready

- Team and season lists, player search with pagination, and player details.
- Roster win projections using an explicit season and 12–15 distinct players.
- Two-team historical trade simulations with before/after wins and net differences.
- Consistent JSON responses, input validation, and database error handling.

Player valuation and draft pick endpoints are placeholders that return HTTP
501. Trade analysis performs basic roster checks, not full NBA legality checks.
Salary, current team, and player-value fields are not
populated yet. Historical team membership must not be treated as a current roster.

See [trade analysis](docs/trades.md) for a request example, payroll assumptions,
and the remaining legality work. No salary-cap restrictions are enforced yet.

## Win projections and player data

`POST /api/projections/wins` accepts 12–15 internal player IDs and one season ID.
The backend reads that season's ratings and minutes through its configured
read-only connection, then calls Chase's `project_wins` calculation. It estimates
roster wins; it does not calculate player salary values or validate trades.

`player_data/2025-2026.csv` contains the season's player ratings, minutes, and
team records. The standalone `database_config/enterdata.py` importer inserts or
updates those records in the database selected by `PROD_DATABASE_URL`. It writes
to production, unlike the API's test-database fallback, and is not run by the API.
The standalone model demo uses `TEST_DATABASE_URL`; the API calls only its
calculation function and uses the API's own database settings.

| Component | Database configuration | Writes data? |
| --- | --- | --- |
| Flask API | `DATABASE_URL`, falling back to `TEST_DATABASE_URL` | No |
| `databasesetup.py` | `TEST_DATABASE_URL` | Creates missing tables and indexes |
| `enterdata.py` | `PROD_DATABASE_URL` | Inserts or updates CSV records |
| `project_wins.py` standalone demo | `TEST_DATABASE_URL` | No |
| `testdatabaseconnection.py` | Both test and production URLs | No |

Running Flask does not run any of these standalone scripts. The importer needs
the existing schema and its own production variable; `.env.example` intentionally
contains only what a frontend/backend developer needs for the API. Importing
data is a separate team maintenance task, not a normal frontend setup step.
The CSV importer currently requires team wins and losses to total 82, so it
does not support in-progress season records. `CREATE TABLE IF NOT EXISTS`
does not migrate existing tables to a new schema.

A read-only test-database check on September 29, 2026 found 435 players with
usable ratings and minutes and successfully exercised the projection endpoint.
No import was needed for that check.

## Structure

```text
backend/
  __init__.py          Flask factory, configuration, CORS, error handling
  database.py          Read-only PostgreSQL connection lifecycle and queries
  responses.py         Shared JSON response format
  routes/
    health.py          App and database health checks
    catalog.py         Players, teams, seasons
    pending.py         Reserved valuation and pick routes
    projections.py     Roster win estimates using Chase's calculation
    trades.py          Two-team trade request validation and response
  services/
    trade_data.py      Historical roster and future salary adapters
    trades.py          Roster exchange, limited checks, and payroll calculations
frontend/
  src/                React pages, components, and shared API client
  vite.config.js      Development proxy to Flask on port 5001
data_model/
  project_wins.py      Chase's roster win calculation and standalone demo
database_config/
  databasesetup.py     Test database table and index setup
  enterdata.py         CSV importer targeting PROD_DATABASE_URL
  testdatabaseconnection.py  Standalone test and production connection checks
player_data/
  2025-2026.csv        Player/team records used by the importer
docs/
  api.md              Endpoint and response contract
  frontend-setup.md   React setup and integration walkthrough
  trades.md           Trade request, calculations, limitations, and next steps
tests/                Backend tests
```

The project proposal mentions SQLAlchemy; this first increment reuses psycopg2
already present in the repository. Database access is isolated in `database.py`
to keep a later transition manageable. The current queries target PostgreSQL,
not SQLite. The development server is for local use; production deployment and
a production WSGI server remain a later milestone.
