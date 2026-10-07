"""Simulate a two-team player exchange without saving changes to the database."""

import math
from decimal import Decimal, InvalidOperation

from werkzeug.exceptions import UnprocessableEntity

from data_model.project_wins import project_wins


NOT_CHECKED = [
    "current_roster_ownership",
    "salary_matching_and_cap_restrictions",
    "apron_and_tax_restrictions",
    "contract_trade_restrictions_and_player_consent",
    "trade_deadline_and_transaction_dates",
    "roster_limits_and_contract_types",
    "draft_picks_cash_and_other_assets",
]


def check_trade(teams, team_ids, outgoing):
    """Check roster consistency, without claiming full NBA trade approval."""
    a, b = team_ids
    ids = {team_id: {p["player_id"] for p in teams[team_id]["players"]} for team_id in team_ids}
    shared = sorted(ids[a] & ids[b])
    checks = [{
        "code": "DISJOINT_ROSTERS", "passed": not shared,
        "message": "Starting rosters must not share players.", "player_ids": shared,
    }]
    for team_id in team_ids:
        missing = sorted(set(outgoing[team_id]) - ids[team_id])
        checks.append({
            "code": "OUTGOING_PLAYERS_ON_ROSTER", "team_id": team_id,
            "passed": not missing, "player_ids": missing,
            "message": "Outgoing players must belong to the loaded season roster.",
        })
    return {
        "status": "incomplete" if all(check["passed"] for check in checks) else "failed",
        "is_legal": None,
        "checks": checks,
        "not_checked": list(NOT_CHECKED),
    }


def projection(roster):
    """Validate every player before using the existing win calculation."""
    values, invalid = [], []
    for player in roster:
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


def money(value):
    """Keep dollar amounts exact, treating missing or invalid salaries as unavailable."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            return None
        return amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def payroll(before, retained, incoming, estimates):
    """Use actual salaries before, then actual retained salaries plus incoming estimates."""
    before_values = [money(p.get("actual_salary")) for p in before]
    retained_values = [money(p.get("actual_salary")) for p in retained]
    incoming_values = [money(estimates.get(p["player_id"])) for p in incoming]

    def total(values):
        return None if any(value is None for value in values) else sum(values, Decimal("0"))

    before_total, after_total = total(before_values), total(retained_values + incoming_values)
    difference = None if before_total is None or after_total is None else after_total - before_total
    return {
        "currency": "USD", "basis": "actual_retained_plus_estimated_incoming",
        "before": None if before_total is None else format(before_total, ".2f"),
        "after": None if after_total is None else format(after_total, ".2f"),
        "net_difference": None if difference is None else format(difference, ".2f"),
        "missing_actual_before": [p["player_id"] for p, v in zip(before, before_values) if v is None],
        "missing_actual_after": [p["player_id"] for p, v in zip(retained, retained_values) if v is None],
        "missing_estimated_after": [p["player_id"] for p, v in zip(incoming, incoming_values) if v is None],
    }


def analyze_trade(teams, team_ids, outgoing, estimates):
    """Return both teams' before/after results, or explain why simulation is blocked."""
    legality = check_trade(teams, team_ids, outgoing)
    if legality["status"] == "failed":
        return {"analysis_available": False, "teams": [], "legality": legality}

    results = []
    for team_id, other_id in (team_ids, team_ids[::-1]):
        team = teams[team_id]
        before = team["players"]
        retained = [p for p in before if p["player_id"] not in outgoing[team_id]]
        incoming = [p for p in teams[other_id]["players"] if p["player_id"] in outgoing[other_id]]
        # Keep each player's historical minutes fixed when moving between teams.
        after = sorted(retained + incoming, key=lambda p: p["player_id"])
        before_wins, after_wins = projection(before), projection(after)
        results.append({
            "team_id": team_id, "abbreviation": team["abbreviation"], "name": team["name"],
            "roster_before": sorted(p["player_id"] for p in before),
            "roster_after": [p["player_id"] for p in after],
            "outgoing_player_ids": sorted(outgoing[team_id]),
            "incoming_player_ids": sorted(outgoing[other_id]),
            "projected_wins": {
                "before": before_wins, "after": after_wins, "net_difference": after_wins - before_wins,
            },
            "payroll": payroll(before, retained, incoming, estimates),
        })
    return {"analysis_available": True, "teams": results, "legality": legality}
