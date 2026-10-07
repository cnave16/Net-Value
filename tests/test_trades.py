"""Check trade results, partial legality, and payroll without writing to a database."""

from copy import deepcopy
from decimal import Decimal
from unittest.mock import MagicMock

import psycopg2
import pytest

from backend import create_app
from backend.routes import trades
from backend.services import trade_data
from backend.services.trades import analyze_trade, payroll


@pytest.fixture
def client():
    return create_app({"TESTING": True, "DATABASE_URL": None}).test_client()


@pytest.fixture
def payload():
    return {
        "season_id": 1, "team_a_id": 10, "team_b_id": 20,
        "team_a_sends": {"player_ids": [1], "pick_ids": []},
        "team_b_sends": {"player_ids": [13]},
    }


@pytest.fixture
def teams():
    return {
        team_id: {
            "id": team_id, "abbreviation": abbreviation, "name": abbreviation,
            "players": [{
                "player_id": player_id, "name": f"Player {player_id}",
                "lebron": Decimal(rating), "minutes": Decimal("100"),
                "actual_salary": Decimal("1000000.10"),
            } for player_id in range(start, start + 12)],
        }
        for team_id, abbreviation, start, rating in (
            (10, "AAA", 1, "1"), (20, "BBB", 13, "3")
        )
    }


@pytest.fixture
def loaded(monkeypatch, teams):
    loader = MagicMock(return_value=teams)
    monkeypatch.setattr(trades, "load_trade_rosters", loader)
    return loader


@pytest.mark.parametrize("path", ["/api/trade/analyze", "/api/trade/validate"])
def test_trade_moves_players_and_returns_real_model_results(client, payload, teams, loaded, path):
    original = deepcopy(teams)
    response = client.post(path, json=payload)
    assert response.status_code == 200
    data = response.json["data"]
    assert data["analysis_available"] is True
    a, b = data["teams"]
    assert a["roster_after"] == list(range(2, 14))
    assert b["roster_after"] == [1] + list(range(14, 25))
    assert a["projected_wins"]["before"] == pytest.approx(31.10105)
    assert b["projected_wins"]["before"] == pytest.approx(45.59065)
    # Equal minutes make these small fixtures easy to calculate independently.
    assert a["projected_wins"]["after"] == pytest.approx(32.3085166667)
    assert b["projected_wins"]["after"] == pytest.approx(50.1583033333)
    for result in (a, b):
        wins = result["projected_wins"]
        assert wins["net_difference"] == pytest.approx(wins["after"] - wins["before"])
        assert result["payroll"]["before"] == "12000001.20"
        assert result["payroll"]["after"] is None
        assert result["payroll"]["net_difference"] is None
    assert data["legality"]["is_legal"] is None
    assert data["legality"]["status"] == "incomplete"
    assert "salary_matching_and_cap_restrictions" in data["legality"]["not_checked"]
    assert response.json["meta"]["roster_source"] == "historical_season_membership"
    assert teams == original
    loaded.assert_called_once_with([10, 20], 1)


def test_estimated_payroll_for_incoming_only(client, payload, loaded, monkeypatch):
    estimates = MagicMock(return_value={1: "2000000.25", 13: "3000000.75"})
    monkeypatch.setattr(trades, "load_estimated_salaries", estimates)
    a, b = client.post("/api/trade/analyze", json=payload).json["data"]["teams"]
    assert a["payroll"]["after"] == "14000001.85"
    assert a["payroll"]["net_difference"] == "2000000.65"
    assert b["payroll"]["after"] == "13000001.35"
    assert b["payroll"]["net_difference"] == "1000000.15"
    estimates.assert_called_once_with([1, 13], 1)


