"""Exercise multi-team transfers, salary comparisons, and the commissioner API."""

from copy import deepcopy
from decimal import Decimal
from unittest.mock import MagicMock

import psycopg2
import pytest

from backend import create_app
from backend.routes import trades
from backend.services import trade_data
from backend.services.trade_finances import cap_comparison, payroll
from backend.services.trades import analyze_trade, commissioner_dashboard, projection


def transfer(player, source, destination):
    return {"player_id": player, "from_team_id": source, "to_team_id": destination}


@pytest.fixture
def client():
    return create_app({"TESTING": True, "DATABASE_URL": None}).test_client()


@pytest.fixture
def payload():
    return {
        "season_id": 1, "team_ids": [10, 20, 30],
        "transfers": [transfer(1, 10, 20), transfer(13, 20, 30), transfer(25, 30, 10)],
    }


@pytest.fixture
def teams():
    return {
        team_id: {
            "id": team_id, "abbreviation": abbreviation, "name": abbreviation,
            "players": [{
                "player_id": player_id, "name": f"Player {player_id}",
                "lebron": Decimal(rating), "minutes": Decimal("100"),
                "actual_salary": Decimal(salary),
            } for player_id in range(start, start + 12)],
        }
        for team_id, abbreviation, start, rating, salary in (
            (10, "AAA", 1, "1", "1000000.10"),
            (20, "BBB", 13, "3", "2000000.20"),
            (30, "CCC", 25, "2", "3000000.30"),
        )
    }


@pytest.fixture
def caps():
    return trade_data.load_cap_context([10, 20, 30])


@pytest.fixture
def loaded(monkeypatch, teams):
    loader = MagicMock(return_value=teams)
    monkeypatch.setattr(trades, "load_trade_rosters", loader)
    return loader


@pytest.mark.parametrize("path", ["/api/trade/analyze", "/api/trade/validate"])
def test_three_team_cycle(client, payload, teams, caps, loaded, path):
    original = deepcopy(teams)
    response = client.post(path, json=payload)
    assert response.status_code == 200
    data = response.json["data"]
    assert data["analysis_available"] is True
    a, b, c = data["teams"]
    assert a["roster_after"] == list(range(2, 13)) + [25]
    assert b["roster_after"] == [1] + list(range(14, 25))
    assert c["roster_after"] == [13] + list(range(26, 37))
    assert a["projected_wins"]["before"] == pytest.approx(31.10105)
    assert b["projected_wins"]["before"] == pytest.approx(45.59065)
    assert a["projected_wins"]["after"] == pytest.approx(31.7047833333)
    assert a["payroll"]["before"] == "12000001.20"
    assert a["payroll"]["after"] == "14000001.40"
    assert a["payroll"]["net_difference"] == "2000000.20"
    assert a["salary_cap"]["before"] == "152960998.80"
    assert a["salary_cap"]["after"] == "150960998.60"
    assert a["salary_cap"]["net_difference"] == "-2000000.20"
    assert a["salary_cap"]["is_estimate"] is True
    for result in data["teams"]:
        wins, pct = result["projected_wins"], result["projected_win_percentage"]
        assert pct["after"] == pytest.approx(wins["after"] / 82 * 100)
        assert pct["net_difference"] == pytest.approx((wins["after"] - wins["before"]) / 82 * 100)
    assert sum(Decimal(t["payroll"]["net_difference"]) for t in data["teams"]) == 0
    assert data["legality"]["passes_supported_rules"] is True
    assert data["legality"]["is_legal"] is None
    assert response.json["meta"]["salary_source"] == "player_seasons.contract_value_assumed_annual_usd"
    assert teams == original
    loaded.assert_called_once_with([10, 20, 30], 1)


def test_fan_out_and_fan_in_are_order_independent(teams, caps):
    moves = [transfer(1, 10, 20), transfer(2, 10, 30), transfer(13, 20, 10), transfer(25, 30, 10)]
    forward = analyze_trade(teams, [10, 20, 30], moves, caps)
    reverse = analyze_trade(teams, [30, 20, 10], moves[::-1], caps)
    assert forward["teams"] == reverse["teams"][::-1]
    a = forward["teams"][0]
    assert a["incoming_player_ids"] == [13, 25]
    assert a["outgoing_player_ids"] == [1, 2]
    assert a["roster_after"] == list(range(3, 13)) + [13, 25]
    all_after = [p for team in forward["teams"] for p in team["roster_after"]]
    assert sorted(all_after) == list(range(1, 37))


