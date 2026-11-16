"""Draft pick value by slot, built on Chase's fair-value model (salary_value.py).

Method: take one stats season's fair values (league_fair_salaries) for players
from recent draft classes. A player drafted in year D is in career year
(stats_end_year - D) during that season. Smooth fair value over draft slot and
career year with a Gaussian kernel (in log-pick space, since value falls
fastest at the top of the draft), then make it non-increasing by slot.

A pick's value is the expected fair value per season over its rookie contract,
compared with the rookie salary paid at that slot.

The settings below are placeholders until Chase confirms them.
"""

import math

try:  # Imported by the API as data_model.draft_value
    from .salary_value import BASE_SALARY_2026_27
except ImportError:  # Run from inside data_model/, like Chase's other scripts
    from salary_value import BASE_SALARY_2026_27

# Drafted players with no minutes in the stats season (washouts, injuries)
# count as the minimum salary rather than $0. (Open question 1.)
WASHOUT_VALUE = BASE_SALARY_2026_27
# Seasons of value a pick buys: rookie scale for round 1, typical 2nd-round deal.
# (Open question 4.)
CONTRACT_SEASONS = {1: 4, 2: 2}
FIRST_ROUND_PICKS = 30
PICKS = 60
# Kernel widths: ~35% change in pick number, and well under one career year so
# a rookie's estimate leans on first- and second-year players.
PICK_BANDWIDTH = 0.35
YEAR_BANDWIDTH = 0.6

ASSUMPTIONS = {
    "washout_value": WASHOUT_VALUE,
    "contract_seasons": CONTRACT_SEASONS,
    "replacement_level": "unchanged from salary_value.py",
    "sample": "one stats season across recent draft classes (not tracked over time)",
}


def round_of(pick):
    return 1 if pick <= FIRST_ROUND_PICKS else 2


def expected_values(observations, max_year=5):
    """Return {(pick, career_year): expected fair value} for picks 1-60.

    observations: (pick, career_year, fair_value or None) tuples; None means the
    player had no playable minutes and counts as WASHOUT_VALUE.
    """
    points = [(math.log(p), y, WASHOUT_VALUE if v is None else float(v))
              for p, y, v in observations if 1 <= p <= PICKS and y >= 1]
    if not points:
        raise ValueError("No draft observations to fit.")
    table = {}
    for year in range(1, max_year + 1):
        raw, mass = [], []
        for pick in range(1, PICKS + 1):
            x = math.log(pick)
            weights = [math.exp(-((x - px) / PICK_BANDWIDTH) ** 2 / 2 - ((year - py) / YEAR_BANDWIDTH) ** 2 / 2)
                       for px, py, _ in points]
            total = sum(weights)
            raw.append(sum(w * v for w, (_, _, v) in zip(weights, points)) / total if total else WASHOUT_VALUE)
            mass.append(total or 1e-9)
        # A later pick is never expected to be worth more than an earlier one.
        for pick, value in enumerate(non_increasing(raw, mass), start=1):
            table[(pick, year)] = value
    return table


def non_increasing(values, weights):
    """Weighted isotonic regression (pool adjacent violators), non-increasing.

    Out-of-order neighbors are averaged together, rather than cut to the lower one.
    """
    blocks = []  # [mean, weight, count]
    for value, weight in zip(values, weights):
        blocks.append([value, weight, 1])
        while len(blocks) > 1 and blocks[-2][0] < blocks[-1][0]:
            v2, w2, n2 = blocks.pop()
            v1, w1, n1 = blocks.pop()
            blocks.append([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, n1 + n2])
    return [mean for mean, _, count in blocks for _ in range(count)]


def fill_salaries(known):
    """Complete {pick: rookie salary} for 1-60, interpolating unsigned slots."""
    picks = sorted(p for p in known if 1 <= p <= PICKS)
    if not picks:
        return {}
    filled = {}
    for pick in range(1, PICKS + 1):
        if pick in known:
            filled[pick] = float(known[pick])
            continue
        lower = max((p for p in picks if p < pick), default=None)
        upper = min((p for p in picks if p > pick), default=None)
        if lower is None or upper is None:
            filled[pick] = float(known[lower if upper is None else upper])
        else:
            share = (pick - lower) / (upper - lower)
            filled[pick] = float(known[lower]) + share * (float(known[upper]) - float(known[lower]))
    return filled


def pick_values(table, salaries):
    """Value of each slot: expected fair value per season vs. first-year rookie salary."""
    results = []
    for pick in range(1, PICKS + 1):
        rnd = round_of(pick)
        by_year = [table[(pick, year)] for year in range(1, CONTRACT_SEASONS[rnd] + 1)]
        average = sum(by_year) / len(by_year)
        salary = salaries.get(pick)
        results.append({
            "pick": pick, "round": rnd, "contract_seasons": CONTRACT_SEASONS[rnd],
            "expected_value_by_season": [round(v) for v in by_year],
            "expected_value_per_season": round(average),
            "rookie_salary": None if salary is None else round(salary),
            "surplus_per_season": None if salary is None else round(average - salary),
        })
    return results
