"""Check salary matching boundaries and avoid blanket bans on apron-team trades."""

from decimal import Decimal

import pytest

from backend.services.trade_finances import SEASON_RULES
from backend.services.trade_legality import independent_salary_matches, salary_checks


CONTEXT = {**SEASON_RULES[2025], "other_cap_charges": "0"}


def player(salary):
    return {"actual_salary": str(salary)}


def check(before_total, sent, received):
    outgoing = [player(salary) for salary in sent]
    before = outgoing + [player(Decimal(str(before_total)) - sum(Decimal(str(s)) for s in sent))]
    return salary_checks(10, before, outgoing, [player(s) for s in received], CONTEXT)


@pytest.mark.parametrize("incoming,passed", [("14897000", True), ("14897000.01", False)])
def test_cap_room_includes_250k_allowance(incoming, passed):
    result = check("140000000", [], [incoming])[0]
    assert result["passed"] is passed
    assert result["maximum_incoming_salary"] == "14897000.00"
    assert result["rule"] == "cap_room"


@pytest.mark.parametrize("incoming,passed", [("10250000", True), ("10250000.01", False)])
def test_lower_expanded_matching_boundary(incoming, passed):
    result = check("160000000", ["5000000"], [incoming])[0]
    assert result["passed"] is passed
    assert result["maximum_incoming_salary"] == "10250000.00"


def test_middle_matching_uses_scaled_increment():
    limit = Decimal("10000000") + Decimal("7500000") * Decimal("154647000") / Decimal("136021000")
    floor = limit.quantize(Decimal("0.01"), rounding="ROUND_DOWN")
    assert check("170000000", ["10000000"], [floor])[0]["passed"] is True
    assert check("170000000", ["10000000"], [floor + Decimal("0.01")])[0]["passed"] is False


@pytest.mark.parametrize("incoming,passed", [("50250000", True), ("50250000.01", False)])
def test_upper_expanded_matching_boundary(incoming, passed):
    result = check("170000000", ["40000000"], [incoming])[0]
    assert result["passed"] is passed
    assert result["maximum_incoming_salary"] == "50250000.00"


def test_apron_uses_after_total_and_exact_boundary():
    assert check("190000000", ["10000000"], ["15945000"])[0]["passed"] is True
    result = check("190000000", ["10000000"], ["15945000.01"])[0]
    assert result["passed"] is False
    assert result["rule"] == "first_apron_no_salary_increase"
    # Starting over an apron does not forbid shedding salary below it.
    result = check("200000000", ["30000000"], ["20000000"])[0]
    assert result["passed"] is True
    assert result["rule"] == "expanded_traded_player_exception"


def test_first_apron_no_incoming_salary_increase():
    assert check("200000000", ["10000000"], ["10000000"])[0]["passed"] is True
    assert check("200000000", ["10000000"], ["10000000.01"])[0]["passed"] is False
    assert check("200000000", [], ["1"])[0]["passed"] is False
    assert check("200000000", ["10000000"], [])[0]["passed"] is True


@pytest.mark.parametrize("incoming,passed", [("19015000", True), ("19015000.01", False)])
def test_2026_first_apron_boundary(incoming, passed):
    context = {**SEASON_RULES[2026], "other_cap_charges": "0"}
    checks = salary_checks(
        10, [player("190000000"), player("10000000")],
        [player("10000000")], [player(incoming)], context,
    )
    assert checks[0]["passed"] is passed


def test_second_apron_aggregation_is_not_just_outgoing_count():
    blocked = check("220000000", ["5000000", "5000000"], ["10000000"])
    assert blocked[0]["passed"] is True
    assert blocked[1]["code"] == "SECOND_APRON_NO_AGGREGATION"
    assert blocked[1]["passed"] is False
    allowed = check("220000000", ["6000000", "4000000"], ["5000000", "4000000"])
    assert all(item["passed"] for item in allowed)
    # A single outgoing salary can cover several incoming contracts.
    allowed = check("220000000", ["10000000"], ["6000000", "4000000"])
    assert all(item["passed"] for item in allowed)


def test_aggregation_allowed_after_dropping_below_second_apron():
    checks = check("220000000", ["20000000", "20000000"], ["27824000"])
    assert len(checks) == 1 and checks[0]["passed"] is True
    checks = check("220000000", ["20000000", "20000000"], ["27824000.01"])
    assert checks[1]["passed"] is False


def test_non_greedy_matching_and_search_limit():
    assert independent_salary_matches([Decimal(8), Decimal(7)], [Decimal(7), Decimal(5), Decimal(3)]) is True
    assert independent_salary_matches([Decimal(5), Decimal(5)], [Decimal(6), Decimal(4)]) is False
    assert independent_salary_matches([], []) is True
    assert independent_salary_matches([], [Decimal(1)]) is False
    assert independent_salary_matches([Decimal(8)], [Decimal(7)], max_states=0) is None


def test_missing_salary_and_unsupported_season_are_unknown():
    for context, before in (({}, [player(100)]), (CONTEXT, [{"actual_salary": None}])):
        checks = salary_checks(10, before, [], [player(1)], context)
        assert checks[0]["passed"] is None


def test_charges_change_apron_classification():
    before = [player("190000000")]
    context = {**CONTEXT, "other_cap_charges": "20000000"}
    checks = salary_checks(10, before, [player("10000000")], [player("11000000")], context)
    assert checks[0]["passed"] is False
    assert checks[0]["rule"] == "first_apron_no_salary_increase"
