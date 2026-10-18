"""Expose the commissioner dashboard and validate multi-team simulation requests."""

from flask import Blueprint, request
from werkzeug.exceptions import BadRequest

from .catalog import integer_argument
from ..responses import success
from ..services.trade_data import load_cap_context, load_target_candidates, load_trade_rosters
from ..services.trade_finances import TRADE_SEASON_START_YEAR
from ..services.trades import analyze_trade, commissioner_dashboard

trades = Blueprint("trades", __name__)


def positive_id(value):
    return type(value) is int and 1 <= value <= 2147483647


def parse_trade(body):
    """Each player has one source and destination, including in three-way trades."""
    if not isinstance(body, dict) or set(body) != {"season_id", "team_ids", "transfers"}:
        raise BadRequest("Provide only season_id, team_ids, and transfers.")
    if not positive_id(body["season_id"]):
        raise BadRequest("season_id must be a positive database integer ID.")
    team_ids = body["team_ids"]
    if not isinstance(team_ids, list) or not 2 <= len(team_ids) <= 30 or not all(positive_id(i) for i in team_ids):
        raise BadRequest("team_ids must contain 2 to 30 positive database integer IDs.")
    if len(set(team_ids)) != len(team_ids):
        raise BadRequest("Participating teams must be distinct.")
    transfers = body["transfers"]
    # Bound request work without presenting these limits as NBA eligibility rules.
    if not isinstance(transfers, list) or not 1 <= len(transfers) <= 100:
        raise BadRequest("transfers must contain 1 to 100 player transfers.")
    players, involved = set(), set()
    for transfer in transfers:
        if not isinstance(transfer, dict) or set(transfer) != {"player_id", "from_team_id", "to_team_id"}:
            raise BadRequest("Each transfer requires only player_id, from_team_id, and to_team_id.")
        if not all(positive_id(value) for value in transfer.values()):
            raise BadRequest("Transfer IDs must be positive database integer IDs.")
        source, destination = transfer["from_team_id"], transfer["to_team_id"]
        if source == destination or source not in team_ids or destination not in team_ids:
            raise BadRequest("Each transfer must connect two distinct participating teams.")
        if transfer["player_id"] in players:
            raise BadRequest("A player can move only once in a simulation.")
        players.add(transfer["player_id"])
        involved.update((source, destination))
    if involved != set(team_ids):
        raise BadRequest("Every participating team must send or receive a player.")
    return team_ids, body["season_id"], transfers


def simulation_meta(season_id):
    return {
        "season_id": season_id,
        "data_season_id": season_id,
        "trade_season": {
            "start_year": TRADE_SEASON_START_YEAR, "end_year": TRADE_SEASON_START_YEAR + 1,
        },
        "roster_source": "historical_season_membership",
        "salary_source": "player_seasons.contract_value_assumed_annual_usd",
        "minutes_basis": "full_season_all_teams_fixed_before_and_after",
        "projection_games": 82,
        "win_percentage_scale": "0_to_100",
        "warnings": [
            "Historical membership is not proof of current team ownership.",
            "Minutes stay fixed; this does not predict a new rotation.",
            "contract_value is provisionally treated as annual USD salary.",
            "Roster and contract data from the selected source season are not confirmed for 2026-27.",
            "Cap figures exclude untracked holds, dead money, bonuses, and other charges.",
            "Passing supported checks does not establish full NBA trade legality.",
        ],
    }


@trades.post("/trade/analyze")
@trades.post("/trade/validate")
def trade_analysis():
    team_ids, season_id, transfers = parse_trade(request.get_json())
    teams = load_trade_rosters(team_ids, season_id)
    cap_context = load_cap_context(team_ids)
    return success(analyze_trade(teams, team_ids, transfers, cap_context), simulation_meta(season_id))


@trades.get("/trade/teams/<int:team_id>")
def team_dashboard(team_id):
    """Supply the selected roster, its projection, and up to 15 addition targets."""
    if not positive_id(team_id):
        raise BadRequest("team_id must be a positive database integer ID.")
    if set(request.args) != {"season_id"} or len(request.args.getlist("season_id")) != 1:
        raise BadRequest("Provide exactly one season_id query parameter.")
    season_id = integer_argument("season_id", maximum=2147483647)
    teams = load_trade_rosters([team_id], season_id)
    candidates = load_target_candidates(season_id)
    context = load_cap_context([team_id])
    meta = simulation_meta(season_id)
    meta["target_basis"] = "single_player_addition_without_outgoing_players_or_legality_filter"
    return success(commissioner_dashboard(teams[team_id], candidates, context.get(team_id, {})), meta)
