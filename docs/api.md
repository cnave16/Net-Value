# Net Value API contract

This is the implemented first-week contract for Bronson's backend work.
Base URL: `http://localhost:5000/api`. Field names use snake_case.
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
(405), `NOT_IMPLEMENTED` (501), `DATABASE_UNAVAILABLE` (503 for database
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

`/players` accepts these query parameters:

| Parameter | Default | Rules |
| --- | --- | --- |
| `search` | empty | Case-insensitive name substring, at most 100 characters |
| `page` | 1 | Integer from 1 to 1,000,000 |
| `limit` | 20 | Integer from 1 to 100 |
| `season_id` | unset | Positive ID from `/seasons` |
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
`/teams` returns `id`, `abbreviation`, `team_name`, `city`.
`/seasons` returns `id`, `start_year`, `end_year`.

Team filtering means **played for that team in that season**, not current
roster membership. A traded player can match multiple teams in one season.
Results do not duplicate players. `team` stays null until the schema contains
authoritative current roster information. Salary, predicted value, and surplus
also remain null because the current schema/model does not supply them.
An empty or out-of-range page returns 200 with `data: []` and the true count.

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

- Chase: model inputs, output units, trained model interface, and whether the
  first model predicts wins, player value, or fair-market salary. These are
  distinct quantities in the proposal and should not be treated as interchangeable.
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
other environments. No authentication is required by this initial public API.

Run locally and check:

```sh
curl http://localhost:5000/api/health
curl http://localhost:5000/api/health/db
curl http://localhost:5000/api/teams
curl 'http://localhost:5000/api/players?limit=5'
```

Automated tests cover response behavior, validation, bound query parameters,
pagination edge cases, database failure handling, connection cleanup, and CORS.
They mock PostgreSQL; a live development-database smoke check is also needed
to verify schema compatibility and deployed connectivity.
