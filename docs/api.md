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
| GET | `/trade/teams/<id>?season_id=<id>` | Commissioner roster, win percentage, and top 15 addition targets |
| POST | `/trade/analyze` | Compare all participating teams before and after directed player and pick transfers |
| POST | `/trade/validate` | Alias for `/trade/analyze`, with the same request and response |

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
    "team": "BOS",
    "salary": 30348000.0,
    "predicted_value": 57736350.0,
    "surplus": 27388350.0,
    "contract_type": "standard"
  }],
  "meta": {
    "page": 1, "limit": 20, "total": 1, "total_pages": 1,
    "season_id": 1, "team_filter": "BOS"
  },
  "error": null
}
```

Example data is illustrative. Results use database IDs, not external provider IDs.
`/players/<id>` returns one object of the same shape, plus a `seasons` list,
and empty metadata. Seasons are newest first and contain `season_id`,
`start_year`, `end_year`, `teams`, `games_played`, `minutes_played`, `lebron`,
`offensive_lebron`, and `defensive_lebron`. Games and minutes are summed across
team stints. Team abbreviations are ordered by minutes descending, then
alphabetically for ties. Ratings and minutes are JSON numbers; missing stats
remain null. A season without team stints has `teams: []`; a player without
season records has `seasons: []`. These teams describe historical membership.
An ID of zero or above 2147483647 returns 400. A valid ID with no player returns
404. The integer URL route does not match negative or nonnumeric IDs (404).
`/teams` returns `id`, `abbreviation`, `team_name`, `city`.
`/seasons` returns `id`, `start_year`, `end_year`.

By default the list includes only players on a 2026–27 roster (a row in
`player_contracts`); `roster=all` also returns free agents and other players kept
for historical stats and the models. Any other `roster` value returns 400, and
`meta.roster` echoes the filter. `sort` orders the list: `name` (default),
`best_value` (largest surplus first), `worst_value` (most negative first), or
`salary` (highest first). The value sorts rank players with at least
`meta.min_ranked_games` (41) games in the stats season first, since fair value
grows with minutes and an injury-shortened season would otherwise read as a bad
contract; `meta.ranked_count` says how many qualified. Players without the sort
field come last. `/players/<id>` and `/valuation` work for every
player either way.

Team filtering means **played for that team in that season**, not current
roster membership. A traded player can match multiple teams in one season.
Results do not duplicate players. `team`, `salary`, `predicted_value`, `surplus`,
and `contract_type` have the same meaning as in [`POST /valuation`](#valuation);
`team` is the 2026–27 contract team, or null without a contract.
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

## Multi-team trade simulator

See [the trade contract](trades.md) for complete requests, responses, and rule
coverage. The commissioner dashboard at `GET /trade/teams/<id>?season_id=<id>`
returns player details, baseline wins/win percentage, and up to 15 targets ranked
by Chase's weighted wins/salary-surplus/LEBRON score for independent additions.
An optional `available_salary` query parameter filters by maximum annual incoming
salary in dollars. Omit it for no limit; zero is explicit. This does not establish
trade legality. Responses add `available_salary` (decimal string or null) and
`over_budget_candidate_count`. Over-cap teams can still receive targets. Existing
win fields retain the trade simulator's projection basis; `ranking_projected_wins`
contains Chase's normalized-rotation estimates used in scoring. Added fields
include `score`, `estimated_fair_salary`, and `salary_surplus` per target, plus
`ranking_weights`, `budget_filter_applied`, `recommendation_status`,
`recommendation_reason`, and `ranking_excluded_roster_ids` on the dashboard.
See the trade contract for missing-data behavior and ranking metadata.

Both trade POST routes require `season_id`, `team_ids`, and `transfers`. Each
transfer supplies `player_id`, `from_team_id`, and `to_team_id`. The old
`team_a_*` / `team_b_*` payload is no longer accepted. The general format supports
2–30 teams, up to 100 distinct player transfers, and optional `pick_transfers`
(up to 100). At least one player or pick must move; every team must participate.

Analysis returns each team's before/after roster IDs, wins, win percentages,
payroll, estimated cap space, and legality checks. Percentages use 0–100;
differences are percentage points. Rosters and cap salaries come from
`player_contracts` (2026–27 contracts; see [trades.md](trades.md)). A payroll
total is null when any listed salary is unknown. Cap estimates include the
source's dead money but not cap holds or exceptions, and always use the supplied
**2026–27** cap/apron figures. `salary_cap.minimum_team_salary` is informational. `season_id` selects
the source data snapshot, not the trade season: older ratings can feed the
upcoming-season model. Responses expose `meta.data_season_id` and
`meta.trade_season: {"start_year": 2026, "end_year": 2027}`. Existing requests
with `season_id: 1` need no changes. Players without ratings and minutes in the
data season (`has_stats: false`, e.g. rookies) count toward payroll but not wins.

`legality.passes_supported_rules` reports the outcome of implemented roster,
salary-matching, and apron checks. `legality.is_legal` remains null because full
NBA eligibility cannot be established from the available data. A salary-rule
failure still returns projections; failed ownership checks set
`analysis_available: false`. Missing model inputs return 422.

The dashboard and simulation do not persist a commissioner choice or execute
roster changes.

## Valuation

`POST /valuation` with `{"player_id": 95}` (a database ID; nothing else) returns:

```json
{
  "data": {
    "player_id": 95, "salary": 30348000.0, "predicted_value": 57736350.0,
    "surplus": 27388350.0, "contract_type": "standard"
  },
  "meta": {
    "fair_value_basis": "league_cap_budget_by_lebron_above_replacement_times_minutes",
    "stats_season_end_year": 2026,
    "salary_season": {"start_year": 2026, "end_year": 2027},
    "salary_source": "player_contracts.cap_salary"
  },
  "error": null
}
```

- `predicted_value` is Chase's fair annual salary (`data_model/salary_value.py`):
  the league's cap budget split by LEBRON above replacement times minutes in the
  latest complete stats season, with a minimum salary floor and a 35%-of-cap
  ceiling (`value_basis: "stats"`). A player from the last two draft classes
  without stats gets their draft slot's expected value for their current career
  year instead (year 1 for this year's rookies, year 2 for last year's;
  `value_basis: "draft_slot"`, `draft_pick`; see [Draft picks](#draft-picks)).
  Otherwise it is null. Valuations are cached in the API process for 10 minutes.
- `salary` is the 2026–27 cap salary. It is null for two-way contracts (their
  pay is not listed), for standard contracts the source has not priced yet,
  and for players without a contract (`contract_type: null`).
- `surplus` is `predicted_value - salary`, null when either is missing.
- `at_value_ceiling` is true when `predicted_value` is the model's $57.7M
  ceiling (35% of the cap, about the max salary); `uncapped_value` is then the
  same model's estimate without the ceiling (otherwise null). `surplus` always
  uses the capped value, since no team can pay more than the max.
- `value_missing_reason` explains a null `predicted_value`: `no_recent_stats`
  (the player isn't in the model's stats season: missed it or barely played)
  or `model_unavailable` (no complete stats season loaded); otherwise null.

A nonexistent player returns 404; a malformed body returns 400.

## Draft picks

`GET /picks` returns all 60 slots; `slot` (1–60) or `round` (1–2) filter them.
`year` returns 400: values are per slot, and projecting a specific future draft
(team records, lottery odds) is not supported yet. Each slot has:

- `expected_value_by_season` and `expected_value_per_season`: Chase's fair values
  for past picks at that slot in career years 1–4 (round 1) or 1–2 (round 2),
  smoothed across nearby slots and made non-increasing by slot.
- `typical_value_per_season`: the same, using the kernel-weighted median
  (what most players at the slot turn into) instead of the mean.
- `salary_by_season` and `salary_per_season`: what this year's pick at the slot
  is paid over the same seasons; `rookie_salary` is the first season.
  `salary_is_estimate` is true when any season is interpolated from neighboring
  slots (an unsigned pick, or a deal shorter than the valued seasons).
- `surplus_per_season` and `typical_surplus_per_season` (value minus salary per
  season), `contract_seasons`, `round`, and `current_draftee` (`player_id`, `name`).

`meta` gives the stats season, the draft classes used, the sample size, and the
`assumptions` (`data_model/draft_value.py`), with `confirmed` and `under_review`
lists naming which settings are settled. Missing draft or stats
data returns 422. Future ownership is separate from these slot valuations;
see [future draft-pick trading](#future-draft-pick-trading) for resolved ownership
and the limits on protection checks.

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

### Future draft-pick trading

`GET /api/trade/teams/<team_id>/picks` lists resolved future ownership (2027–2033),
without estimated values. This is distinct from the existing `/api/picks` slot
valuation endpoint.

`POST /api/trade/analyze` and `/api/trade/validate` accept optional `pick_transfers`
with `draft_year`, `round`, `original_team_id`, `from_team_id`, and `to_team_id`.
`transfers` remains required but may be empty when picks move. Responses add
`incoming_picks`/`outgoing_picks` to each team and ownership, horizon, and Stepien
checks to legality. Unknown protection outcomes and missing restriction history
require review. See [trade documentation](trades.md#future-draft-picks) for the
payload, rules, limits, and additive database deployment procedure.
