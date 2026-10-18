# Multi-team trade simulator

The backend supplies a commissioner dashboard and simulates simultaneous player
transfers between 2–30 teams for the upcoming **2026–27 season only**. There is one general trade format; the old
`team_a_*` / `team_b_*` format is removed. No frontend files are changed.
All endpoints are read-only and use the usual `{data, meta, error}` envelope.

## Commissioner dashboard

Get team and season IDs from `GET /api/teams` and `GET /api/seasons`, then call:

```http
GET /api/trade/teams/10?season_id=1
```

Use internal database IDs, not NBA external IDs. `season_id` is required and
selects the source data snapshot (ratings, minutes, and the provisional roster
and salary records). It does not select the trade season or cap rules. Existing
requests with `season_id: 1` continue to work using 2026–27 limits. Responses
identify both `meta.data_season_id` and `meta.trade_season` (2026–2027);
`meta.season_id` remains an alias for the source data ID.
The response's `data` contains:

- `team_id`, `abbreviation`, `name`, and `roster` with player details.
- `projected_wins` and `projected_win_percentage` for the selected roster.
- `payroll` and `salary_cap`, using the same comparison objects as trades, with
  identical before/after values because no trade has occurred.
- `targets`: up to 15 players ranked by the win-percentage gain from adding each
  player individually, without removing anyone or filtering for trade legality.
- `eligible_target_count` and `skipped_targets` with IDs and reasons for unusable
  projection data. Fewer than 15 results are possible.

Each target has `player`, `team_id`, `team_ids`, `projected_wins`, and
`projected_win_percentage`. The projection objects contain `before`, `after`,
and `net_difference`. A target's `team_ids` describes historical membership;
`team_id` is null when that membership does not identify exactly one team.
Such players can still be ranked as hypothetical additions. Do not guess their
current owner when constructing a trade.

Player details include `player_id`, `name`, `external_id`, `lebron`,
`offensive_lebron`, `defensive_lebron`, `minutes`, and `actual_salary`.
Unavailable optional details are null. Existing roster members are excluded
from targets. Ties are broken by player ID. Negative or zero gains remain visible
if they rank in the top 15; this model does not guarantee that adding a player
improves a roster. Missing target salaries do not prevent win ranking.

Percentages are **0–100**, calculated as `projected_wins / 82 * 100`.
Percentage differences are percentage points, not relative percent changes.

## Trade request

`POST /api/trade/analyze` and `POST /api/trade/validate` accept the same JSON and
return the same analysis. Example three-team cycle:

```json
{
  "season_id": 1,
  "team_ids": [10, 20, 30],
  "transfers": [
    {"player_id": 1, "from_team_id": 10, "to_team_id": 20},
    {"player_id": 13, "from_team_id": 20, "to_team_id": 30},
    {"player_id": 25, "from_team_id": 30, "to_team_id": 10}
  ]
}
```

These IDs are illustrative. Each player moves once, from their starting roster
to one distinct participating team. A team can send players to several teams,
receive from several teams, or only send/receive. Every listed team must take
part. Players cannot be routed through an intermediate team within one request.

Team IDs must be distinct. All IDs must be JSON integers from 1 to 2147483647;
strings and booleans are rejected. Requests accept 1–100 transfers as a work
limit, not an NBA roster rule. Extra fields, picks, cash, and client-supplied
salary/cap overrides are rejected. The general format also supports a trade
with two participants; there is no separate two-team option or service.

## Trade response

`data.analysis_available` means roster projections could be computed, **not**
that the trade is legal. `data.teams` follows the input team order. Each entry
contains identity fields, `roster_before`/`roster_after` player-ID lists,
`outgoing_player_ids`, `incoming_player_ids`, projected wins and win percentage
comparison objects, `payroll`, and `salary_cap`.

For example, the financial fields can look like this:

```json
{
  "payroll": {
    "currency": "USD",
    "basis": "contract_value_assumed_annual_usd",
    "before": "150000000.00",
    "after": "155000000.00",
    "net_difference": "5000000.00",
    "missing_actual_before": [],
    "missing_actual_after": []
  },
  "salary_cap": {
    "currency": "USD",
    "basis": "cap_minus_payroll_and_supplied_other_charges",
    "is_estimate": true,
    "limit": "164961000.00",
    "minimum_team_salary": "148465000.00",
    "first_apron": "209015000.00",
    "second_apron": "221686000.00",
    "other_cap_charges": "0.00",
    "other_cap_charges_confirmed": false,
    "before": "14961000.00",
    "after": "9961000.00",
    "net_difference": "-5000000.00"
  }
}
```

`salary_cap.before`/`after` mean estimated **space under the cap**; the league's
cap limit itself does not change in a trade. Negative space means over the cap.
It does not automatically make a trade illegal. Differences always mean after
minus before. Dollar values are decimal strings with two places. Incomplete
totals are null, never partial sums or zero.