def test_four_team_cycle_and_two_team_general_case(teams, caps):
    teams[40] = deepcopy(teams[10])
    teams[40]["id"] = 40
    for player in teams[40]["players"]:
        player["player_id"] += 36
    moves = [transfer(1, 10, 20), transfer(13, 20, 30), transfer(25, 30, 40), transfer(37, 40, 10)]
    result = analyze_trade(teams, [10, 20, 30, 40], moves, caps)
    assert len(result["teams"]) == 4
    assert result["teams"][3]["incoming_player_ids"] == [25]
    result = analyze_trade(teams, [10, 20], [transfer(1, 10, 20)], caps)
    assert len(result["teams"][0]["roster_after"]) == 11
    assert len(result["teams"][1]["roster_after"]) == 13


@pytest.mark.parametrize("changes", [
    {"season_id": True}, {"season_id": "1"}, {"season_id": 2147483648}, {"extra": 1},
    {"team_ids": [10]}, {"team_ids": [10, 10]}, {"team_ids": "10,20"},
    {"team_ids": [True, 20]}, {"team_ids": [0, 20]}, {"team_ids": list(range(1, 32))},
    {"transfers": []}, {"transfers": None}, {"transfers": [{}]},
    {"transfers": [transfer(1, 10, 10)]}, {"transfers": [transfer(1, 10, 99)]},
    {"transfers": [transfer(True, 10, 20)]}, {"transfers": [transfer(0, 10, 20)]},
    {"transfers": [transfer(1.5, 10, 20)]},
    {"transfers": [transfer(1, 10, 20), transfer(1, 20, 30)]},
    {"transfers": [{**transfer(1, 10, 20), "salary": 1}]},
    {"transfers": [{**transfer(1, 10, 20), "pick_ids": []}]},
    {"transfers": [transfer(1, 10, 20)]},  # Team 30 would be uninvolved.
    {"transfers": [transfer(i, 10, 20) for i in range(1, 102)]},
])
def test_bad_requests_never_load_rosters(client, payload, loaded, changes):
    assert client.post("/api/trade/analyze", json={**payload, **changes}).status_code == 400
    loaded.assert_not_called()


def test_legacy_two_team_shape_removed(client, loaded):
    body = {"season_id": 1, "team_a_id": 10, "team_b_id": 20,
            "team_a_sends": {"player_ids": [1]}, "team_b_sends": {"player_ids": [13]}}
    assert client.post("/api/trade/analyze", json=body).status_code == 400
    loaded.assert_not_called()


@pytest.mark.parametrize("body", ["null", "[]", "{}", "{"])
def test_malformed_json(client, loaded, body):
    assert client.post("/api/trade/analyze", data=body, content_type="application/json").status_code == 400
    loaded.assert_not_called()


def test_json_required(client, loaded):
    assert client.post("/api/trade/analyze", data="{}").status_code == 415
    loaded.assert_not_called()


def test_wrong_roster_blocks_projection(client, payload, loaded, monkeypatch):
    payload["transfers"][0]["player_id"] = 999
    model = MagicMock()
    monkeypatch.setattr("backend.services.trades.project_wins", model)
    data = client.post("/api/trade/analyze", json=payload).json["data"]
    assert not data["analysis_available"]
    assert data["teams"] == []
    assert data["legality"]["checks"][1]["player_ids"] == [999]
    model.assert_not_called()


def test_overlap_between_later_teams_blocks_trade(client, payload, loaded, teams):
    teams[30]["players"].append(deepcopy(teams[20]["players"][0]))
    data = client.post("/api/trade/analyze", json=payload).json["data"]
    assert not data["analysis_available"]
    assert data["legality"]["checks"][0]["player_ids"] == [13]


@pytest.mark.parametrize("field,value", [
    ("lebron", None), ("lebron", float("nan")), ("lebron", float("inf")),
    ("minutes", None), ("minutes", -1), ("minutes", float("inf")),
])
def test_unusable_model_data(client, payload, loaded, teams, field, value):
    teams[10]["players"][0][field] = value
    assert client.post("/api/trade/analyze", json=payload).status_code == 422


