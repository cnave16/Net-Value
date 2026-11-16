"""Fair salary from Chase's model next to each player's current cap salary.

Fair value comes from data_model/salary_value.py: the league's cap budget split
by each player's impact (LEBRON above replacement times minutes) in the latest
complete stats season. Salary is the 2026-27 cap salary from player_contracts.
"""

import time
from decimal import Decimal

from flask import current_app

from data_model.salary_value import MAX_SALARY_FRACTION, SALARY_CAP_2026_27, league_fair_salaries

from ..database import get_db

CACHE_SECONDS = 600
_cache = {}
_uncapped_cache = {}
# The model never values a player above this (35% of the cap, about the max).
VALUE_CEILING = SALARY_CAP_2026_27 * MAX_SALARY_FRACTION


def fair_values():
    """Return (stats_season_end_year, {external_id: fair salary}), cached per database.

    The whole league is valued at once, so results are cached for CACHE_SECONDS.
    An incomplete stats season gives (None, {}) instead of failing every request.
    """
    key = current_app.config.get("DATABASE_URL")
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1], cached[2]
    with get_db().cursor() as cursor:
        try:
            year, allocations = league_fair_salaries(cursor)
        except ValueError:
            year, allocations = None, {}
    _cache[key] = (time.monotonic(), year, allocations)
    return year, allocations


def uncapped_values():
    """{external_id: fair salary} with the ceiling removed, for players at the ceiling.

    Same model and season as fair_values(), but max_salary_fraction=1.0, so
    the stars the ceiling flattens get the model's own estimate. Cached.
    """
    key = current_app.config.get("DATABASE_URL")
    cached = _uncapped_cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    with get_db().cursor() as cursor:
        try:
            _, allocations = league_fair_salaries(cursor, max_salary_fraction=1.0)
        except ValueError:
            allocations = {}
    _uncapped_cache[key] = (time.monotonic(), allocations)
    return allocations


def valuation(external_id, cap_salary, contract_type, values, rookie=None, uncapped=None):
    """Salary, fair value, and surplus (fair value minus salary) for one player.

    Two-way contracts have no listed pay, so their salary and surplus are null.
    A rookie without stats gets the expected first-season value of their draft
    slot (rookie = {"pick", "value"} from services/draft.py).
    """
    salary = float(cap_salary) if cap_salary is not None and contract_type == "standard" else None
    fair = values.get(str(external_id)) if external_id else None
    basis = None if fair is None else "stats"
    at_ceiling = fair is not None and fair >= VALUE_CEILING - 1
    beyond = (uncapped or {}).get(str(external_id)) if at_ceiling else None
    if fair is None and rookie is not None:
        fair, basis = rookie["value"], "draft_slot"
    fair = None if fair is None else float(round(Decimal(str(fair))))
    # Why fair value is missing: the model ran but this player has no stats in
    # its season (missed it, barely played), or the model has no season at all.
    missing = None if fair is not None else "no_recent_stats" if values else "model_unavailable"
    return {
        "salary": salary, "predicted_value": fair,
        "surplus": None if salary is None or fair is None else fair - salary,
        "contract_type": contract_type, "value_basis": basis,
        "draft_pick": rookie["pick"] if basis == "draft_slot" else None,
        "value_missing_reason": missing,
        # At the ceiling, fair value is capped; uncapped_value is the model's own estimate.
        "at_value_ceiling": at_ceiling,
        "uncapped_value": None if beyond is None else float(round(Decimal(str(beyond)))),
    }
