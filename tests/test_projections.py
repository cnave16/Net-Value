"""Exercise the win adapter with database fixtures and Chase's real calculation."""

from decimal import Decimal
from unittest.mock import MagicMock

import psycopg2
import pytest

from backend import create_app, database
from backend.routes import projections


@pytest.fixture
def client():
    return create_app({"TESTING": True, "DATABASE_URL": None}).test_client()


@pytest.fixture
def payload():
    return {"player_ids": list(range(1, 13)), "season_id": 7}


@pytest.fixture
def rows():
    return [
        {"player_id": player_id, "lebron": Decimal("1"), "minutes": Decimal("100")}
        for player_id in range(1, 13)
    ]


def test_projection_uses_api_connection_and_real_model(payload, rows, monkeypatch):
    # Mock only the driver so this also checks connection reuse and bound SQL.
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = rows
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(database.psycopg2, "connect", connect)
    app = create_app({"TESTING": True, "DATABASE_URL": "postgresql://api-test"})
    response = app.test_client().post("/api/projections/wins", json=payload)
    assert response.status_code == 200
    assert response.json["data"] == pytest.approx({
        "projected_wins": 31.10105, "team_lebron": 1,
        "top10_std": 0, "positive_share": 1, "top3_share": 0.25,
    })
    assert response.json["meta"] == payload
    connect.assert_called_once_with("postgresql://api-test", connect_timeout=5)
    connection.set_session.assert_called_once_with(readonly=True)
    sql, params = cursor.execute.call_args.args
    assert params == (7, list(range(1, 13)))
    assert "p.player_id = ANY(%s)" in sql
    assert "ps.season_id = %s" in sql
    assert "SUM(pts.minutes_played)" in sql
    connection.close.assert_called_once()


@pytest.mark.parametrize("changes", [
    {"player_ids": []}, {"player_ids": list(range(1, 12))},
    {"player_ids": list(range(1, 17))}, {"player_ids": [1] * 12},
    {"player_ids": [True] + list(range(2, 13))},
    {"player_ids": ["1"] + list(range(2, 13))},
    {"player_ids": [0] + list(range(2, 13))},
    {"player_ids": [2147483648] + list(range(2, 13))},
    {"season_id": True}, {"season_id": "7"}, {"season_id": 0},
    {"season_id": 1.5}, {"season_id": 2147483648}, {"extra": 1},
])
def test_invalid_requests_never_query_database(client, payload, changes, monkeypatch):
    query = MagicMock()
    monkeypatch.setattr(projections, "query", query)
    response = client.post("/api/projections/wins", json={**payload, **changes})
    assert response.status_code == 400
    assert response.json["error"]["code"] == "BAD_REQUEST"
    query.assert_not_called()


@pytest.mark.parametrize("body", ["null", "[]", "{}", '{"season_id":7}', "{"])
def test_missing_or_malformed_body(client, body):
    response = client.post("/api/projections/wins", data=body, content_type="application/json")
    assert response.status_code == 400
    assert response.json["data"] is None


def test_missing_players_do_not_reach_model(client, payload, rows, monkeypatch):
    monkeypatch.setattr(projections, "query", lambda *args: rows[:-1])
    model = MagicMock()
    monkeypatch.setattr(projections, "project_wins", model)
    response = client.post("/api/projections/wins", json=payload)
    assert response.status_code == 422
    assert "[12]" in response.json["error"]["message"]
    model.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("lebron", None), ("lebron", float("nan")), ("lebron", float("inf")),
    ("minutes", None), ("minutes", 0), ("minutes", -1), ("minutes", float("nan")),
    ("minutes", float("inf")),
])
def test_incomplete_season_data_never_reaches_model(client, payload, rows, field, value, monkeypatch):
    rows[0][field] = value
    monkeypatch.setattr(projections, "query", lambda *args: rows)
    model = MagicMock()
    monkeypatch.setattr(projections, "project_wins", model)
    response = client.post("/api/projections/wins", json=payload)
    assert response.status_code == 422
    assert response.json["error"]["code"] == "UNPROCESSABLE_ENTITY"
    assert "season 7: [1]" in response.json["error"]["message"]
    model.assert_not_called()


def test_database_failure_is_sanitized(client, payload, monkeypatch):
    monkeypatch.setattr(projections, "query", MagicMock(side_effect=psycopg2.OperationalError("secret")))
    response = client.post("/api/projections/wins", json=payload)
    assert response.status_code == 503
    assert "secret" not in response.get_data(as_text=True)