def test_zero_minutes_allowed_but_empty_rotation_rejected(client, payload, loaded, teams):
    teams[10]["players"][0]["minutes"] = 0
    assert client.post("/api/trade/analyze", json=payload).status_code == 200
    for player in teams[10]["players"]:
        player["minutes"] = 0
    assert client.post("/api/trade/analyze", json=payload).status_code == 422


def test_empty_after_roster_rejected(client, payload, loaded):
    payload["transfers"] = [transfer(i, 10, 20) for i in range(1, 13)] + [transfer(13, 20, 30)]
    assert client.post("/api/trade/analyze", json=payload).status_code == 422


@pytest.mark.parametrize("value", [None, "NaN", "Infinity", "-1", True, "bad"])
def test_missing_salary_keeps_wins_and_marks_unknown(client, payload, loaded, teams, value):
    teams[10]["players"][1]["actual_salary"] = value
    response = client.post("/api/trade/analyze", json=payload)
    assert response.status_code == 200
    data = response.json["data"]
    assert data["legality"]["passes_supported_rules"] is None
    salary = data["teams"][0]["payroll"]
    assert salary["before"] is None and salary["after"] is None
    assert salary["missing_actual_before"] == [2]
    assert salary["missing_actual_after"] == [2]
    assert data["teams"][0]["salary_cap"]["before"] is None


def test_salary_failure_does_not_hide_projections(client, payload, loaded, teams):
    for p in teams[10]["players"]:
        p["actual_salary"] = "20000000"
    teams[30]["players"][0]["actual_salary"] = "30000000"
    data = client.post("/api/trade/analyze", json=payload).json["data"]
    assert data["analysis_available"]
    assert data["legality"]["status"] == "failed"
    assert data["legality"]["passes_supported_rules"] is False
    assert data["teams"][0]["salary_cap"]["after"].startswith("-")


def test_exact_payroll_and_missing_outgoing():
    before = [{"player_id": 1, "actual_salary": "0"}, {"player_id": 2, "actual_salary": "0.30"}]
    after = [before[0], {"player_id": 3, "actual_salary": "0.10"}]
    result = payroll(before, after)
    assert result["before"] == "0.30" and result["after"] == "0.10"
    assert result["net_difference"] == "-0.20"
    before[1]["actual_salary"] = None
    result = payroll(before, after)
    assert result["before"] is None and result["after"] == "0.10"


def test_cap_missing_settings_and_known_charges():
    salaries = {"before": "100", "after": "120"}
    assert cap_comparison(salaries, {})["before"] is None
    result = cap_comparison(salaries, {"salary_cap": "110", "other_cap_charges": "5", "charges_confirmed": True})
    assert result["before"] == "5.00" and result["after"] == "-15.00"
    assert result["net_difference"] == "-20.00"


def test_database_failure_sanitized(client, payload, monkeypatch):
    monkeypatch.setattr(trades, "load_trade_rosters", MagicMock(side_effect=psycopg2.OperationalError("secret")))
    response = client.post("/api/trade/analyze", json=payload)
    assert response.status_code == 503
    assert "secret" not in response.get_data(as_text=True)


def test_loader_binds_ids_and_maps_contract_value(monkeypatch):
    rows = [{"team_id": i, "abbreviation": "AAA", "team_name": "Team", "matched_season_id": 1,
             "player_id": i, "name": "Player", "lebron": 1, "minutes": 100, "actual_salary": "999"}
            for i in (10, 20, 30)]
    query = MagicMock(return_value=rows)
    monkeypatch.setattr(trade_data, "query", query)
    result = trade_data.load_trade_rosters([10, 20, 30], 1)
    assert query.call_args.args[1] == (1, 1, [10, 20, 30])
    assert "to_jsonb(ps)->>'contract_value'" in query.call_args.args[0]
    assert result[10]["players"][0]["actual_salary"] == "999"


