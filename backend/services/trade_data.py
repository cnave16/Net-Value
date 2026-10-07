"""Load historical rosters for trades; replace this adapter when current rosters are ready."""

from werkzeug.exceptions import NotFound, UnprocessableEntity

from ..database import query


def load_trade_rosters(team_ids, season_id):
    """Read both rosters and their season data in one database snapshot."""
    rows = query(
        """
        WITH season_players AS (
            SELECT ps.player_id, ps.lebron,
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
               sp.lebron, sp.minutes
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
                # contract_value's meaning is unconfirmed; do not label it salary.
                "actual_salary": None,
            })
    empty = [team_id for team_id in team_ids if not teams[team_id]["players"]]
    if empty:
        raise UnprocessableEntity(f"No roster data for season {season_id}, teams: {empty}.")
    return teams


def load_estimated_salaries(player_ids, season_id):
    """Vincent's integration point: return annual USD estimates by internal player ID."""
    # Do not substitute actual salary for a missing incoming-player estimate.
    return {player_id: None for player_id in player_ids}
