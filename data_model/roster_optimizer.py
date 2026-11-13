"""Knapsack-style NBA roster additions for the Net Value project.

Requires the existing local modules:
    salary_value.py  (_fetch_season_players, _compute_salary_allocations)
    project_wins.py  (project_wins)

The single-player recommendation API reads actual salaries from PostgreSQL.
Pass NBA external player IDs (strings or ints), never internal primary keys.
It evaluates each addition INDEPENDENTLY against the same original team.

This is a beam-search HEURISTIC for a nonlinear group objective, not a proof of
an exact global knapsack optimum. Available cap is an input; cap rules and
player/contract availability are intentionally not inferred here.
"""

import math
import os
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from psycopg2 import sql

import psycopg2
from dotenv import load_dotenv

from project_wins import project_wins
from salary_value import (
    NBA_GAMES,
    NBA_TEAMS,
    MIN_LEAGUE_MINUTES_COVERAGE,
    MINUTES_PER_TEAM_GAME,
    _compute_salary_allocations,
    _fetch_season_players,
)

load_dotenv()

DEFAULT_WEIGHTS = {"wins": 0.65, "salary_value": 0.25, "lebron": 0.10}
REPLACEMENT_LEBRON = -1.5
# Scales make the three score components roughly comparable. Tune with backtests.
WIN_SCALE = 5.0                 # +5 projected wins -> 1 score unit
SURPLUS_SCALE = 25_000_000.0   # +$25M total salary surplus -> 1 unit
LEBRON_SCALE = 10.0            # +10 combined above-replacement LEBRON -> 1 unit
MAX_PLAYER_MINUTES = 3_200.0  # avoid >3200 historical minutes dominating


@dataclass(frozen=True)
class _Option:
    player: object     # _PlayerSeason from salary_value.py
    actual_salary: float
    fair_salary: float
    solo_win_gain: float

    @property
    def player_id(self):
        return self.player.external_id

    @property
    def salary_surplus(self):
        return self.fair_salary - self.actual_salary


def _ids(values):
    return [str(value).strip() for value in values]


def _check_weights(weights):
    result = dict(DEFAULT_WEIGHTS if weights is None else weights)
    if set(result) != set(DEFAULT_WEIGHTS):
        raise ValueError(f"weights must have exactly these keys: {list(DEFAULT_WEIGHTS)}")
    result = {name: float(value) for name, value in result.items()}
    if any(not math.isfinite(v) or v < 0 for v in result.values()):
        raise ValueError("weights must be finite, nonnegative numbers")
    total = sum(result.values())
    if total <= 0:
        raise ValueError("at least one weight must be positive")
    return {name: value / total for name, value in result.items()}


def _project_roster_wins(players, rotation_size):
    """Project a rotation from historical minutes, then call existing model.

    A new signing competes for minutes rather than receiving extra team minutes.
    We model the highest-minutes `rotation_size` players, and rescale their
    (capped) past minutes to 19,680 regulation team-minutes per 82 games.
    This is a simple rotation assumption, *not* a fitted minutes forecaster.
    """
    rotation = sorted(
        players,
        key=lambda p: (min(p.minutes, MAX_PLAYER_MINUTES), p.lebron, p.external_id),
        reverse=True,
    )[:rotation_size]
    if not rotation:
        raise ValueError("Cannot project a team with no players")

    capped_minutes = [min(max(float(p.minutes), 0.0), MAX_PLAYER_MINUTES) for p in rotation]
    denominator = sum(capped_minutes)
    if denominator <= 0:
        raise ValueError("The selected players have no playable minutes")

    team_minutes = NBA_GAMES * MINUTES_PER_TEAM_GAME
    roster_data = [
        {
            "external_id": p.external_id,
            "lebron": float(p.lebron),
            "minutes": minutes * team_minutes / denominator,
        }
        for p, minutes in zip(rotation, capped_minutes)
    ]
    return float(project_wins(roster_data)["projected_wins"])


def _objective(options, projected_wins, baseline_wins, weights):
    win_component = (projected_wins - baseline_wins) / WIN_SCALE
    surplus_component = sum(o.salary_surplus for o in options) / SURPLUS_SCALE
    lebron_component = (
        sum(max(o.player.lebron - REPLACEMENT_LEBRON, 0.0) for o in options)
        / LEBRON_SCALE
    )
    return (
        weights["wins"] * win_component
        + weights["salary_value"] * surplus_component
        + weights["lebron"] * lebron_component
    )


