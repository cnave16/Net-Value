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
selects the source data snapshot for ratings and minutes. Rosters and salaries
always come from 2026–27 contracts. It does not select the trade season or cap rules. Existing
requests with `season_id: 1` continue to work using 2026–27 limits. Responses
identify both `meta.data_season_id` and `meta.trade_season` (2026–2027);
`meta.season_id` remains an alias for the source data ID.
The response's `data` contains:

- `team_id`, `abbreviation`, `name`, and `roster` with player details.
- `projected_wins` and `projected_win_percentage` for the selected roster.
- `payroll` and `salary_cap`, using the same comparison objects as trades, with
  identical before/after values because no trade has occurred.
- `targets`: up to 15 independent additions ranked with Chase's weighted score
  (65% wins, 25% salary surplus, 10% LEBRON impact after component scaling).
  No outgoing players or trade-legality filter is applied. A maximum incoming
  salary can optionally filter candidates before selecting the top 15.
- `eligible_target_count` and `skipped_targets` with IDs and reasons for unusable
  stats, NBA IDs, fair values, or positive actual salaries. Fewer than 15 results
  are possible. Two-way zero cap hits are not treated as annual salary.

Each target has `player`, `team_id`, `team_ids`, `projected_wins`, and
`projected_win_percentage`. The projection objects contain `before`, `after`,
and `net_difference`. Targets are players under a 2026–27 contract with stats
in the selected data season; `team_id` is their contract team and `team_ids`
is `[team_id]`. Free agents are not targets.

Player details include `player_id`, `name`, `external_id`, `lebron`,
`offensive_lebron`, `defensive_lebron`, `minutes`, `actual_salary` (2026–27 cap
salary), `contract_type` (`standard` or `two_way`), and `has_stats`.
Unavailable optional details are null. Existing roster members are excluded
from targets. Chase's tie order is score, ranking wins added, lower actual salary,
then NBA ID. Negative or zero gains remain visible if they rank in the top 15.
Recommendations do not establish affordability or trade legality; evaluate the
actual outgoing/incoming package with the trade simulator.

Each target also has `score`, `estimated_fair_salary`, `salary_surplus`, and
`ranking_projected_wins` (`before`, `after`, `net_difference`). Chase's score
uses the top 15 players by capped historical minutes, rescaled to 19,680 team
minutes. Existing `projected_wins` and percentage fields keep the simulator's
fixed historical minutes for display consistency. Their order need not follow
those displayed gains. The two projection bases are explicit in metadata.

Fair values are calculated across the whole selected stats season, including
players without current contracts, using the API's configured read-only database
connection. Candidate salaries come directly from `player_contracts.cap_salary`.
Internal player IDs remain unchanged in API responses; NBA IDs are used only
inside the model. The optimizer's standalone database/salary discovery is not used.

Omit `available_salary` to keep recommendations unfiltered, even when payroll is
unknown or the team is over the cap. To filter, request for example
`GET /api/trade/teams/20?season_id=1&available_salary=10000000`.
This is a maximum annual salary for one incoming player, not total team payroll
or a trade-legality determination. Values must be nonnegative plain dollar
amounts (up to 12 integer digits and two decimal places); duplicate, empty,
negative, nonfinite, and malformed values return 400. Zero is an explicit zero
budget; omit the parameter to clear it. Salaries are compared with exact cents.
`budget_filter_applied` indicates whether a limit was supplied, `available_salary`
is a decimal dollar string or null, and `over_budget_candidate_count` counts
otherwise eligible candidates removed by the limit. The UI's per-team Apply
and Clear controls only change target recommendations, not the selected trade.
Budgets are local to the page session and are not included in shared trade URLs. `ranking_weights` exposes Chase's weights. `recommendation_status` is
`available` or `unavailable`, with `recommendation_reason` when unavailable.
Insufficient league minutes (below the model's 90% coverage threshold) or missing
NBA IDs on usable roster members returns an empty target list, never the old
wins-only ranking. Roster members without usable stats remain in payroll and are
listed in `ranking_excluded_roster_ids`.

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
    "basis": "player_contracts_cap_salary",
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
    "other_cap_charges_confirmed": true,
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

## Rosters and salaries

Rosters and cap salaries come from the `player_contracts` and `team_cap_sheets`
tables, loaded by `database_config/load_contracts.py` from Basketball-Reference's
team contract pages. Each page lists the players under contract and their
salary for 2026–27, so every player belongs to exactly one team. Rerun the
loader to refresh (it replaces the season's rows in one transaction):

```sh
python database_config/load_contracts.py --dry-run   # parse and match only
python database_config/load_contracts.py
```

- **Matching.** Contract players are matched to `players` by normalized name
  (case, accents, punctuation, and Jr./II/III ignored, plus `NAME_ALIASES` for
  nicknames such as Ron/Ronald Holland); the load stops if a name matches more
  than one player. Unmatched players, mostly rookies, get a new `players` row;
  `load_nba_ids.py` then fills their NBA IDs from Wikidata and reports any
  player whose ID already belongs to another row, i.e. a missed match that
  needs an alias.
- **Later seasons.** `later_salaries` holds the next three seasons' salaries
  (null where none is listed); the draft model uses them for rookie contracts.
- **Two-way contracts** count as zero against the cap (`cap_salary = 0`,
  `contract_type = 'two_way'`). A blank salary is treated as two-way only when
  the source's payroll note says so.
- **Unknown salaries.** A standard contract the source has not priced yet has a
  null `cap_salary`, so that team's payroll total is null rather than understated.
- **Dead money.** `other_cap_charges` is the source's team payroll total minus
  the listed players' salaries (waived players and similar charges), and
  `other_cap_charges_confirmed` is true. Cap holds, exceptions, incentives, and
  distinct apron salary calculations are not included.
- **Players without stats.** Ratings and minutes still come from the selected
  data season. Players with no rating or minutes there (`has_stats: false`)
  count toward payroll but are left out of win projections; the model does not
  invent a rating for them.

The cap adapter always uses `TRADE_SEASON_START_YEAR = 2026`, independently of
which database season supplies the model inputs. The user-supplied settings are
a $164,961,000 cap, $148,465,000 minimum team salary, $209,015,000 first apron,
and $221,686,000 second apron. `salary_cap.minimum_team_salary` is information;
minimum-payroll compliance is not a trade restriction.

The model uses fixed full-season minutes across all team stints and Chase's
unchanged win calculation. It does not predict a new rotation. Tied minutes
are consistently ordered by player ID. Every before/after roster must have
positive total minutes among players with stats.

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

A November 16, 2026 load stored 526 contracts for all 30 teams (88 two-way;
142 new player rows). 24 teams had every salary listed; six standard contracts
had no salary on the source yet, so those teams' payroll totals are null.

Before presenting results as current NBA legality, add the contract,
exception, cap-accounting, roster, and date inputs listed in `not_checked`.
