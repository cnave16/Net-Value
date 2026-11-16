"""Draft pick values and rookie estimates from data_model/draft_value.py.

Recent draft classes' fair values (Chase's model, latest stats season) give
expected value by slot. The newest class (drafted for the trade season) supplies
rookie salaries by slot and is the set of rookies estimated from their slot.
"""

import time

from flask import current_app

from data_model.draft_value import ASSUMPTIONS, expected_values, fill_salaries, pick_values

from ..database import query
from .trade_finances import TRADE_SEASON_START_YEAR
from .valuation import fair_values

CACHE_SECONDS = 600
HISTORY_CLASSES = 5
_cache = {}


def draft_model():
    """Return the fitted model as a dict, or None without stats or draft data. Cached."""
    key = current_app.config.get("DATABASE_URL")
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    model = build_model()
    _cache[key] = (time.monotonic(), model)
    return model


def build_model():
    stats_year, values = fair_values()
    if stats_year is None:
        return None
    rows = query(
        """
        SELECT dp.draft_year, dp.pick, dp.player_id, dp.player_name, p.external_id,
               c.cap_salary, c.later_salaries, c.contract_type
        FROM draft_picks dp
        LEFT JOIN players p ON p.player_id = dp.player_id
        LEFT JOIN player_contracts c
            ON c.player_id = dp.player_id AND c.season_start_year = %s
        WHERE dp.draft_year BETWEEN %s AND %s
        ORDER BY dp.draft_year, dp.pick
        """,
        (TRADE_SEASON_START_YEAR, stats_year - HISTORY_CLASSES, TRADE_SEASON_START_YEAR),
    )
    # A player drafted in year D is in career year stats_year - D during the stats season.
    history = [r for r in rows if r["draft_year"] < stats_year]
    observations = [
        (r["pick"], stats_year - r["draft_year"],
         values.get(str(r["external_id"])) if r["external_id"] else None)
        for r in history
    ]
    rookies = [r for r in rows if r["draft_year"] == TRADE_SEASON_START_YEAR]
    if not observations or not rookies:
        return None

    table = expected_values(observations)
    typical = expected_values(observations, statistic="median")
    signed = {r["pick"]: [r["cap_salary"], *(r["later_salaries"] or [])] for r in rookies
              if r["cap_salary"] is not None and r["contract_type"] == "standard"}
    salaries, estimated = fill_salaries(signed)
    picks = pick_values(table, salaries, typical, estimated)
    by_pick = {r["pick"]: r for r in rookies}
    for slot in picks:
        rookie = by_pick.get(slot["pick"])
        slot["current_draftee"] = None if rookie is None else {
            "player_id": rookie["player_id"], "name": rookie["player_name"],
        }
    return {
        "stats_season_end_year": stats_year,
        "history_classes": sorted({r["draft_year"] for r in history}),
        "sample_size": len(observations),
        "rookie_class": TRADE_SEASON_START_YEAR,
        "picks": picks,
        # First-season expected value for each current rookie, by player_id.
        "rookies": {r["player_id"]: {"pick": r["pick"], "value": table[(r["pick"], 1)]}
                    for r in rookies if r["player_id"] is not None},
        "assumptions": ASSUMPTIONS,
    }


def rookie_estimates():
    """{player_id: {"pick", "value"}} for the current rookie class; empty without data."""
    model = draft_model()
    return model["rookies"] if model else {}
