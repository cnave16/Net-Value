"""Prepare selected-season league values for Chase's trade-target ranking."""

import math

from data_model.salary_value import (
    MIN_LEAGUE_MINUTES_COVERAGE, MINUTES_PER_TEAM_GAME, NBA_GAMES, NBA_TEAMS,
    _PlayerSeason, _compute_salary_allocations,
)

from ..database import query


def model_player(row):
    """Map an API player to the model's NBA ID and usable season inputs."""
    external = row.get("external_id")
    if external is None or not str(external).strip() or row.get("has_stats") is False:
        return None
    try:
        lebron, minutes = float(row["lebron"]), float(row["minutes"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(lebron) or not math.isfinite(minutes) or minutes <= 0:
        return None
    return _PlayerSeason(str(external).strip(), row["name"], lebron, minutes)


def load_recommendation_values(season_id):
    """Value the whole selected season using the API's read-only connection.

    Include players without current contracts so the league allocation does
    not redistribute their value to the remaining rostered players.
    """
    rows = query(
        "SELECT p.external_id, p.first_name || ' ' || p.last_name AS name, "
        "ps.lebron, SUM(pts.minutes_played) AS minutes "
        "FROM player_seasons ps JOIN players p ON p.player_id = ps.player_id "
        "JOIN player_team_seasons pts ON pts.player_season_id = ps.player_season_id "
        "WHERE ps.season_id = %s GROUP BY p.player_id, ps.player_season_id "
        "ORDER BY p.player_id",
        (season_id,),
    )
    players = [player for row in rows if (player := model_player(row)) is not None]
    required_minutes = NBA_TEAMS * NBA_GAMES * MINUTES_PER_TEAM_GAME * MIN_LEAGUE_MINUTES_COVERAGE
    if sum(p.minutes for p in players) < required_minutes:
        return {"fair": {}, "reason": "insufficient_season_coverage"}
    return {"fair": _compute_salary_allocations(players), "reason": None}
