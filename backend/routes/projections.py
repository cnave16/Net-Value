"""Load one season's roster data and pass it to Chase's win calculation."""

import math

from flask import Blueprint, request
from werkzeug.exceptions import BadRequest, UnprocessableEntity

from data_model.project_wins import project_wins

from ..database import query
from ..responses import success

projections = Blueprint("projections", __name__)


def positive_id(value):
    # Reject booleans too: Python otherwise treats True as the integer 1.
    return type(value) is int and 1 <= value <= 2147483647


@projections.post("/projections/wins")
def wins():
    """Validate a roster, load its season, and return the model's estimate."""
    body = request.get_json()
    if not isinstance(body, dict):
        raise BadRequest("Send a JSON object with player_ids and season_id.")
    if set(body) != {"player_ids", "season_id"}:
        raise BadRequest("Only player_ids and season_id are accepted and both are required.")

    player_ids, season_id = body["player_ids"], body["season_id"]
    if not positive_id(season_id):
        raise BadRequest("season_id must be a positive database integer ID.")
    if not isinstance(player_ids, list) or not 12 <= len(player_ids) <= 15:
        raise BadRequest("player_ids must contain 12 to 15 players.")
    if not all(positive_id(player_id) for player_id in player_ids):
        raise BadRequest("player_ids must contain positive database integer IDs.")
    if len(set(player_ids)) != len(player_ids):
        raise BadRequest("player_ids must not contain duplicates.")

    # Use our internal IDs and one explicit season, through the API connection.
    # Sum team stints so a traded player's minutes count once for the full season.
    rows = query(
        "SELECT p.player_id, ps.lebron, SUM(pts.minutes_played) AS minutes "
        "FROM players p "
        "LEFT JOIN player_seasons ps ON ps.player_id = p.player_id AND ps.season_id = %s "
        "LEFT JOIN player_team_seasons pts ON pts.player_season_id = ps.player_season_id "
        "WHERE p.player_id = ANY(%s) "
        "GROUP BY p.player_id, ps.lebron ORDER BY p.player_id",
        (season_id, player_ids),
    )
    missing = sorted(set(player_ids) - {row["player_id"] for row in rows})
    if missing:
        raise UnprocessableEntity(f"Players not found: {missing}.")

    roster = []
    invalid = []
    for row in rows:
        try:
            lebron, minutes = float(row["lebron"]), float(row["minutes"])
        except (TypeError, ValueError, OverflowError):
            invalid.append(row["player_id"])
            continue
        # Missing or nonfinite values must not turn into a believable prediction.
        if not math.isfinite(lebron) or not math.isfinite(minutes) or minutes <= 0:
            invalid.append(row["player_id"])
            continue
        roster.append({"player_id": row["player_id"], "lebron": lebron, "minutes": minutes})
    if invalid:
        raise UnprocessableEntity(
            f"Players need a finite LEBRON rating and positive minutes for season {season_id}: {invalid}."
        )

    # Only call the pure calculation; Chase's database helpers and demo stay unused.
    result = project_wins(roster)
    if not all(math.isfinite(value) for value in result.values()):
        raise UnprocessableEntity("Roster data could not produce a finite projection.")
    return success(result, {"season_id": season_id, "player_ids": player_ids})
