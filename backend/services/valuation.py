"""Fair salary from Chase's model next to each player's current cap salary.

Fair value comes from data_model/salary_value.py: the league's cap budget split
by each player's impact (LEBRON above replacement times minutes) in the latest
complete stats season. Salary is the 2026-27 cap salary from player_contracts.
"""

import time
from decimal import Decimal

from flask import current_app

from data_model.salary_value import league_fair_salaries

from ..database import get_db

CACHE_SECONDS = 600
_cache = {}


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


def valuation(external_id, cap_salary, contract_type, values, rookie=None):
    """Salary, fair value, and surplus (fair value minus salary) for one player.

    Two-way contracts have no listed pay, so their salary and surplus are null.
    A rookie without stats gets the expected first-season value of their draft
    slot (rookie = {"pick", "value"} from services/draft.py).
    """
    salary = float(cap_salary) if cap_salary is not None and contract_type == "standard" else None
    fair = values.get(str(external_id)) if external_id else None
    basis = None if fair is None else "stats"
    if fair is None and rookie is not None:
        fair, basis = rookie["value"], "draft_slot"
    fair = None if fair is None else float(round(Decimal(str(fair))))
    return {
        "salary": salary, "predicted_value": fair,
        "surplus": None if salary is None or fair is None else fair - salary,
        "contract_type": contract_type, "value_basis": basis,
        "draft_pick": rookie["pick"] if basis == "draft_slot" else None,
    }