## Salary and roster assumptions

For this increment, `player_seasons.contract_value` is provisionally treated as
annual USD salary, as requested. Actual contract salary follows the player;
estimated market values are never substituted for salary matching. The mapping
is isolated in `backend/services/trade_data.py` for later replacement.
`to_jsonb(ps)->>'contract_value'` also supports older databases without that
column: salary is null instead of a query failure. No schema migration is needed.

The cap adapter always uses `TRADE_SEASON_START_YEAR = 2026`, independently of
which database season supplies the model inputs. No 2026–27 database season row
is required just to apply these limits, and existing season records are not
relabelled. The API does not accept a trade-season override.

The user-supplied settings are a $164,961,000 cap, $148,465,000 minimum team
salary, $209,015,000 first apron, and $221,686,000 second apron. The response
exposes `salary_cap.minimum_team_salary` as information; minimum-payroll
compliance is not implemented as a trade restriction.

Historical ratings can be inputs to the upcoming-season estimate, but this
does not turn historical roster or salary records into confirmed 2026–27 data.
Those adapters still need authoritative upcoming-season membership and salaries.

Cap space and matching currently use roster salaries with zero additional
charges. This is an explicit **roster-only estimate**: cap holds, dead money,
incentives, and other cap/apron adjustments are not in the database adapter.
The adapter can later supply `other_cap_charges`; a complete implementation also
needs distinct cap and apron salary calculations.

Rosters still use historical season membership, not an authoritative current
roster feed. The new model helper on main also reads historical membership and
cannot resolve current ownership. A player shared by participating rosters
blocks the simulation instead of being counted twice. Replacing the roster
adapter requires replacing candidate ownership and source metadata too.

The model uses fixed full-season minutes across all team stints and Chase's
unchanged win calculation. It does not predict a new rotation. Tied minutes
are consistently ordered by player ID. Every before/after roster must have
finite ratings, nonnegative minutes, and positive total minutes. Historical
rosters can exceed 15 players; their counts cannot prove NBA roster legality.

## Legality function

`backend/services/trade_legality.py:check_trade` runs for every simulation.
It checks disjoint rosters and outgoing ownership, then evaluates each team's
cap room or ordinary simultaneous salary matching. Post-trade apron position
controls expanded matching and the allowance. Above the second apron, it
searches for matches using separate outgoing contracts rather than rejecting
all trades with multiple outgoing players. Search exhaustion returns unknown.

Rules follow Article VII, Sections 2(e) and 6(j) of the
[2023 NBA–NBPA CBA](https://nbpa.com/cba). The
[NBA's CBA guide](https://cms.nba.com/wp-content/uploads/sites/4/2024/11/2024-25-CBA-101.pdf)
provides a matching overview. The active 2026–27 cap and apron figures were
supplied by the user; older settings retained in the code are not selected by
the trade API.

The checker supports cap room plus the applicable allowance, the expanded
simultaneous exception below the first apron, no salary increase above the
first apron, and nonaggregated matching above the second apron. It evaluates
one combined matching package per team below the second apron; it does not
optimize arbitrary combinations of exceptions or prior trade exceptions.

Read these fields in `data.legality`:

- `checks`: codes, team IDs, `passed` (true/false/null), messages, and matching
  amounts where available. Null means the check could not be evaluated.
- `passes_supported_rules`: false for any failure, null if required inputs are
  missing, true only if every supported check passes under the stated assumptions.
- `status`: `failed` for a supported-rule failure; otherwise `incomplete`.
- `is_legal`: null because provisional data and missing rules do not establish
  full NBA approval, even when a supported check fails.
- `not_checked`: explicit gaps including authoritative ownership, contract
  restrictions/consent, existing hard caps, exceptions, dates, and roster types.

Salary failures retain projections. Ownership failures return HTTP 200 with
`analysis_available: false` and `teams: []`. Bad request shapes return 400;
non-JSON bodies return 415; missing teams/seasons return 404; missing roster or
projection inputs return 422; database failures return 503. Never label an
incomplete result “legal.”

## Verification and remaining integration

Run `venv/bin/python -m pytest -q` (or your activated environment's Python).
Tests cover cycles, multiple destinations, conservation, ordering, target ranking,
missing data, matching boundaries, apron crossings, and API validation.

An October 16, 2026 read-only check of the configured database returned a
21-player historical roster and 15 targets for season 1 (2025–26). Four roster
players had missing contract values, so payroll/cap totals correctly stayed
null. This confirms the query integration, not current roster accuracy.

Before presenting results as current NBA legality, connect authoritative dated
rosters, fill salary gaps, confirm annual contract units, and add the contract,
exception, cap-accounting, roster, and date inputs listed in `not_checked`.