@pytest.mark.parametrize("rows,code", [
    ([], 404),
    ([{"team_id": i, "matched_season_id": None} for i in (10, 20, 30)], 404),
    ([{"team_id": i, "matched_season_id": 1, "abbreviation": "AAA", "team_name": "Team", "player_id": None}
      for i in (10, 20, 30)], 422),
])
def test_missing_teams_season_or_roster(client, payload, monkeypatch, rows, code):
    monkeypatch.setattr(trade_data, "query", lambda *args: rows)
    assert client.post("/api/trade/analyze", json=payload).status_code == code


@pytest.mark.parametrize("data_season_id", [1, 999])
def test_source_season_does_not_change_2026_trade_rules(client, payload, loaded, data_season_id):
    payload["season_id"] = data_season_id
    response = client.post("/api/trade/analyze", json=payload)
    assert response.status_code == 200
    loaded.assert_called_once_with([10, 20, 30], data_season_id)
    assert response.json["meta"]["data_season_id"] == data_season_id
    assert response.json["meta"]["trade_season"] == {"start_year": 2026, "end_year": 2027}
    cap = response.json["data"]["teams"][0]["salary_cap"]
    assert cap["limit"] == "164961000.00"
    assert cap["minimum_team_salary"] == "148465000.00"
    assert cap["first_apron"] == "209015000.00"
    assert cap["second_apron"] == "221686000.00"
    assert cap["before"] == "152960998.80"
    assert cap["after"] == "150960998.60"


def test_target_query_scoped_to_season(monkeypatch):
    query = MagicMock(return_value=[])
    monkeypatch.setattr(trade_data, "query", query)
    assert trade_data.load_target_candidates(7) == []
    assert query.call_args.args[1] == (7,)
    assert "SUM(pts.minutes_played)" in query.call_args.args[0]


def candidates(teams):
    return [{**p, "team_ids": [team_id]} for team_id, team in teams.items() for p in team["players"]]


def test_dashboard_top_15_matches_independent_projections(teams, caps):
    pool = candidates(teams)
    original = deepcopy((teams, pool))
    result = commissioner_dashboard(teams[10], pool[::-1], caps[10])
    expected = sorted(
        [(projection(teams[10]["players"] + [p]), p["player_id"]) for p in pool if p["team_ids"] != [10]],
        key=lambda item: (-item[0], item[1]),
    )[:15]
    assert [t["player"]["player_id"] for t in result["targets"]] == [item[1] for item in expected]
    assert result["eligible_target_count"] == 24
    assert len(result["targets"]) == 15
    assert isinstance(result["roster"][0]["lebron"], float)
    assert result["roster"][0]["actual_salary"] == "1000000.10"
    assert (teams, pool) == original


def test_dashboard_skips_bad_candidates_and_reports_short_list(teams, caps):
    pool = candidates(teams)[12:15]
    pool[0]["team_ids"] = [20, 30]
    pool[1]["lebron"] = None
    result = commissioner_dashboard(teams[10], pool, caps[10])
    assert len(result["targets"]) == 2
    assert result["targets"][0]["player"]["player_id"] == 13
    assert result["targets"][0]["team_id"] is None
    assert result["targets"][0]["team_ids"] == [20, 30]
    assert result["skipped_targets"] == [
        {"player_id": 14, "reason": "unusable_projection_data"},
    ]


def test_dashboard_route(client, loaded, teams, monkeypatch):
    loader = MagicMock(return_value=candidates(teams))
    monkeypatch.setattr(trades, "load_target_candidates", loader)
    response = client.get("/api/trade/teams/10?season_id=1")
    assert response.status_code == 200
    assert len(response.json["data"]["targets"]) == 15
    assert response.json["data"]["salary_cap"]["limit"] == "164961000.00"
    assert response.json["meta"]["data_season_id"] == 1
    assert response.json["meta"]["trade_season"] == {"start_year": 2026, "end_year": 2027}
    assert "without_outgoing" in response.json["meta"]["target_basis"]
    loaded.assert_called_once_with([10], 1)
    loader.assert_called_once_with(1)


@pytest.mark.parametrize("suffix", ["", "?season_id=0", "?season_id=abc", "?season_id=2147483648",
                                    "?season_id=1&season_id=2", "?season_id=1&extra=x"])
def test_dashboard_bad_arguments(client, loaded, suffix):
    assert client.get("/api/trade/teams/10" + suffix).status_code == 400
    loaded.assert_not_called()
