"""Expose the commissioner dashboard and validate multi-team simulation requests."""

import re
from decimal import Decimal

from flask import Blueprint, request
from werkzeug.exceptions import BadRequest

from .catalog import integer_argument
from ..responses import success
from ..services.trade_data import load_cap_context, load_target_candidates, load_trade_rosters
from ..services.trade_finances import TRADE_SEASON_START_YEAR
from ..services.trades import analyze_trade, commissioner_dashboard
from ..services.recommendations import load_recommendation_values

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
        "roster_source": "player_contracts_current_season",
        "salary_source": "player_contracts.cap_salary",
        "minutes_basis": "full_season_all_teams_fixed_before_and_after",
        "projection_games": 82,
        "win_percentage_scale": "0_to_100",
        "warnings": [
            "Rosters and cap salaries come from Basketball-Reference contract pages and are as "
            "current as the last database_config/load_contracts.py run.",
            "Players without ratings and minutes in the selected data season count toward payroll "
            "but not win projections.",
            "Minutes stay fixed at the data season's totals; this does not predict a new rotation.",
            "Cap figures include the source's dead money but not cap holds, exceptions, or bonuses.",
            "Passing supported checks does not establish full NBA trade legality.",
        ],
    }


@trades.post("/trade/analyze")
@trades.post("/trade/validate")
def trade_analysis():
    team_ids, season_id, transfers = parse_trade(request.get_json())
    teams = load_trade_rosters(team_ids, season_id)
    cap_context = load_cap_context(team_ids, teams)
    return success(analyze_trade(teams, team_ids, transfers, cap_context), simulation_meta(season_id))


@trades.get("/trade/teams/<int:team_id>")
def team_dashboard(team_id):
    """Supply the selected roster, its projection, and up to 15 addition targets."""
    if not positive_id(team_id):
        raise BadRequest("team_id must be a positive database integer ID.")
    if ("season_id" not in request.args or set(request.args) - {"season_id", "available_salary"}
            or any(len(request.args.getlist(key)) != 1 for key in request.args)):
        raise BadRequest("Provide one season_id and optionally one available_salary.")
    raw_budget = request.args.get("available_salary")
    budget = None
    if raw_budget is not None:
        if not re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,2})?", raw_budget):
            raise BadRequest("available_salary must be nonnegative dollars with at most two decimal places.")
        budget = Decimal(raw_budget)
    season_id = integer_argument("season_id", maximum=2147483647)
    teams = load_trade_rosters([team_id], season_id)
    candidates = load_target_candidates(season_id)
    context = load_cap_context([team_id], teams)
    meta = simulation_meta(season_id)
    meta["target_basis"] = "single_player_addition_without_outgoing_players_or_legality_filter"
    meta["target_ranking"] = "chase_weighted_wins_salary_surplus_lebron"
    meta["target_budget_filter_applied"] = budget is not None
    meta["ranking_minutes_basis"] = "top_15_rotation_capped_at_3200_rescaled_to_19680"
    meta["warnings"].append(
        "Targets use Chase's score with an optional maximum incoming salary, not a legality filter. Each is an independent "
        "addition with no outgoing players. Ranking uses normalized rotation minutes; displayed "
        "projected_wins retain the trade simulator's fixed historical minutes."
    )
    values = load_recommendation_values(season_id)
    return success(commissioner_dashboard(teams[team_id], candidates, context.get(team_id, {}), values, budget), meta)
