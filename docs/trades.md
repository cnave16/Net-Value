# Two-team trade analysis

This endpoint exchanges players between two historical season rosters and
compares each team's projected wins before and after. It never updates roster
records or executes a real trade. Payroll calculations are ready for salary
integration, but actual salary mapping and incoming estimates are unavailable.

## Request

Use `POST /api/trade/analyze`. `POST /api/trade/validate` is an alias returning
the same analysis and checks. Both endpoints require JSON:

```json
{
  "season_id": 1,
  "team_a_id": 1,
  "team_b_id": 2,
  "team_a_sends": {"player_ids": [1]},
  "team_b_sends": {"player_ids": [2]}
}
```

Use internal IDs from `/teams`, `/seasons`, and `/players`, not NBA external IDs.
Each sends object may also contain `"pick_ids": []` for compatibility with the
planned frontend shape. Nonempty picks, cash, extra fields, and client-provided
salaries are rejected rather than silently ignored. IDs must be positive JSON
integers up to 2147483647; booleans and strings are rejected.

The teams must differ, players cannot repeat within or across packages, and at
least one player must move. One side may send an empty player array; this is
a supported simulation, not a statement that a player-only one-way transaction
satisfies all NBA rules. A package can contain at most 100 players as an input
size limit, not an NBA roster rule.

Elias's existing `validateTrade` helper currently sends only the two packages.
It will need `season_id`, `team_a_id`, and `team_b_id` added before it can call
these endpoints. No frontend files were changed for this feature.

## Response

The usual `{data, meta, error}` envelope is unchanged. On a successful simulation:

- `data.analysis_available` is true.
- `data.teams` contains two entries, in team A / team B order.
- Each entry includes `team_id`, `abbreviation`, `name`, `roster_before`,
  `roster_after`, `outgoing_player_ids`, and `incoming_player_ids`.
- `projected_wins` contains `before`, `after`, and `net_difference` (after minus
  before). Positive means an increase in estimated wins; negative means a loss.
- `payroll` contains `before`, `after`, `net_difference`, `currency`, `basis`,
  and lists of players whose actual or estimated salaries are missing.
- `legality` reports `status`, `is_legal`, `checks`, and `not_checked`.
- `meta` identifies the season, historical roster source, minutes basis, and
  warnings about the simulation's limits.

For example, one team's result has this shape (illustrative numbers):

```json
{
  "team_id": 1,
  "abbreviation": "LAL",
  "name": "Los Angeles Lakers",
  "roster_before": [1, 3, 5],
  "roster_after": [2, 3, 5],
  "outgoing_player_ids": [1],
  "incoming_player_ids": [2],
  "projected_wins": {"before": 40.5, "after": 42.0, "net_difference": 1.5},
  "payroll": {
    "currency": "USD",
    "basis": "actual_retained_plus_estimated_incoming",
    "before": null,
    "after": null,
    "net_difference": null,
    "missing_actual_before": [1, 3, 5],
    "missing_actual_after": [3, 5],
    "missing_estimated_after": [2]
  }
}
```

The full response includes both teams and their complete roster ID lists.
Dollar totals will be decimal strings with two places, not floating-point
numbers; unavailable values are JSON null. Never display null as zero.

## Historical rosters and minutes

`backend/services/trade_data.py` owns roster loading. It includes every player
with a membership record for the team in the selected season. Statistics use
each player's full-season minutes across all teams, matching the standalone
roster projection endpoint's data basis. Those minutes and LEBRON ratings stay
fixed when the player moves. This does not predict a new rotation or reproduce
the original team's exact distribution of minutes.

Some historical rosters overlap because a player appeared for both teams in one
season. This version blocks the simulation and lists the shared player IDs;
it does not guess which team currently owns that player or count them twice.
Chase's current-roster function can replace the loader later. It should return
the same internal IDs and roster records, with matching season statistics, and
the route's `roster_source` metadata must be updated with it.

