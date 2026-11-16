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


def test_fill_salaries_interpolates_unsigned_slots():
    filled = dv.fill_salaries({1: 100, 3: 80, 60: 10})
    assert filled[2] == 90 and filled[1] == 100 and filled[59] == pytest.approx(10 + 70 / 57)


def test_pick_values_use_contract_length_by_round():
    table = {(p, y): 10e6 - p * 1e5 + y * 1e6 for p in range(1, 61) for y in range(1, 5)}
    values = {v["pick"]: v for v in dv.pick_values(table, {1: 5e6, 31: 2e6})}
    assert values[1]["contract_seasons"] == 4 and len(values[1]["expected_value_by_season"]) == 4
    assert values[31]["contract_seasons"] == 2
    assert values[1]["surplus_per_season"] == values[1]["expected_value_per_season"] - 5_000_000
    assert values[2]["rookie_salary"] is None
