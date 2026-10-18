"""Keep salary arithmetic exact and store season cap settings."""

from decimal import Decimal, InvalidOperation

TRADE_SEASON_START_YEAR = 2026

# Official NBA releases and CBA references are linked in docs/trades.md.
# Add seasons explicitly rather than guessing a future cap from a database ID.
SEASON_RULES = {
    2024: {
        "salary_cap": "140588000", "first_apron": "178132000", "second_apron": "188931000",
    },
    2025: {
        "salary_cap": "154647000", "first_apron": "195945000", "second_apron": "207824000",
    },
    # User-supplied 2026–27 figures, converted from millions to USD.
    2026: {
        "salary_cap": "164961000", "minimum_team_salary": "148465000",
        "first_apron": "209015000", "second_apron": "221686000",
    },
}


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


def dollar(value):
    return None if value is None else format(value, ".2f")


def payroll(before, after):
    """Actual contracts follow players; market-value estimates are not cap salaries."""
    def snapshot(roster):
        values = [money(p.get("actual_salary")) for p in roster]
        missing = sorted(p["player_id"] for p, value in zip(roster, values) if value is None)
        total = None if missing else sum(values, Decimal("0"))
        return total, missing

    before_total, missing_before = snapshot(before)
    after_total, missing_after = snapshot(after)
    difference = None if before_total is None or after_total is None else after_total - before_total
    return {
        "currency": "USD", "basis": "contract_value_assumed_annual_usd",
        "before": dollar(before_total), "after": dollar(after_total),
        "net_difference": dollar(difference),
        "missing_actual_before": missing_before, "missing_actual_after": missing_after,
    }


def cap_comparison(salaries, context):
    """Compare cap space; mark roster-only figures as estimates."""
    limit = money(context.get("salary_cap"))
    charges = money(context.get("other_cap_charges"))
    before_payroll, after_payroll = money(salaries["before"]), money(salaries["after"])
    # The adapter explicitly supplies zero when excluding untracked cap charges.
    before = None if None in (limit, charges, before_payroll) else limit - charges - before_payroll
    after = None if None in (limit, charges, after_payroll) else limit - charges - after_payroll
    return {
        "currency": "USD", "basis": "cap_minus_payroll_and_supplied_other_charges",
        "is_estimate": True,
        "other_cap_charges_confirmed": context.get("charges_confirmed", False),
        "minimum_team_salary": dollar(money(context.get("minimum_team_salary"))),
        "first_apron": dollar(money(context.get("first_apron"))),
        "second_apron": dollar(money(context.get("second_apron"))),
        "limit": dollar(limit), "other_cap_charges": dollar(charges),
        "before": dollar(before), "after": dollar(after),
        "net_difference": dollar(None if before is None or after is None else after - before),
    }