def test_multi_player_trade_and_symmetry(teams):
    forward = analyze_trade(teams, [10, 20], {10: [1, 2], 20: [13]}, {})
    reverse = analyze_trade(teams, [20, 10], {10: [1, 2], 20: [13]}, {})
    assert forward["teams"] == reverse["teams"][::-1]
    assert len(forward["teams"][0]["roster_after"]) == 11
    assert len(forward["teams"][1]["roster_after"]) == 13
    # Counts are historical-model inputs, not a claimed NBA roster-size rule.
    assert forward["legality"]["status"] == "incomplete"


def test_one_sided_exchange_is_not_mislabeled_illegal(client, payload, loaded):
    payload["team_b_sends"]["player_ids"] = []
    data = client.post("/api/trade/analyze", json=payload).json["data"]
    assert data["analysis_available"]
    assert data["teams"][0]["payroll"]["after"] == "11000001.10"
    assert data["teams"][1]["payroll"]["after"] is None


@pytest.mark.parametrize("changes", [
    {"team_a_id": 20}, {"team_a_id": True}, {"season_id": "1"},
    {"team_b_id": 2147483648}, {"extra": 1},
    {"team_a_sends": {"player_ids": [1, 1]}},
    {"team_a_sends": {"player_ids": [13]}},
    {"team_a_sends": {"player_ids": [True]}},
    {"team_a_sends": {"player_ids": [0]}},
    {"team_a_sends": {"player_ids": [1.5]}},
    {"team_a_sends": {"player_ids": "1"}},
    {"team_a_sends": {"player_ids": list(range(1, 102))}},
    {"team_a_sends": {"player_ids": [1], "pick_ids": [1]}},
    {"team_a_sends": {"player_ids": [1], "pick_ids": None}},
    {"team_a_sends": {"player_ids": [1], "cash": 100}},
    {"team_a_sends": []},
    {"team_a_sends": {"player_ids": []}, "team_b_sends": {"player_ids": []}},
])
def test_bad_requests_never_load_rosters(client, payload, loaded, changes):
    response = client.post("/api/trade/analyze", json={**payload, **changes})
    assert response.status_code == 400
    loaded.assert_not_called()


@pytest.mark.parametrize("body", ["null", "[]", "{}", "{"])
def test_malformed_json(client, loaded, body):
    assert client.post("/api/trade/analyze", data=body, content_type="application/json").status_code == 400
    loaded.assert_not_called()


def test_json_content_type_required(client, loaded):
    assert client.post("/api/trade/analyze", data="{}").status_code == 415
    loaded.assert_not_called()


def test_wrong_roster_returns_failed_check_without_projection(client, payload, loaded, monkeypatch):
    payload["team_a_sends"]["player_ids"] = [999]
    model = MagicMock()
    monkeypatch.setattr("backend.services.trades.project_wins", model)
    response = client.post("/api/trade/analyze", json=payload)
    assert response.status_code == 200
    data = response.json["data"]
    assert not data["analysis_available"]
    assert data["teams"] == []
    assert data["legality"]["status"] == "failed"
    assert data["legality"]["checks"][1]["player_ids"] == [999]
    model.assert_not_called()


def test_shared_historical_players_are_not_counted_twice(client, payload, loaded, teams):
    teams[20]["players"].append(deepcopy(teams[10]["players"][0]))
    data = client.post("/api/trade/analyze", json=payload).json["data"]
    assert not data["analysis_available"]
    assert data["legality"]["checks"][0]["player_ids"] == [1]


@pytest.mark.parametrize("field,value", [
    ("lebron", None), ("lebron", float("nan")), ("lebron", float("inf")),
    ("minutes", None), ("minutes", -1), ("minutes", float("inf")),
])
def test_missing_model_data_is_not_silently_dropped(client, payload, loaded, teams, field, value):
    teams[10]["players"][0][field] = value
    assert client.post("/api/trade/analyze", json=payload).status_code == 422


def test_zero_minutes_allowed_but_empty_rotation_rejected(client, payload, loaded, teams):
    teams[10]["players"][0]["minutes"] = 0
    assert client.post("/api/trade/analyze", json=payload).status_code == 200
    for player in teams[10]["players"]:
        player["minutes"] = 0
    assert client.post("/api/trade/analyze", json=payload).status_code == 422


