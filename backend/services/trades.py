"""Simulate player transfers and compare each team's wins and actual payroll."""

import math

from werkzeug.exceptions import UnprocessableEntity

from data_model.project_wins import project_wins

from .trade_finances import cap_comparison, dollar, money, payroll
from .trade_legality import check_trade


def projection(roster):
    """Validate every player before using the existing win calculation."""
    values, invalid = [], []
    # Tied minutes must produce the same result regardless of transfer order.
    for player in sorted(roster, key=lambda p: p["player_id"]):
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


def commissioner_dashboard(team, candidates, cap_context):
    """Rank single-player additions against the selected team's unchanged roster."""
    roster = team["players"]
    before_wins = projection(roster)
    roster_ids = {p["player_id"] for p in roster}
    targets, skipped = [], []
    for player in candidates:
        if player["player_id"] in roster_ids:
            continue
        team_ids = player["team_ids"]
        if team["id"] in team_ids:
            continue
        try:
            after_wins = projection(roster + [player])
        except UnprocessableEntity:
            skipped.append({"player_id": player["player_id"], "reason": "unusable_projection_data"})
            continue
        targets.append({
            "player": player_details(player),
            "team_id": team_ids[0] if len(team_ids) == 1 else None,
            "team_ids": team_ids,
            **win_comparison(before_wins, after_wins),
        })
    targets.sort(key=lambda item: (-item["projected_wins"]["net_difference"], item["player"]["player_id"]))
    salaries = payroll(roster, roster)
    return {
        "team_id": team["id"], "abbreviation": team["abbreviation"], "name": team["name"],
        "roster": [player_details(p) for p in sorted(roster, key=lambda p: p["player_id"])],
        "projected_wins": before_wins, "projected_win_percentage": before_wins / 82 * 100,
        "payroll": salaries, "salary_cap": cap_comparison(salaries, cap_context),
        "targets": targets[:15], "eligible_target_count": len(targets),
        "skipped_targets": skipped,
    }
