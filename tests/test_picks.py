"""Draft pick value API and the draft value model."""

from unittest.mock import MagicMock

import pytest

from backend import create_app
from backend.routes import picks
from data_model import draft_value as dv


@pytest.fixture
def client():
    return create_app({"TESTING": True, "DATABASE_URL": None}).test_client()


def slots():
    return [{"pick": p, "round": dv.round_of(p), "expected_value_per_season": 100 - p} for p in range(1, 61)]


@pytest.fixture
def model(monkeypatch):
    fitted = {"picks": slots(), "stats_season_end_year": 2026, "history_classes": [2021, 2025],
              "sample_size": 290, "rookie_class": 2026, "assumptions": dv.ASSUMPTIONS}
    monkeypatch.setattr(picks, "draft_model", MagicMock(return_value=fitted))
    return fitted


def test_all_slots_and_filters(client, model):
    assert len(client.get("/api/picks").json["data"]) == 60
    assert [p["pick"] for p in client.get("/api/picks?slot=7").json["data"]] == [7]
    second = client.get("/api/picks?round=2").json["data"]
    assert len(second) == 30 and all(p["round"] == 2 for p in second)
    meta = client.get("/api/picks").json["meta"]
    assert meta["sample_size"] == 290 and meta["assumptions"]["contract_seasons"] == {"1": 4, "2": 2}


@pytest.mark.parametrize("query", ["slot=0", "slot=61", "round=3", "year=2027", "team=BOS"])
def test_bad_parameters(client, model, query):
    assert client.get(f"/api/picks?{query}").status_code == 400


def test_missing_draft_data(client, monkeypatch):
    monkeypatch.setattr(picks, "draft_model", MagicMock(return_value=None))
    assert client.get("/api/picks").status_code == 422


def test_expected_values_fall_with_pick_and_count_washouts_at_minimum():
    observations = [(1, 1, 40e6), (2, 1, 30e6), (10, 1, 5e6), (30, 1, None), (45, 1, None), (1, 2, 50e6)]
    table = dv.expected_values(observations, max_year=2)
    year_one = [table[(p, 1)] for p in range(1, 61)]
    assert all(a >= b for a, b in zip(year_one, year_one[1:]))
    assert year_one[0] > 20e6
    assert year_one[-1] == pytest.approx(dv.WASHOUT_VALUE, rel=0.05)


def test_non_increasing_averages_violators_instead_of_cutting():
    assert dv.non_increasing([5, 10, 1], [1, 1, 1]) == [7.5, 7.5, 1]
    assert dv.non_increasing([3, 2, 1], [1, 1, 1]) == [3, 2, 1]


def test_median_is_typical_outcome_not_pulled_up_by_a_star():
    # One star among washouts at the same slot: the mean rises, the median doesn't.
    observations = [(5, 1, 50e6)] + [(5, 1, None)] * 6
    mean = dv.expected_values(observations, max_year=1)[(5, 1)]
    median = dv.expected_values(observations, max_year=1, statistic="median")[(5, 1)]
    assert mean > 5 * median and median == pytest.approx(dv.WASHOUT_VALUE)


def test_fill_salaries_interpolates_each_season_separately():
    filled, estimated = dv.fill_salaries({1: [100, 110, 120, 130], 3: [80, 84, None, None], 60: [10, 12, 14, 16]})
    assert filled[1] == [100, 110, 120, 130] and 1 not in estimated
    assert filled[2][:2] == [90, 97] and 2 in estimated
    # Pick 3's missing later seasons come from its neighbors that list them.
    assert filled[3][:2] == [80, 84] and 3 in estimated
    assert filled[3][2] == pytest.approx(120 + (14 - 120) * 2 / 59)


def test_pick_values_compare_value_and_salary_over_the_same_seasons():
    table = {(p, y): 10e6 + y * 1e6 for p in range(1, 61) for y in range(1, 5)}
    salaries = {p: [4e6, 5e6, 6e6, 7e6] for p in range(1, 61)}
    values = {v["pick"]: v for v in dv.pick_values(table, salaries, table, {2})}
    first, second = values[1], values[31]
    assert first["contract_seasons"] == 4 and first["salary_per_season"] == 5_500_000
    assert first["surplus_per_season"] == 12_500_000 - 5_500_000
    assert first["typical_surplus_per_season"] == first["surplus_per_season"]
    assert second["contract_seasons"] == 2 and second["salary_per_season"] == 4_500_000
    assert values[2]["salary_is_estimate"] and not first["salary_is_estimate"]
