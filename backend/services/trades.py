"""Simulate player transfers and compare each team's wins and actual payroll."""

import math

from werkzeug.exceptions import UnprocessableEntity

from data_model.project_wins import project_wins
from data_model.roster_optimizer import _rank_single_players_from_data

from .recommendations import model_player

from .trade_finances import cap_comparison, dollar, money, payroll
from .trade_legality import check_trade


def projection(roster):
    """Validate every player before using the existing win calculation."""
    values, invalid = [], []
    # Tied minutes must produce the same result regardless of transfer order.
    for player in sorted(roster, key=lambda p: p["player_id"]):
        # Rookies and players who missed the data season have no inputs to use.
        if player.get("has_stats") is False:
            continue
        try:
            lebron, minutes = float(player["lebron"]), float(player["minutes"])
        except (TypeError, ValueError, OverflowError):
            invalid.append(player["player_id"])
            continue
        if not math.isfinite(lebron) or not math.isfinite(minutes) or minutes < 0:
            invalid.append(player["player_id"])
        else:
            values.append({"player_id": player["player_id"], "lebron": lebron, "minutes": minutes})
    if invalid:
        raise UnprocessableEntity(f"Missing or invalid season ratings/minutes for players: {sorted(invalid)}.")
    # Historical rosters can exceed 15 players. Do not call that an illegal trade.
    if not values or not 0 < sum(p["minutes"] for p in values) < math.inf:
        raise UnprocessableEntity("Every before/after roster needs positive total recorded minutes.")
    try:
        result = project_wins(values)
    except (OverflowError, ValueError):
        raise UnprocessableEntity("Roster data could not produce a finite projection.") from None
    if not all(math.isfinite(value) for value in result.values()):
        raise UnprocessableEntity("Roster data could not produce a finite projection.")
    return result["projected_wins"]


def win_comparison(before, after):
    """Percentages use the model's 82-game season; differences are percentage points."""
    return {
        "projected_wins": {"before": before, "after": after, "net_difference": after - before},
        "projected_win_percentage": {
            "before": before / 82 * 100, "after": after / 82 * 100,
            "net_difference": (after - before) / 82 * 100,
        },
    }


def player_details(player):
    """Return roster information with numeric ratings and exact salary strings."""
    def number(field):
        value = player.get(field)
        try:
            value = float(value)
        except (ValueError, TypeError, OverflowError):
            return None
        return value if math.isfinite(value) else None

    return {
        "player_id": player["player_id"], "name": player["name"],
        "external_id": player.get("external_id"),
        "lebron": number("lebron"), "offensive_lebron": number("offensive_lebron"),
        "defensive_lebron": number("defensive_lebron"), "minutes": number("minutes"),
        "actual_salary": dollar(money(player.get("actual_salary"))),
        "contract_type": player.get("contract_type"),
        "has_stats": player.get("has_stats", True),
    }


def analyze_trade(teams, team_ids, transfers, cap_context):
    """Apply every move at once, then run checks and project all participating teams."""
    outgoing = {team_id: [] for team_id in team_ids}
    incoming = {team_id: [] for team_id in team_ids}
    for transfer in transfers:
        outgoing[transfer["from_team_id"]].append(transfer["player_id"])
        incoming[transfer["to_team_id"]].append(transfer["player_id"])

    legality = check_trade(teams, team_ids, outgoing, incoming, cap_context)
    if not legality["roster_checks_passed"]:
        return {"analysis_available": False, "teams": [], "legality": legality}

    players = {p["player_id"]: p for team_id in team_ids for p in teams[team_id]["players"]}
    results = []
    for team_id in team_ids:
        team = teams[team_id]
        before = team["players"]
        retained = [p for p in before if p["player_id"] not in outgoing[team_id]]
        # All incoming players come from the original snapshot, even in a cycle.
        after = sorted(retained + [players[i] for i in incoming[team_id]], key=lambda p: p["player_id"])
        before_wins, after_wins = projection(before), projection(after)
        salaries = payroll(before, after)
        results.append({
            "team_id": team_id, "abbreviation": team["abbreviation"], "name": team["name"],
            "roster_before": sorted(p["player_id"] for p in before),
            "roster_after": [p["player_id"] for p in after],
            "outgoing_player_ids": sorted(outgoing[team_id]),
            "incoming_player_ids": sorted(incoming[team_id]),
            **win_comparison(before_wins, after_wins),
            "payroll": salaries,
            "salary_cap": cap_comparison(salaries, cap_context.get(team_id, {})),
        })
    return {"analysis_available": True, "teams": results, "legality": legality}