Missing/nonfinite LEBRON ratings or missing/negative/nonfinite minutes block
projection rather than silently dropping players. Zero-minute players are
allowed if the full roster still has positive minutes. Each before/after roster
must be nonempty. Historical lists may exceed 15 players, so the standalone
projection endpoint's 12–15 input limit is not imposed on this simulation.
These are model/data checks, not official roster-size eligibility rules.

Win estimates use Chase's existing function unchanged, including its 0–82
clamp. Differences are calculated from unrounded model outputs. The model is
nonlinear: one team's improvement does not have to equal the other's loss.

## Payroll basis and Vincent's integration

Before the trade, add the actual annual salaries of all players on that team's
starting roster. After the trade, add actual salaries of retained players and
estimated salaries of incoming players. Outgoing players are removed. Then
calculate `after - before` when both totals are available.

This is a custom projected payroll comparison. An estimate does not replace a
player's real contract or determine cap space. Salary-cap restrictions are not
implemented. No league cap, tax, dead money, bonuses, or cap holds are included.

The test database has `player_seasons.contract_value`, but its meaning has not
been confirmed. The loader deliberately sets actual salary to None until the
team confirms the source, units, and season. A new database column is not needed
for this feature, and no schema files were changed.

Once confirmed, map actual annual USD salaries into each loader record's
`actual_salary`. Vincent's estimates should be supplied by
`load_estimated_salaries(player_ids, season_id)` as a dictionary keyed by internal
player ID. It currently returns None for each incoming player. Estimates should
be for the selected season and in USD, using Decimal values or decimal strings.

An incomplete total is null, not a partial sum. Each side reports the exact IDs
missing actual salaries before/after or incoming estimates after. Missing
payroll values do not block win projections. Invalid or negative salary values
are treated as unavailable; a known zero is valid. If a missing actual salary
belongs only to an outgoing player, a complete after total can still be shown.

## Legality and errors

Basic request validation checks team/ID formats, duplicate players, and supported
assets. The returned legality section checks disjoint starting rosters and that
outgoing players belong to the loaded historical roster. These are simulation
consistency checks, not a complete NBA contract-eligibility check.

If roster checks fail, HTTP 200 returns `analysis_available: false`, `teams: []`,
and `legality.status: "failed"` with the affected IDs. Otherwise the status is
`"incomplete"`. **`legality.is_legal` is always null in this version**, including
failed historical-roster checks, because current NBA legality is not established.

Malformed requests return 400; non-JSON requests return 415. Unknown teams or
season return 404. Missing team roster data or unusable model inputs return 422.
Database failures use the existing 503 response. Error responses use the usual
error envelope; they do not return partial predictions.

The official [NBA–NBPA CBA](https://nbpa.com/cba) contains date- and
contract-dependent provisions in Article VII, Section 8 and Article XXIV.
The current schema lacks the inputs to evaluate them accurately. This version
does not invent blanket signing waits, no-trade-clause rules, or roster limits.

## To do

- Replace historical membership with Chase's authoritative current rosters.
- Confirm actual annual salary mapping and connect Vincent's incoming estimates.
- Add **salary matching, salary-cap restrictions, apron/tax checks**, and required
  actual-contract data. Keep those calculations separate from estimated payroll.
- Add dated contract restrictions, player consent, trade deadlines, and contract
  types after obtaining the necessary data and verifying each applicable rule.
- Add roster-size eligibility checks with the correct date and contract context.
- Add picks, protections, ownership, cash, and additional teams in later versions.
- Connect Elias's trade UI and add team/season IDs to its API helper.

## Try it locally

Start Flask on port 5001. These IDs worked in the development database check;
use IDs from your database if it differs:

```sh
curl -sS http://localhost:5001/api/trade/analyze \
  -H "Content-Type: application/json" \
  -d '{"season_id":1,"team_a_id":1,"team_b_id":2,"team_a_sends":{"player_ids":[1]},"team_b_sends":{"player_ids":[2]}}'
```

The read-only check exchanged one player each between historical LAL and LAC
rosters. It returned HTTP 200 with both win comparisons and null payroll fields.
This verifies integration, not NBA legality or prediction accuracy.
