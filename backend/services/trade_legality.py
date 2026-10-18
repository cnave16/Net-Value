"""Check roster ownership and ordinary salary matching under documented assumptions."""

from decimal import Decimal, ROUND_DOWN

from .trade_finances import dollar, money

NOT_CHECKED = [
    "authoritative_current_roster_ownership",
    "cap_holds_dead_money_and_apron_salary_adjustments",
    "existing_hard_caps_and_exception_history",
    "preexisting_trade_exceptions_and_other_acquisition_exceptions",
    "contract_guarantees_trade_bonuses_and_special_matching_salaries",
    "sign_and_trade_extension_waits_and_player_consent",
    "trade_deadline_moratorium_and_postseason_rules",
    "recently_acquired_player_aggregation_restrictions",
    "roster_limits_and_contract_types",
    "draft_picks_cash_and_other_assets",
]


def independent_salary_matches(outgoing, incoming, max_states=10000):
    """Fit incoming salaries into separate outgoing contracts without aggregation."""
    incoming = sorted(incoming, reverse=True)
    visited = set()

    def fit(index, capacities):
        if index == len(incoming):
            return True
        key = (index, tuple(sorted(capacities, reverse=True)))
        if key in visited:
            return False
        if len(visited) >= max_states:
            return None
        visited.add(key)
        tried = set()
        for slot, capacity in enumerate(capacities):
            if capacity < incoming[index] or capacity in tried:
                continue
            tried.add(capacity)
            remaining = list(capacities)
            remaining[slot] -= incoming[index]
            result = fit(index + 1, remaining)
            if result is not False:
                return result
        return False

    return fit(0, sorted(outgoing, reverse=True))


def salary_checks(team_id, before, outgoing, incoming, context):
    """Check cap-room or simultaneous matching, using post-trade apron levels."""
    outgoing_values = [money(p.get("actual_salary")) for p in outgoing]
    incoming_values = [money(p.get("actual_salary")) for p in incoming]
    before_values = [money(p.get("actual_salary")) for p in before]
    cap, first, second = (money(context.get(key)) for key in ("salary_cap", "first_apron", "second_apron"))
    charges = money(context.get("other_cap_charges"))
    required = before_values + outgoing_values + incoming_values + [cap, first, second, charges]
    if any(value is None for value in required):
        return [{
            "code": "SALARY_MATCHING", "team_id": team_id, "passed": None,
            "message": "Complete salaries and supported season cap settings are required.",
        }]

    sent = sum(outgoing_values, Decimal("0"))
    received = sum(incoming_values, Decimal("0"))
    before_total = sum(before_values, Decimal("0")) + charges
    after_total = before_total - sent + received
    retained_total = before_total - sent
    allowance = Decimal("250000")
    rule = "cap_room"
    # A team can choose cap room or a matching exception, but cannot add them.
    room_limit = max(Decimal("0"), cap - retained_total + allowance) if retained_total < cap else Decimal("0")
    if after_total > first:
        limit, rule = sent, "first_apron_no_salary_increase"
    elif outgoing:
        # Article VII 6(j): the $7.5m increment scales from the 2023-24 cap.
        increment = Decimal("7500000") * cap / Decimal("136021000")
        expanded = max(min(2 * sent + allowance, sent + increment), Decimal("1.25") * sent + allowance)
        limit = max(room_limit, expanded)
        rule = "cap_room" if room_limit >= expanded else "expanded_traded_player_exception"
    else:
        limit = room_limit

    # Never display a rounded-up limit that would reject that same dollar amount.
    limit = limit.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    checks = [{
        "code": "SALARY_MATCHING", "team_id": team_id, "passed": received <= limit,
        "message": "Incoming salary must fit cap room or the supported matching exception.",
        "rule": rule, "outgoing_salary": dollar(sent), "incoming_salary": dollar(received),
        "maximum_incoming_salary": dollar(limit),
    }]
    if after_total > second:
        # Sending two players is allowed when each incoming contract fits separately.
        matched = independent_salary_matches(outgoing_values, incoming_values)
        checks.append({
            "code": "SECOND_APRON_NO_AGGREGATION", "team_id": team_id, "passed": matched,
            "message": ("Matching search limit reached; manual review is required." if matched is None else
                        "Above the second apron, incoming salaries must fit separate outgoing contracts."),
        })
    return checks


def check_trade(teams, team_ids, outgoing, incoming, cap_context):
    """Return per-team checks without claiming that provisional data proves NBA legality."""
    ids = {team_id: {p["player_id"] for p in teams[team_id]["players"]} for team_id in team_ids}
    seen, shared = set(), set()
    for roster_ids in ids.values():
        shared.update(seen & roster_ids)
        seen.update(roster_ids)
    checks = [{
        "code": "DISJOINT_ROSTERS", "passed": not shared,
        "message": "Starting rosters must not share players.", "player_ids": sorted(shared),
    }]
    for team_id in team_ids:
        missing = sorted(set(outgoing[team_id]) - ids[team_id])
        checks.append({
            "code": "OUTGOING_PLAYERS_ON_ROSTER", "team_id": team_id,
            "passed": not missing, "player_ids": missing,
            "message": "Outgoing players must belong to the loaded season roster.",
        })
    roster_checks_passed = all(check["passed"] for check in checks)
    if roster_checks_passed:
        players = {p["player_id"]: p for team_id in team_ids for p in teams[team_id]["players"]}
        for team_id in team_ids:
            checks.extend(salary_checks(
                team_id, teams[team_id]["players"],
                [players[i] for i in outgoing[team_id]], [players[i] for i in incoming[team_id]],
                cap_context.get(team_id, {}),
            ))
    failed = any(check["passed"] is False for check in checks)
    unknown = any(check["passed"] is None for check in checks)
    return {
        "status": "failed" if failed else "incomplete",
        "is_legal": None,
        "passes_supported_rules": False if failed else (None if unknown else True),
        "roster_checks_passed": roster_checks_passed,
        "checks": checks, "not_checked": list(NOT_CHECKED),
        "basis": "provisional_contract_values_and_roster_only_team_salary",
    }
