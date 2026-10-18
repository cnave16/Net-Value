"""Read historical rosters, target candidates, and provisional contract salaries."""

from werkzeug.exceptions import NotFound, UnprocessableEntity

from ..database import query
from .trade_finances import SEASON_RULES, TRADE_SEASON_START_YEAR


def load_trade_rosters(team_ids, season_id):
    """Read all participating rosters and season data in one database snapshot."""
    rows = query(
        """
        WITH season_players AS (
            SELECT ps.player_id, ps.lebron, ps.offensive_lebron, ps.defensive_lebron,
                   to_jsonb(ps)->>'contract_value' AS actual_salary,
                   SUM(pts.minutes_played) AS minutes,
                   ARRAY_AGG(pts.team_id) AS team_ids
            FROM player_seasons ps
            LEFT JOIN player_team_seasons pts
                ON pts.player_season_id = ps.player_season_id
            WHERE ps.season_id = %s
            GROUP BY ps.player_season_id
        )
        SELECT t.team_id, t.abbreviation, t.team_name,
               s.season_id AS matched_season_id,
               p.player_id, p.first_name || ' ' || p.last_name AS name,
               p.external_id, sp.lebron, sp.offensive_lebron, sp.defensive_lebron,
               sp.minutes, sp.actual_salary
        FROM teams t
        LEFT JOIN seasons s ON s.season_id = %s
        LEFT JOIN season_players sp ON t.team_id = ANY(sp.team_ids)
        LEFT JOIN players p ON p.player_id = sp.player_id
        WHERE t.team_id = ANY(%s)
        ORDER BY t.team_id, p.player_id
        """,
        (season_id, season_id, team_ids),
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
        })
        if row["player_id"] is not None:
            team["players"].append({
                "player_id": row["player_id"], "name": row["name"],
                "lebron": row["lebron"], "minutes": row["minutes"],
                "external_id": row.get("external_id"),
                "offensive_lebron": row.get("offensive_lebron"),
                "defensive_lebron": row.get("defensive_lebron"),
                # Provisional annual USD mapping, as agreed for this simulator.
                "actual_salary": row.get("actual_salary"),
            })
    empty = [team_id for team_id in team_ids if not teams[team_id]["players"]]
    if empty:
        raise UnprocessableEntity(f"No roster data for season {season_id}, teams: {empty}.")
    return teams


def load_target_candidates(season_id):
    """Read each candidate once, summing all season stints like roster projections."""
    return query(
        """
        SELECT p.player_id, p.external_id,
               p.first_name || ' ' || p.last_name AS name,
               ps.lebron, ps.offensive_lebron, ps.defensive_lebron,
               to_jsonb(ps)->>'contract_value' AS actual_salary,
               SUM(pts.minutes_played) AS minutes,
               COALESCE(ARRAY_AGG(DISTINCT pts.team_id)
                   FILTER (WHERE pts.team_id IS NOT NULL), '{}') AS team_ids
        FROM player_seasons ps
        JOIN players p ON p.player_id = ps.player_id
        LEFT JOIN player_team_seasons pts ON pts.player_season_id = ps.player_season_id
        WHERE ps.season_id = %s
        GROUP BY p.player_id, ps.player_season_id
        ORDER BY p.player_id
        """,
        (season_id,),
    )


def load_cap_context(team_ids):
    """Use upcoming-season limits even when projections use older player data."""
    rules = SEASON_RULES[TRADE_SEASON_START_YEAR]
    # These are roster-only estimates until cap holds and dead money are available.
    return {team_id: {**rules, "other_cap_charges": "0.00", "charges_confirmed": False}
            for team_id in team_ids}