def test_empty_after_roster_rejected(client, payload, loaded):
    payload["team_a_sends"]["player_ids"] = list(range(1, 13))
    payload["team_b_sends"]["player_ids"] = []
    assert client.post("/api/trade/analyze", json=payload).status_code == 422


@pytest.mark.parametrize("value", [None, "NaN", "Infinity", "-1", True, "bad"])
def test_missing_actual_salary_does_not_block_wins(client, payload, loaded, teams, value):
    teams[10]["players"][1]["actual_salary"] = value
    response = client.post("/api/trade/analyze", json=payload)
    assert response.status_code == 200
    salary = response.json["data"]["teams"][0]["payroll"]
    assert salary["before"] is None
    assert salary["after"] is None
    assert salary["missing_actual_before"] == [2]
    assert salary["missing_actual_after"] == [2]


def test_zero_salary_is_available_and_negative_difference_is_preserved():
    before = [{"player_id": 1, "actual_salary": "0"}, {"player_id": 2, "actual_salary": "0.30"}]
    result = payroll(before, before[:1], [{"player_id": 3}], {3: "0.10"})
    assert result["before"] == "0.30"
    assert result["after"] == "0.10"
    assert result["net_difference"] == "-0.20"


def test_missing_outgoing_actual_salary_does_not_hide_complete_after_total():
    before = [{"player_id": 1, "actual_salary": None}, {"player_id": 2, "actual_salary": "100"}]
    result = payroll(before, before[1:], [{"player_id": 3}], {3: "50"})
    assert result["before"] is None
    assert result["after"] == "150.00"
    assert result["net_difference"] is None


@pytest.mark.parametrize("estimate", [None, "NaN", "-20"])
def test_missing_or_invalid_estimate_is_not_replaced_with_actual_salary(estimate):
    original = [{"player_id": 1, "actual_salary": "100"}]
    incoming = [{"player_id": 2, "actual_salary": "200"}]
    result = payroll(original, original, incoming, {2: estimate})
    assert result["before"] == "100.00"
    assert result["after"] is None
    assert result["net_difference"] is None
    assert result["missing_estimated_after"] == [2]


def test_database_failure_is_sanitized(client, payload, monkeypatch):
    monkeypatch.setattr(trades, "load_trade_rosters", MagicMock(side_effect=psycopg2.OperationalError("secret")))
    response = client.post("/api/trade/analyze", json=payload)
    assert response.status_code == 503
    assert "secret" not in response.get_data(as_text=True)


def test_roster_loader_binds_ids_and_preserves_missing_salary(monkeypatch):
    rows = [{
        "team_id": team_id, "abbreviation": "AAA", "team_name": "Team",
        "matched_season_id": 1, "player_id": team_id, "name": "Player",
        "lebron": 1, "minutes": 100, "actual_salary": "999",
    } for team_id in (10, 20)]
    query = MagicMock(return_value=rows)
    monkeypatch.setattr(trade_data, "query", query)
    result = trade_data.load_trade_rosters([10, 20], 1)
    assert query.call_args.args[1] == (1, 1, [10, 20])
    assert result[10]["players"][0]["actual_salary"] is None


@pytest.mark.parametrize("rows,code", [
    ([], 404),
    ([{"team_id": 10, "matched_season_id": None}, {"team_id": 20, "matched_season_id": None}], 404),
    ([{"team_id": i, "matched_season_id": 1, "abbreviation": "AAA", "team_name": "Team", "player_id": None} for i in (10, 20)], 422),
])
def test_missing_teams_season_or_roster(client, payload, monkeypatch, rows, code):
    monkeypatch.setattr(trade_data, "query", lambda *args: rows)
    assert client.post("/api/trade/analyze", json=payload).status_code == code
