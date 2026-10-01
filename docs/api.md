# Net Value API contract

Base URL: `http://localhost:5001/api`. Field names use snake_case.
See [frontend setup](frontend-setup.md) for local integration steps.
This document describes current behavior; the project proposal describes the
broader target. Elias should consume `response.data.data` when using Axios.

## Response format

All implemented endpoints return JSON in the same envelope. Lists are always
arrays, including when empty. Missing data is `null`, never a made-up zero.

```json
{
  "data": [{"id": 1, "abbreviation": "BOS", "team_name": "Celtics", "city": "Boston"}],
  "meta": {},
  "error": null
}
```

On failure the HTTP status reflects the error, `data` is null, and `error`
contains a stable code and a readable message:

```json
{
  "data": null,
  "meta": {},
  "error": {"code": "BAD_REQUEST", "message": "page must be an integer."}
}
```

Codes include `BAD_REQUEST` (400), `NOT_FOUND` (404), `METHOD_NOT_ALLOWED`
(405), `REQUEST_ENTITY_TOO_LARGE` (413), `UNSUPPORTED_MEDIA_TYPE` (415),
`UNPROCESSABLE_ENTITY` (422), `NOT_IMPLEMENTED` (501), `DATABASE_UNAVAILABLE` (503 for database
driver failures), `SERVICE_UNAVAILABLE` (503 for missing configuration), and
`INTERNAL_ERROR` (500). The client should use HTTP status and code for logic,
and display the message to the user. Database and server internals are omitted.

## Working endpoints

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/health` | Process health; no database access |
| GET | `/health/db` | Runs `SELECT 1` on the configured database |
| GET | `/teams` | Teams ordered by abbreviation |
| GET | `/seasons` | Season IDs and years, newest first |
| GET | `/players` | Player search, season/team filters, pagination |
| GET | `/players/<id>` | Player details; 404 if absent |
| POST | `/projections/wins` | Estimate roster wins from one season's ratings and minutes |

`/players` accepts these query parameters:

| Parameter | Default | Rules |
| --- | --- | --- |
| `search` | empty | Case-insensitive name substring, at most 100 characters |
| `page` | 1 | Integer from 1 to 1,000,000 |
| `limit` | 20 | Integer from 1 to 100 |
| `season_id` | unset | Database ID from `/seasons`, from 1 to 2147483647 |
| `team` | unset | Three-letter abbreviation; requires `season_id` |

Example: `GET /api/players?team=BOS&season_id=1&page=1&limit=20`.
Use actual IDs from `/seasons`; the example does not assert which year ID 1 means.

```json
{
  "data": [{
    "id": 1,
    "name": "Sample Player",
    "external_id": null,
    "team": null,
    "salary": null,
    "predicted_value": null,
    "surplus": null
  }],
  "meta": {
    "page": 1, "limit": 20, "total": 1, "total_pages": 1,
    "season_id": 1, "team_filter": "BOS"
  },
  "error": null
}
```

Example data is illustrative. Results use database IDs, not external provider IDs.
`/players/<id>` returns one object of the same shape and empty metadata.
An ID of zero or above 2147483647 returns 400. A valid ID with no player returns
404. The integer URL route does not match negative or nonnumeric IDs (404).
`/teams` returns `id`, `abbreviation`, `team_name`, `city`.
`/seasons` returns `id`, `start_year`, `end_year`.

Team filtering means **played for that team in that season**, not current
roster membership. A traded player can match multiple teams in one season.
Results do not duplicate players. `team` stays null until the schema contains
authoritative current roster information. Salary, predicted value, and surplus
also remain null because the current schema/model does not supply them.
An empty or out-of-range page returns 200 with `data: []` and the true count.

## Roster win projection

Send `POST /api/projections/wins` with `Content-Type: application/json`:

```json
{
  "player_ids": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
  "season_id": 7
}
```

IDs here are examples. Use internal player IDs from `/players` and a season ID
from `/seasons`, not NBA external IDs. Both fields are required; extra fields
are rejected. IDs must be JSON integers from 1 through 2147483647. The roster
must contain 12–15 distinct players, following the model demo's input limit.
This limit does not establish NBA roster or trade legality.

The backend reads through its existing read-only database connection and sums
each player's minutes across all teams in the requested season. Every player
must exist and have a finite LEBRON rating and positive recorded minutes in
that season. Unknown players or incomplete season data return 422 with code
`UNPROCESSABLE_ENTITY` and the affected IDs. Invalid request fields return 400;
non-JSON content types return 415. Database failures use the existing 503 errors.

On success, `data` contains `projected_wins`, `team_lebron`, `top10_std`,
`positive_share`, and `top3_share`, as returned by Chase's `project_wins` function.
`meta` echoes the requested `season_id` and `player_ids`.

The estimate uses historical minutes, including minutes played for other teams.
It does not predict a new rotation, verify current team membership, price a
player, or determine trade legality. The model code and importer are unchanged;
the endpoint never calls the model's database helpers or imports the CSV.
Mocked integration tests cover this endpoint. A read-only live check on
September 29, 2026 confirmed the test database had 435 players with usable
ratings and minutes for the 2025–2026 season. A request with 12 sample players
returned HTTP 200 with the expected response fields. This verified integration,
not prediction accuracy or an actual team's roster. Repeat the check when the
database configuration, schema, or data changes.

## Reserved endpoints

`POST /valuation`, `POST /trade/validate`, and `GET /picks` always return 501
with `NOT_IMPLEMENTED`. They do not yet validate input, query assets, or perform
analysis. The frontend should show these features as unavailable.

The proposal's request formats remain design targets:

- Valuation: `player_id`, `ppg`, `rpg`, `apg`, `per`, `win_shares`, `age`.
- Trade: `team_a_sends` and `team_b_sends`, each containing `player_ids` and
  `pick_ids` arrays. Explicit participating team IDs, season, and transaction
  date still need to be agreed upon to support picks-only trades and dated rules.
- Picks: `slot`, `round`, optional `year`.

Before these become working endpoints, coordinate the following:

- Chase: the integrated model predicts roster wins from LEBRON ratings and
  historical minutes. Agree on a separate player-value or fair-market-salary
  model before implementing `/valuation`; roster wins do not supply those values.
- Vincent and Chase: current roster membership, contract years and salaries,
  draft pick ownership/protections, and data freshness fields.
- Bronson and Elias: response fields for analysis, validation failures, and
  unavailable data. A 501 response must never display as a legal or illegal trade.

## Configuration and checks

`DATABASE_URL` takes priority over `TEST_DATABASE_URL`. Connections are created
on demand, reused within a request, and closed at its end. API connections are
read-only, with a five-second connection timeout and statement timeout. No
database writes or schema changes are performed by the API.

CORS allows `http://localhost:5173` and `http://localhost:3000` by default.
Set `CORS_ORIGINS` to a comma-separated list of exact frontend origins for
other environments. Spaces around entries and empty entries are ignored.
Origins include the scheme, hostname, and port, with no path or trailing slash.
`localhost` and `127.0.0.1` are different origins. CORS controls browser access
to responses; it is not authentication. No authentication is required by this
initial public API. Request bodies are limited to 64 KiB.

Run locally and check:

```sh
curl http://localhost:5001/api/health
curl http://localhost:5001/api/health/db
curl http://localhost:5001/api/teams
curl 'http://localhost:5001/api/players?limit=5'
```

Automated tests cover response behavior, validation, bound query parameters,
pagination edge cases, database failure handling, connection cleanup, and CORS.
They mock PostgreSQL. The live projection check above verified the test database
separately; automated test success alone does not verify live connectivity.
