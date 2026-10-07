"""Validate two-team trade requests and return win and payroll comparisons."""

from flask import Blueprint, request
from werkzeug.exceptions import BadRequest

from ..responses import success
from ..services.trade_data import load_estimated_salaries, load_trade_rosters
from ..services.trades import analyze_trade

trades = Blueprint("trades", __name__)


def positive_id(value):
    return type(value) is int and 1 <= value <= 2147483647


def parse_trade(body):
    """Accept only team/season IDs and the outgoing players on each side."""
    fields = {"season_id", "team_a_id", "team_b_id", "team_a_sends", "team_b_sends"}
    if not isinstance(body, dict) or set(body) != fields:
        raise BadRequest("Provide only season_id, team_a_id, team_b_id, team_a_sends, and team_b_sends.")
    for field in ("season_id", "team_a_id", "team_b_id"):
        if not positive_id(body[field]):
            raise BadRequest(f"{field} must be a positive database integer ID.")
    if body["team_a_id"] == body["team_b_id"]:
        raise BadRequest("Choose two different teams.")

    outgoing = {}
    for side in ("a", "b"):
        package = body[f"team_{side}_sends"]
        if not isinstance(package, dict) or "player_ids" not in package or set(package) - {"player_ids", "pick_ids"}:
            raise BadRequest(f"team_{side}_sends must contain player_ids and optionally empty pick_ids.")
        if "pick_ids" in package and package["pick_ids"] != []:
            raise BadRequest("Draft picks are not supported yet; pick_ids must be an empty array.")
        ids = package["player_ids"]
        # This bounds request size, not the NBA's roster limit.
        if not isinstance(ids, list) or len(ids) > 100 or not all(positive_id(i) for i in ids):
            raise BadRequest("player_ids must be an array of up to 100 positive database integer IDs.")
        if len(ids) != len(set(ids)):
            raise BadRequest("A player cannot appear more than once in a trade package.")
        outgoing[body[f"team_{side}_id"]] = ids
    a, b = body["team_a_id"], body["team_b_id"]
    if not outgoing[a] and not outgoing[b]:
        raise BadRequest("Include at least one outgoing player.")
    if set(outgoing[a]) & set(outgoing[b]):
        raise BadRequest("A player cannot be sent by both teams.")
    return [a, b], body["season_id"], outgoing


@trades.post("/trade/analyze")
@trades.post("/trade/validate")
def trade_analysis():
    team_ids, season_id, outgoing = parse_trade(request.get_json())
    teams = load_trade_rosters(team_ids, season_id)
    estimates = load_estimated_salaries(outgoing[team_ids[0]] + outgoing[team_ids[1]], season_id)
    return success(analyze_trade(teams, team_ids, outgoing, estimates), {
        "season_id": season_id,
        "roster_source": "historical_season_membership",
        "minutes_basis": "full_season_all_teams_fixed_before_and_after",
        "warnings": [
            "Historical membership is not proof of current team ownership.",
            "Minutes stay fixed; this does not predict a new rotation.",
            "Payroll is a hybrid estimate, not actual cap space or a salary-cap check.",
            "Actual salary mapping is unconfirmed and incoming estimates are not connected yet.",
            "Passing basic checks does not establish full NBA trade legality.",
        ],
    })
