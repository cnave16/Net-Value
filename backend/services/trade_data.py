"""Read current rosters and cap salaries, joined to the selected season's ratings."""

from decimal import Decimal

from werkzeug.exceptions import NotFound, UnprocessableEntity

from ..database import query
from .trade_finances import SEASON_RULES, TRADE_SEASON_START_YEAR, dollar, money


def load_trade_rosters(team_ids, season_id):
    """Read participating rosters from 2026-27 contracts in one database snapshot.

    Ratings and minutes come from the selected data season. Players without a
    usable rating and minutes there (rookies, players who missed the season) are
    marked has_stats=False: they count toward payroll but not win projections.
    """
    rows = query(
        """
        WITH season_stats AS (
            SELECT ps.player_id, ps.lebron, ps.offensive_lebron, ps.defensive_lebron,
                   SUM(pts.minutes_played) AS minutes
            FROM player_seasons ps
            LEFT JOIN player_team_seasons pts
                ON pts.player_season_id = ps.player_season_id
            WHERE ps.season_id = %s
            GROUP BY ps.player_season_id
        )
        SELECT t.team_id, t.abbreviation, t.team_name,
               s.season_id AS matched_season_id,
               cs.source_total_salary,
               p.player_id, p.first_name || ' ' || p.last_name AS name,
               p.external_id, st.lebron, st.offensive_lebron, st.defensive_lebron,
               st.minutes, c.cap_salary AS actual_salary, c.contract_type
        FROM teams t
        LEFT JOIN seasons s ON s.season_id = %s
        LEFT JOIN team_cap_sheets cs
            ON cs.team_id = t.team_id AND cs.season_start_year = %s
        LEFT JOIN player_contracts c
            ON c.team_id = t.team_id AND c.season_start_year = %s
        LEFT JOIN players p ON p.player_id = c.player_id
        LEFT JOIN season_stats st ON st.player_id = c.player_id
        WHERE t.team_id = ANY(%s)
        ORDER BY t.team_id, p.player_id
        """,
        (season_id, season_id, TRADE_SEASON_START_YEAR, TRADE_SEASON_START_YEAR, team_ids),
    )
    missing = sorted(set(team_ids) - {row["team_id"] for row in rows})
    if missing:
        raise NotFound(f"Teams not found: {missing}.")
    if any(row["matched_season_id"] is None for row in rows):
        raise NotFound("Season not found.")

    teams = {}
    for row in rows:
        team = teams.setdefault(row["team_id"], {
            "id": row["team_id"], "abbreviation": row["abbreviation"],
            "name": row["team_name"], "players": [],
            "source_total_salary": row.get("source_total_salary"),
        })
        if row["player_id"] is not None:
            team["players"].append({
                "player_id": row["player_id"], "name": row["name"],
                "lebron": row["lebron"], "minutes": row["minutes"],
                "external_id": row.get("external_id"),
                "offensive_lebron": row.get("offensive_lebron"),
                "defensive_lebron": row.get("defensive_lebron"),
                "has_stats": row["lebron"] is not None and row["minutes"] is not None,
                # Cap salary for 2026-27; two-way contracts count as zero, null is unknown.
                "actual_salary": row.get("actual_salary"),
                "contract_type": row.get("contract_type"),
            })
    empty = [team_id for team_id in team_ids if not teams[team_id]["players"]]
    if empty:
        raise UnprocessableEntity(
            f"No {TRADE_SEASON_START_YEAR}-{str(TRADE_SEASON_START_YEAR + 1)[-2:]} contracts "
            f"loaded for teams: {empty}. Run database_config/load_contracts.py."
        )
    return teams


def load_target_candidates(season_id):
    """Players under a current contract with stats in the selected season, once each."""
    return query(
        """
        SELECT p.player_id, p.external_id,
               p.first_name || ' ' || p.last_name AS name,
               ps.lebron, ps.offensive_lebron, ps.defensive_lebron,
               c.cap_salary AS actual_salary, c.contract_type,
               SUM(pts.minutes_played) AS minutes,
               ARRAY[c.team_id] AS team_ids
        FROM player_seasons ps
        JOIN players p ON p.player_id = ps.player_id
        JOIN player_contracts c
            ON c.player_id = p.player_id AND c.season_start_year = %s
        LEFT JOIN player_team_seasons pts ON pts.player_season_id = ps.player_season_id
        WHERE ps.season_id = %s
        GROUP BY p.player_id, ps.player_season_id, c.team_id, c.cap_salary, c.contract_type
        ORDER BY p.player_id
        """,
        (TRADE_SEASON_START_YEAR, season_id),
    )


def other_cap_charges(team):
    """Source payroll total minus listed salaries: dead money and similar charges."""
    total = money(team.get("source_total_salary"))
    if total is None:
        return None
    listed = sum((money(p.get("actual_salary")) or Decimal("0") for p in team["players"]), Decimal("0"))
    # Unlisted salaries are missing from both sides, so they do not distort this.
    return max(total - listed, Decimal("0"))


def load_cap_context(team_ids, teams=None):
    """Use upcoming-season limits even when projections use older player data.

    With loaded teams, each team's dead money from its cap sheet is included.
    Without a cap sheet, charges are an explicit, unconfirmed zero.
    """
    rules = SEASON_RULES[TRADE_SEASON_START_YEAR]
    context = {}
    for team_id in team_ids:
        charges = other_cap_charges(teams[team_id]) if teams and team_id in teams else None
        context[team_id] = {
            **rules,
            "other_cap_charges": dollar(charges) if charges is not None else "0.00",
            "charges_confirmed": charges is not None,
        }
    return context