def commissioner_dashboard(team, candidates, cap_context, valuation, available_salary=None):
    """Rank targets with Chase's score, without claiming they fit a trade budget."""
    roster = team["players"]
    before_wins = projection(roster)
    roster_ids = {p["player_id"] for p in roster}
    roster_models = [model_player(p) for p in roster]
    excluded = [p["player_id"] for p, model in zip(roster, roster_models) if model is None]
    models = [p for p in roster_models if p is not None]
    reason = valuation["reason"]
    # Missing ratings stay excluded as in the trade simulator. Missing NBA IDs
    # on otherwise usable roster members would silently change Chase's baseline.
    if any(p.get("has_stats") is not False and p.get("minutes")
           and not p.get("external_id") for p in roster):
        reason = "missing_roster_nba_id"
    if not models:
        reason = "no_usable_roster_stats"
    targets, skipped, eligible_count = [], [], 0
    over_budget_count = 0
    weights = None
    if reason is None:
        candidate_map, prices, after_wins = {}, {}, {}
        for player in candidates:
            if player["player_id"] in roster_ids or team["id"] in player["team_ids"]:
                continue
            model = model_player(player)
            salary = money(player.get("actual_salary"))
            code = None
            if not player.get("external_id"):
                code = "missing_nba_id"
            elif model is None:
                code = "unusable_projection_data"
            elif model.external_id not in valuation["fair"]:
                code = "missing_fair_value"
            elif salary is None or salary <= 0:
                code = "missing_positive_actual_salary"
            if code:
                skipped.append({"player_id": player["player_id"], "reason": code})
                continue
            # Compare exact cap-salary cents before Chase rounds model values.
            if available_salary is not None and salary > available_salary:
                over_budget_count += 1
                continue
            external = model.external_id
            candidate_map[external] = player
            prices[external] = salary
            models.append(model)
            after_wins[external] = projection(roster + [player])
        ranked = _rank_single_players_from_data(
            models, valuation["fair"],
            [p.external_id for p in roster_models if p is not None],
            None, prices, candidate_ids=list(candidate_map), top_n=15,
        )
        weights = ranked["weights"]
        eligible_count = ranked["eligible_candidate_count"]
        for item in ranked["recommendations"]:
            external = item["player_id"]
            player = candidate_map[external]
            team_ids = player["team_ids"]
            targets.append({
                "player": player_details(player),
                "team_id": team_ids[0] if len(team_ids) == 1 else None,
                "team_ids": team_ids,
                # Existing displayed wins keep the trade simulator's minutes basis.
                **win_comparison(before_wins, after_wins[external]),
                "score": item["score"],
                "estimated_fair_salary": item["estimated_fair_salary"],
                "salary_surplus": item["salary_surplus"],
                "ranking_projected_wins": {
                    "before": item["baseline_projected_wins"],
                    "after": item["new_projected_wins"],
                    "net_difference": item["wins_added"],
                },
            })
    salaries = payroll(roster, roster)
    return {
        "team_id": team["id"], "abbreviation": team["abbreviation"], "name": team["name"],
        "roster": [player_details(p) for p in sorted(roster, key=lambda p: p["player_id"])],
        "projected_wins": before_wins, "projected_win_percentage": before_wins / 82 * 100,
        "payroll": salaries, "salary_cap": cap_comparison(salaries, cap_context),
        "targets": targets, "eligible_target_count": eligible_count,
        "skipped_targets": sorted(skipped, key=lambda p: p["player_id"]),
        "recommendation_status": "unavailable" if reason else "available",
        "recommendation_reason": reason,
        "ranking_excluded_roster_ids": sorted(excluded),
        "ranking_weights": weights,
        "budget_filter_applied": available_salary is not None,
        "available_salary": dollar(available_salary),
        "over_budget_candidate_count": over_budget_count,
    }