def _shortlist(options, limit, single_scores):
    """Keep diverse inexpensive and strong candidates, not only high scorers."""
    if len(options) <= limit:
        return sorted(options, key=lambda o: o.player_id)

    quota = max(5, limit // 8)
    criteria = [
        lambda o: single_scores[o.player_id],
        lambda o: o.solo_win_gain,
        lambda o: o.salary_surplus,
        lambda o: o.player.lebron,
        lambda o: -o.actual_salary,
    ]
    chosen = {}
    for criterion in criteria:
        for option in sorted(options, key=criterion, reverse=True)[:quota]:
            if len(chosen) < limit:
                chosen[option.player_id] = option

    for option in sorted(options, key=lambda o: single_scores[o.player_id], reverse=True):
        if len(chosen) == limit:
            break
        chosen[option.player_id] = option

    return sorted(chosen.values(), key=lambda o: o.player_id)


def _retain_diverse_beam(states, budget, width):
    """Preserve different budget usage bands so cheap combinations survive."""
    states.sort(key=lambda s: (s[3], s[2], -s[1]), reverse=True)
    bands = [[] for _ in range(5)]
    quota = max(1, width // 5)
    selected, seen = [], set()
    for state in states:
        band = min(4, int(5 * state[1] / budget))
        if len(bands[band]) < quota:
            bands[band].append(state)
            selected.append(state)
            seen.add(state[0])
    if len(selected) < width:
        for state in states:
            if state[0] not in seen:
                selected.append(state)
                seen.add(state[0])
                if len(selected) == width:
                    break
    return selected[:width]


def _optimize_from_players(
    season_players,
    fair_salaries,
    current_roster,
    available_salary,
    actual_salaries,
    *,
    candidate_ids=None,
    max_players=5,
    exactly_five=True,
    weights=None,
    candidate_limit=80,
    beam_width=100,
    rotation_size=15,
):
    """Pure optimization core, separate from PostgreSQL for easy unit testing."""
    if not math.isfinite(float(available_salary)) or available_salary <= 0:
        raise ValueError("available_salary must be a positive dollar amount")
    budget = float(available_salary)
    if not 1 <= max_players <= 15 or not isinstance(max_players, int):
        raise ValueError("max_players must be an integer between 1 and 15")
    if not 1 <= rotation_size <= 30 or not isinstance(rotation_size, int):
        raise ValueError("rotation_size must be an integer between 1 and 30")
    if not isinstance(candidate_limit, int) or candidate_limit < max_players:
        raise ValueError("candidate_limit must be at least max_players")
    if not isinstance(beam_width, int) or beam_width < 1:
        raise ValueError("beam_width must be a positive integer")
    weights = _check_weights(weights)

    by_id = {p.external_id: p for p in season_players}
    roster_ids = set(_ids(current_roster))
    if not roster_ids:
        raise ValueError("current_roster cannot be empty")
    missing_roster = sorted(roster_ids - by_id.keys())
    if missing_roster:
        raise LookupError(
            f"No selected-season LEBRON/minutes data for roster IDs: {missing_roster}"
        )
    roster = [by_id[pid] for pid in sorted(roster_ids)]
    baseline = _project_roster_wins(roster, rotation_size)

    normalized_salaries = {}
    for player_id, salary in actual_salaries.items():
        pid = str(player_id).strip()
        amount = float(salary)
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError(f"Annual salary for {pid!r} must be positive and finite")
        normalized_salaries[pid] = amount

    requested_ids = (
        set(normalized_salaries)
        if candidate_ids is None
        else set(_ids(candidate_ids))
    ) - roster_ids
    missing_stats = sorted(requested_ids - by_id.keys())
    missing_prices = sorted((requested_ids & by_id.keys()) - normalized_salaries.keys())
    eligible_ids = requested_ids & by_id.keys() & normalized_salaries.keys()
    eligible_ids = {pid for pid in eligible_ids if normalized_salaries[pid] <= budget}

    # Score all available, priced candidates once to guide shortlist creation.
    options = []
    single_scores = {}
    for pid in sorted(eligible_ids):
        player = by_id[pid]
        projected = _project_roster_wins(roster + [player], rotation_size)
        option = _Option(
            player=player,
            actual_salary=normalized_salaries[pid],
            fair_salary=float(fair_salaries[pid]),
            solo_win_gain=projected - baseline,
        )
        options.append(option)
        single_scores[pid] = _objective([option], projected, baseline, weights)

    pool = _shortlist(options, candidate_limit, single_scores)

    # State = (indices in sorted pool, dollars spent, team wins, objective score).
    root = ((), 0.0, baseline, 0.0)
    beam = [root]
    best_by_size = {0: root}
    for depth in range(1, max_players + 1):
        states = []
        for picks, spent, _, _ in beam:
            start_idx = picks[-1] + 1 if picks else 0
            for idx in range(start_idx, len(pool)):
                cost = spent + pool[idx].actual_salary
                if cost > budget + 1e-7:
                    continue
                new_picks = picks + (idx,)
                choices = [pool[j] for j in new_picks]
                new_wins = _project_roster_wins(
                    roster + [option.player for option in choices], rotation_size
                )
                score = _objective(choices, new_wins, baseline, weights)
                states.append((new_picks, cost, new_wins, score))
        if not states:
            break
        best_by_size[depth] = max(states, key=lambda s: (s[3], s[2], -s[1]))
        beam = _retain_diverse_beam(states, budget, beam_width)

    # Guarantee a feasible solution for every possible cardinality, even if
    # beam pruning misses all complete combinations. The k cheapest players
    # give the minimum possible cost of signing k players in the shortlist.
    cheapest_indices = sorted(range(len(pool)), key=lambda i: pool[i].actual_salary)
    for count in range(1, min(max_players, len(pool)) + 1):
        indices = tuple(sorted(cheapest_indices[:count]))
        subset = [pool[i] for i in indices]
        cost = sum(o.actual_salary for o in subset)
        if cost > budget + 1e-7:
            break
        projected = _project_roster_wins(
            roster + [option.player for option in subset], rotation_size
        )
        fallback = (indices, cost, projected, _objective(subset, projected, baseline, weights))
        prior = best_by_size.get(count)
        if prior is None or (fallback[3], fallback[2], -fallback[1]) > (prior[3], prior[2], -prior[1]):
            best_by_size[count] = fallback

    if exactly_five:
        # If five affordable additions are impossible, give the best feasible
        # group at the highest attainable cardinality, and report that fact.
        chosen_state = best_by_size[max(best_by_size)]
    else:
        chosen_state = max(
            best_by_size.values(), key=lambda s: (s[3], s[2], -s[1])
        )

    picks, total_cost, new_wins, score = chosen_state
    chosen = [pool[j] for j in picks]
    # Give intuitive attribution: marginal wins as each pick is added in this
    # deterministic order. Marginal gains sum exactly to the group's gain.
    chosen.sort(key=lambda o: (o.solo_win_gain, single_scores[o.player_id]), reverse=True)
    incremental_roster = list(roster)
    previous_wins = baseline
    selected = []
    for option in chosen:
        incremental_roster.append(option.player)
        next_wins = _project_roster_wins(incremental_roster, rotation_size)
        selected.append({
            "player_id": option.player_id,
            "player_name": option.player.name,
            "lebron": option.player.lebron,
            "historical_minutes": option.player.minutes,
            "actual_salary": round(option.actual_salary),
            "fair_salary": round(option.fair_salary),
            "salary_surplus": round(option.salary_surplus),
            "solo_win_gain": round(option.solo_win_gain, 3),
            "marginal_win_gain": round(next_wins - previous_wins, 3),
        })
        previous_wins = next_wins

    return {
        "selected_players": selected,
        "baseline_projected_wins": round(baseline, 3),
        "new_projected_wins": round(new_wins, 3),
        "projected_win_gain": round(new_wins - baseline, 3),
        "total_salary": round(total_cost),
        "remaining_salary": round(budget - total_cost),
        "total_fair_salary": round(sum(o.fair_salary for o in chosen)),
        "total_salary_surplus": round(sum(o.salary_surplus for o in chosen)),
        "objective_score": round(score, 5),
        "five_player_target_met": len(chosen) == max_players,
        "eligible_candidate_count": len(options),
        "searched_candidate_count": len(pool),
        "missing_stats_ids": missing_stats,
        "missing_salary_ids": missing_prices,
        "method": "budget-aware beam search; not guaranteed global optimum",
        "weights": weights,
    }


def recommend_best_additions(
    current_roster,
    available_salary,
    actual_salaries,
    *,
    candidate_ids=None,
    season_end_year=2026,
    max_players=5,
    exactly_five=True,
    weights=None,
    candidate_limit=80,
    beam_width=100,
    rotation_size=15,
    database_url=None,
):
    """Find a strong group of five player additions within an annual budget.

    current_roster: iterable of NBA *external* IDs (existing model helpers)
    available_salary: max TOTAL annual salary dollars available for all additions
    actual_salaries: mapping {NBA external ID: actual annual salary dollars}
    candidate_ids: optional eligible/acquirable IDs; if omitted, all priced IDs
                   are considered (NOT automatically confirmed free agents)
    season_end_year: completed historical statistics season, e.g. 2026
    exactly_five: prioritize five signings if feasible; otherwise optimize
                  up to max_players, including choosing none if beneficial
    weights: optional weights for 'wins', 'salary_value', 'lebron' (normalized)

    Fair salaries computed in ONE database pass using salary_value.py logic.
    """
    url = database_url or os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("Set TEST_DATABASE_URL or DATABASE_URL, or pass database_url")

    with closing(psycopg2.connect(url)) as connection:
        with connection.cursor() as cursor:
            year, players = _fetch_season_players(cursor, season_end_year)

    expected_minutes = NBA_TEAMS * NBA_GAMES * MINUTES_PER_TEAM_GAME
    observed_minutes = sum(player.minutes for player in players)
    if observed_minutes < expected_minutes * MIN_LEAGUE_MINUTES_COVERAGE:
        raise ValueError(
            f"Season {year} is incomplete for fair-salary modeling "
            f"({observed_minutes / expected_minutes:.1%} minutes coverage)."
        )

    fair_salaries = _compute_salary_allocations(players)
    result = _optimize_from_players(
        players,
        fair_salaries,
        current_roster,
        available_salary,
        actual_salaries,
        candidate_ids=candidate_ids,
        max_players=max_players,
        exactly_five=exactly_five,
        weights=weights,
        candidate_limit=candidate_limit,
        beam_width=beam_width,
        rotation_size=rotation_size,
    )
    result["stats_season_end_year"] = year
    return result


# -----------------------------------------------------------------------------
# DATABASE SALARY READER
# -----------------------------------------------------------------------------
# These are supported naming conventions, not assertions about the user's schema.
# If another source exists, pass salary_table and salary_column explicitly.
_SALARY_TABLE_PRIORITY = (
    "player_salaries", "player_contracts", "salaries", "contracts",
    "player_season_salaries", "player_team_seasons", "player_seasons", "players",
)
_SALARY_COLUMN_PRIORITY = (
    "annual_salary", "annual_salary_usd", "salary", "salary_usd",
    "salary_amount", "contract_salary", "base_salary", "cap_hit",
    # Your DB has a season-scoped contract_value on player_seasons.
    # Verify that its values are annual amounts before treating them as salaries.
    "contract_value",
)


def _salary_year(value):
    """Normalize salary season notation to an ending year, e.g. 2026-27 -> 2027."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    v = str(value).strip().replace("/", "-")
    if len(v) == 4 and v.isdecimal():
        return int(v)
    if "-" in v:
        first, last = v.split("-", 1)
        if first.isdecimal() and last.isdecimal() and len(first) == 4:
            first, last = int(first), int(last)
            if last < 100:
                last += (first // 100) * 100
            if last == first + 1:
                return last
    return None


def _annual_salary_dollars(value):
    """Convert a DB salary to USD without guessing units such as 'millions'."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = float(str(value).strip().replace("$", "").replace(",", ""))
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(amount) or amount <= 0:
        return None
    return round(amount)


def _pick_salary_source(cursor, salary_table=None, salary_column=None):
    """Use information_schema to identify a real annual-salary field.

    Supports salary tables keyed by external_id, player_id, player_season_id,
    or player_team_season_id. Raises instead of selecting an unrelated column.
    """
    cursor.execute("""
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = ANY(current_schemas(false))
    """)
    tables = {}
    for schema, table, column in cursor.fetchall():
        tables.setdefault((schema, table), set()).add(column)

    options = []
    for (schema, table), columns in tables.items():
        if salary_table is not None and table != salary_table:
            continue
        if salary_table is None and table not in _SALARY_TABLE_PRIORITY:
            continue
        amount_field = (
            salary_column if salary_column in columns else None
        ) if salary_column is not None else next(
            (c for c in _SALARY_COLUMN_PRIORITY if c in columns), None
        )
        if amount_field is None:
            continue
        key_field = next((k for k in (
            "external_id", "player_id", "player_season_id",
            "player_team_season_id") if k in columns), None)
        if key_field is None:
            continue
        # Prefer explicitly season-scoped sources over generic contracts.
        scoped = any(c in columns for c in (
            "season_id", "season_end_year", "end_year", "start_year",
            "season", "year", "contract_start_date", "contract_end_date",
            "start_date", "end_date",
        )) or key_field in ("player_season_id", "player_team_season_id") or table in (
            "player_seasons", "player_team_seasons")
        priority = (_SALARY_TABLE_PRIORITY.index(table)
                    if table in _SALARY_TABLE_PRIORITY else 100)
        options.append(((0 if scoped else 1, priority),
                        (schema, table, amount_field, key_field, columns)))

    if not options:
        available = [f"{schema}.{table}: {', '.join(sorted(cols))}"
                     for (schema, table), cols in sorted(tables.items())
                     if any("salar" in col or "contract" in col or "cap_hit" in col
                            for col in cols)]
        raise LookupError(
            "No supported actual-salary column was found in PostgreSQL. "
            "Specify salary_table='YOUR_TABLE' and salary_column='YOUR_COLUMN' "
            "if the salary data uses different names. Salary-like columns: "
            + (" | ".join(available[:10]) if available else "none discovered")
        )
    options.sort(key=lambda option: option[0])
    return options[0][1]


def _fetch_db_actual_salaries(cursor, salary_season_end_year=2027,
                              *, salary_table=None, salary_column=None):
    """Return ({NBA_external_id: annual USD}, metadata) using an existing table.

    Uses the salary season's end year, separately from the LEBRON stats season.
    If only a timeless salary snapshot exists, metadata marks its year unverified.
    Duplicated salaries are accepted only if identical; conflicts are excluded.
    """
    (schema, table, value_col, key_col, columns) = _pick_salary_source(
        cursor, salary_table=salary_table, salary_column=salary_column
    )
    t = sql.Identifier(schema, table)
    col = lambda name: sql.Identifier(name)
    q = sql.SQL
    from_expr = q("{} AS t").format(t)
    joins = []
    # Resolve all sources to the NBA's external player ID. Internal player_id
    # values must never leak into the optimizer's player lookup.
    if key_col == "external_id":
        player_ref = q("t.external_id::text")
    elif key_col == "player_id":
        joins.append(q("JOIN players p ON p.player_id = t.player_id"))
        player_ref = q("p.external_id::text")
    elif key_col == "player_season_id":
        joins.extend([
            q("JOIN player_seasons ps ON ps.player_season_id = t.player_season_id"),
            q("JOIN players p ON p.player_id = ps.player_id"),
        ])
        player_ref = q("p.external_id::text")
    else:  # player_team_season_id
        joins.extend([
            q("JOIN player_team_seasons pts "
              "ON pts.player_team_season_id = t.player_team_season_id"),
            q("JOIN player_seasons ps ON ps.player_season_id = pts.player_season_id"),
            q("JOIN players p ON p.player_id = ps.player_id"),
        ])
        player_ref = q("p.external_id::text")

    # Some salary columns live on player_seasons/player_team_seasons themselves.
    # There can be a season_id in the salary source or its linked player-season.
    if "season_id" in columns:
        season_ref = q("t.season_id")
    elif key_col in ("player_season_id", "player_team_season_id"):
        season_ref = q("ps.season_id")
    elif table == "player_seasons" and "season_id" in columns:
        season_ref = q("t.season_id")
    else:
        season_ref = None

    year_type = "snapshot_without_year"
    year_expr = q("NULL")
    parameters = []
    where = []
    if season_ref is not None:
        joins.append(q("JOIN seasons s ON s.season_id = {}")
                     .format(season_ref))
        where.append(q("s.end_year = %s"))
        parameters.append(salary_season_end_year)
        year_type = "season_id"
    elif "season_end_year" in columns or "end_year" in columns:
        ycol = "season_end_year" if "season_end_year" in columns else "end_year"
        where.append(q("t.{} = %s").format(col(ycol)))
        parameters.append(salary_season_end_year)
        year_type = ycol
    elif "start_year" in columns:
        where.append(q("t.start_year = %s"))
        parameters.append(salary_season_end_year - 1)
        year_type = "start_year"
    elif "year" in columns:
        # `year` is assumed to represent the season-ending calendar year.
        where.append(q("t.year = %s"))
        parameters.append(salary_season_end_year)
        year_type = "year_as_end_year"
    elif "season" in columns:
        # Read as text and normalize 2027 / 2026-27 below.
        year_expr = q("t.season::text")
        year_type = "season"
    elif ("contract_start_date" in columns or "start_date" in columns) and (
            "contract_end_date" in columns or "end_date" in columns):
        start = "contract_start_date" if "contract_start_date" in columns else "start_date"
        end = "contract_end_date" if "contract_end_date" in columns else "end_date"
        # Oct 1 is inside the contract year for NBA seasons, but cannot verify
        # trades/contracts that change midseason. Treat as one-time snapshot.
        active_date = date(salary_season_end_year - 1, 10, 1)
        where.append(q("(t.{} IS NULL OR t.{} <= %s)")
                     .format(col(start), col(start)))
        where.append(q("(t.{} IS NULL OR t.{} >= %s)")
                     .format(col(end), col(end)))
        parameters.extend([active_date, active_date])
        year_type = "active_contract_on_oct_1"

    statement = q("SELECT {}, t.{}, {} FROM {} {}").format(
        player_ref, col(value_col), year_expr,
        from_expr, q(" ").join(joins))
    if where:
        statement += q(" WHERE ") + q(" AND ").join(where)
    cursor.execute(statement, parameters)
    raw_rows = cursor.fetchall()
    salaries, conflicting = {}, set()
    no_valid_salary = 0
    for external_id, amount, year_label in raw_rows:
        if year_type == "season" and _salary_year(year_label) != salary_season_end_year:
            continue
        pid = str(external_id).strip() if external_id is not None else ""
        dollars = _annual_salary_dollars(amount)
        if not pid or dollars is None:
            no_valid_salary += 1
            continue
        if pid in salaries and salaries[pid] != dollars:
            conflicting.add(pid)
        else:
            salaries[pid] = dollars
    for pid in conflicting:
        salaries.pop(pid, None)
    if not salaries:
        raise LookupError(
            f"No valid annual player salaries were found for season ending "
            f"{salary_season_end_year} in {schema}.{table}.{value_col}. "
            "Verify the salary season and schema/column selection."
        )
    return salaries, {
        "source": "PostgreSQL",
        "salary_table": f"{schema}.{table}",
        "salary_column": value_col,
        "salary_season_end_year": salary_season_end_year,
        "season_filter": year_type,
        "year_verified": year_type != "snapshot_without_year",
        "matched_player_count": len(salaries),
        "conflicting_salary_ids": sorted(conflicting),
        "invalid_salary_rows": no_valid_salary,
        # Column name alone cannot establish annual-vs-multiyear semantics.
        "annual_salary_unverified": value_col == "contract_value",
    }


def _rank_single_players_from_data(
    players, fair_salaries, current_roster, available_salary, actual_salaries,
    *, candidate_ids=None, top_n=5, weights=None, rotation_size=15,
):
    """Pure calculation. Every candidate is considered ALONE, not with peers."""
    budget = float(available_salary)
    if not math.isfinite(budget) or budget < 0:
        raise ValueError("available_salary must be nonnegative and finite")
    if not isinstance(top_n, int) or top_n < 1:
        raise ValueError("top_n must be a positive integer")
    if not isinstance(rotation_size, int) or not 1 <= rotation_size <= 30:
        raise ValueError("rotation_size must be an integer between 1 and 30")
    weights = _check_weights(weights)
    by_id = {p.external_id: p for p in players}
    roster_ids = set(_ids(current_roster))
    if not roster_ids:
        raise ValueError("current_roster cannot be empty")
    missing_roster = sorted(roster_ids - set(by_id))
    if missing_roster:
        raise LookupError(f"No stats found for roster player IDs {missing_roster}")
    current_players = [by_id[pid] for pid in sorted(roster_ids)]
    baseline = _project_roster_wins(current_players, rotation_size)

    requested = (set(by_id) - roster_ids if candidate_ids is None
                 else set(_ids(candidate_ids)) - roster_ids)
    missing_stats_ids = sorted(requested - set(by_id))
    eligible_ids = requested & set(by_id)
    normalized_prices = {}
    for pid, amount in actual_salaries.items():
        price = _annual_salary_dollars(amount)
        if price is not None:
            normalized_prices[str(pid).strip()] = price
    missing_salary_ids = sorted(eligible_ids - set(normalized_prices))

    recommendations, unaffordable = [], []
    for pid in sorted(eligible_ids & set(normalized_prices)):
        player = by_id[pid]
        salary = normalized_prices[pid]
        if salary > budget:
            unaffordable.append({
                "player_id": pid, "player_name": player.name,
                "actual_salary": salary, "salary_over_budget": round(salary - budget),
            })
            continue
        solo_wins = _project_roster_wins(current_players + [player], rotation_size)
        wins_added = solo_wins - baseline
        fair_salary = fair_salaries[pid]
        salary_surplus = fair_salary - salary
        objective = (
            weights["wins"] * wins_added / WIN_SCALE
            + weights["salary_value"] * salary_surplus / SURPLUS_SCALE
            + weights["lebron"] * max(player.lebron - REPLACEMENT_LEBRON, 0) / LEBRON_SCALE
        )
        recommendations.append({
            "player_id": pid,
            "player_name": player.name,
            "lebron": float(player.lebron),
            "historical_minutes": float(player.minutes),
            "actual_salary": salary,
            "estimated_fair_salary": round(fair_salary),
            "salary_surplus": round(salary_surplus),
            "baseline_projected_wins": round(baseline, 3),
            "new_projected_wins": round(solo_wins, 3),
            "wins_added": round(wins_added, 3),
            "remaining_salary_if_selected": round(budget - salary),
            "score": round(objective, 6),
            "fits_budget": True,
        })
    recommendations.sort(
        key=lambda p: (-p["score"], -p["wins_added"], p["actual_salary"], p["player_id"])
    )
    return {
        "recommendations": recommendations[:top_n],
        "baseline_projected_wins": round(baseline, 3),
        "available_salary": round(budget),
        "affordable_candidate_count": len(recommendations),
        "over_budget_candidate_count": len(unaffordable),
        "over_budget_examples": unaffordable[:10],
        "missing_salary_ids": missing_salary_ids,
        "missing_stats_ids": missing_stats_ids,
        "weights": weights,
        "independent_scenarios": True,
    }


def recommend_single_players(
    current_roster, available_salary, *, candidate_ids=None,
    season_end_year=2026, salary_season_end_year=2027,
    top_n=5, weights=None, rotation_size=15,
    database_url=None, salary_table=None, salary_column=None,
):
    """Return top-five INDEPENDENT single-player recommendations.

    Reads *actual salaries* from your database; NEVER uses synthetic salaries
    or public salary websites. Baseline roster is unchanged across alternatives.

    current_roster: NBA EXTERNAL player IDs, e.g. ["203999", "1628983", ...]
    available_salary: maximum annual salary dollars FOR ONE ADDITION.
    candidate_ids: optional list of externally acquired/available player IDs;
                   None scores every non-roster player with a stored salary.
    season_end_year: LEBRON season end year, e.g. 2026 for 2025-26 stats.
    salary_season_end_year: salary year end, e.g. 2027 for 2026-27 salaries.
    salary_table/salary_column: if necessary, identify your schema explicitly.

    Recommendations have individual projected wins and win gains; do not sum
    the gains as if the five choices were simultaneously acquired.
    """
    url = database_url or os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("Set TEST_DATABASE_URL / DATABASE_URL or pass database_url")
    with closing(psycopg2.connect(url)) as connection:
        with connection.cursor() as cursor:
            stats_year, players = _fetch_season_players(cursor, season_end_year)
            actual_salaries, salary_metadata = _fetch_db_actual_salaries(
                cursor, salary_season_end_year,
                salary_table=salary_table, salary_column=salary_column,
            )
    expected_minutes = NBA_TEAMS * NBA_GAMES * MINUTES_PER_TEAM_GAME
    observed_minutes = sum(p.minutes for p in players)
    if observed_minutes < expected_minutes * MIN_LEAGUE_MINUTES_COVERAGE:
        raise ValueError(
            f"Stats season {stats_year} incomplete for valuation "
            f"({observed_minutes / expected_minutes:.1%} minutes coverage)"
        )
    fair_salaries = _compute_salary_allocations(players)
    result = _rank_single_players_from_data(
        players, fair_salaries, current_roster, available_salary, actual_salaries,
        candidate_ids=candidate_ids, top_n=top_n, weights=weights,
        rotation_size=rotation_size,
    )
    result["stats_season_end_year"] = stats_year
    result["salary_data"] = salary_metadata
    return result


def apply_single_recommendation(current_roster, available_salary, recommendation):
    """After you CHOOSE a recommendation, return (new_roster_ids, new_budget).

    This is only an in-memory roster simulation, not a transaction or signing.
    """
    roster = _ids(current_roster)
    player_id = str(recommendation["player_id"]).strip()
    salary = _annual_salary_dollars(recommendation["actual_salary"])
    budget = float(available_salary)
    if salary is None or not math.isfinite(budget) or budget < salary:
        raise ValueError("Selected player salary is invalid or over budget")
    if player_id in roster:
        raise ValueError("Selected player is already on the roster")
    return roster + [player_id], round(budget - salary)


def main():
    """Example: run `python roster_optimizer.py` after copying this file over it."""
    from model_functions import get_team_id

    team = "PHI"
    stats_season_end_year = 2026       # 2025-26 LEBRON
    salary_season_end_year = 2026      # 2025-26 salaries on player_seasons
                                        # Set 2027 only if your DB has 2026-27 rows
    available_salary = 45_000_000     # Budget already computed elsewhere

    database_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("Missing TEST_DATABASE_URL or DATABASE_URL")
    team_id = get_team_id(team)
    if team_id is None:
        raise LookupError(f"Team not found: {team}")

    # Team lookup respects the requested stats season, unlike the old helper
    # that could return records across all historical seasons.
    with closing(psycopg2.connect(database_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT p.external_id
                FROM players p
                JOIN player_seasons ps ON ps.player_id = p.player_id
                JOIN seasons s ON s.season_id = ps.season_id
                JOIN player_team_seasons pts
                  ON pts.player_season_id = ps.player_season_id
                WHERE pts.team_id = %s AND s.end_year = %s
                  AND ps.lebron IS NOT NULL
                  AND pts.minutes_played > 0
                  AND p.external_id IS NOT NULL
            """, (team_id, stats_season_end_year))
            current_roster = [str(row[0]).strip() for row in cursor.fetchall()]
    if not current_roster:
        raise LookupError(f"No roster found for {team} in {stats_season_end_year}")

    result = recommend_single_players(
        current_roster=current_roster,
        available_salary=available_salary,
        season_end_year=stats_season_end_year,
        salary_season_end_year=salary_season_end_year,
        candidate_ids=None,  # Every non-roster player with stats and DB salary
        top_n=5,
        database_url=database_url,
        salary_table="player_seasons",
        salary_column="contract_value",
    )

    print(f"\nNET VALUE — TOP 5 INDEPENDENT OPTIONS FOR {team}")
    print("Each scenario adds ONE player to the SAME starting roster")
    print(f"Salary source: {result['salary_data']['salary_table']}."
          f"{result['salary_data']['salary_column']}")
    print(f"Salary season checked: {salary_season_end_year - 1}-{str(salary_season_end_year)[-2:]}")
    if not result["salary_data"]["year_verified"]:
        print("WARNING: Salary table is an unversioned snapshot; check its year")
    if result["salary_data"].get("annual_salary_unverified"):
        print("NOTE: contract_value is treated as annual pay; verify this column")
        print("      is not a multi-year contract total before using recommendations")
    print("WARNING: Database salary does not establish trade/free-agent availability")
    print(f"Available salary: ${available_salary:,.0f}")
    print(f"Original projected wins: {result['baseline_projected_wins']:.2f}")
    print(f"Affordable players with complete data: {result['affordable_candidate_count']}")
    print(f"Over budget: {result['over_budget_candidate_count']}")
    print(f"Missing salary: {len(result['missing_salary_ids'])}")
    for index, player in enumerate(result["recommendations"], 1):
        print(
            f"{index}. {player['player_name']} (ID {player['player_id']})"
            f" | LEBRON {player['lebron']:+.2f}"
            f" | actual salary ${player['actual_salary']:,.0f}"
            f" | fair ${player['estimated_fair_salary']:,.0f}"
            f" | projected wins {player['new_projected_wins']:.2f}"
            f" | wins added {player['wins_added']:+.2f}"
            f" | budget remaining ${player['remaining_salary_if_selected']:,.0f}"
        )
    if not result["recommendations"]:
        print("No individually affordable candidates with usable stats and salary")
    return result


if __name__ == "__main__":
    main()
