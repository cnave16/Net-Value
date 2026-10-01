# Check API responses and database cleanup without contacting a real database.

from unittest.mock import MagicMock

import psycopg2
import pytest

from backend import create_app
from backend import database
from backend.routes import catalog


@pytest.fixture
def app():
    return create_app({"TESTING": True, "DATABASE_URL": None})


@pytest.fixture
def client(app):
    return app.test_client()


def test_health_does_not_require_database(client):
    assert client.get("/api/health").json == {
        "data": {"status": "ok"}, "error": None, "meta": {}
    }
    assert client.get("/api/health/db").status_code == 503


@pytest.mark.parametrize("url", [
    "/api/players?page=0", "/api/players?page=abc", "/api/players?limit=101",
    "/api/players?team=BOS", "/api/players?season_id=-1",
    "/api/players?team=INVALID&season_id=1",
])
def test_invalid_filters_fail_before_database_access(client, url):
    response = client.get(url)
    assert response.status_code == 400
    assert response.json["error"]["code"] == "BAD_REQUEST"


def test_search_is_bound_and_missing_values_are_null(client, monkeypatch):
    # Replace the query so we can inspect SQL and values without running them.
    query = MagicMock(return_value=[{
        "id": 1, "name": "Sample Player", "external_id": None, "total": 1
    }])
    monkeypatch.setattr(catalog, "query", query)
    response = client.get("/api/players", query_string={
        "search": "O'Neal%_", "team": "bos", "season_id": 2
    })
    assert response.status_code == 200
    sql, params = query.call_args.args
    assert "O'Neal" not in sql
    assert params == ("%O'Neal\\%\\_%", 2, "BOS", 20, 0)
    assert response.json["data"][0]["salary"] is None
    assert response.json["data"][0]["team"] is None
    assert response.json["meta"]["total"] == 1


def test_empty_page_keeps_total(client, monkeypatch):
    # The SQL returns a count-only row when the requested page is empty.
    monkeypatch.setattr(catalog, "query", lambda *args: [{"id": None, "total": 21}])
    response = client.get("/api/players?page=3&limit=20")
    assert response.json["data"] == []
    assert response.json["meta"]["total_pages"] == 2


def test_missing_player_and_http_errors_share_envelope(client, monkeypatch):
    monkeypatch.setattr(catalog, "query", lambda *args: [])
    for url in ("/api/players/99", "/api/missing"):
        response = client.get(url)
        assert response.status_code == 404
        assert response.json["data"] is None
        assert response.json["error"]["code"] == "NOT_FOUND"
    response = client.post("/api/players")
    assert response.status_code == 405
    assert "GET" in response.headers["Allow"]


def test_database_failure_does_not_expose_connection(client, monkeypatch, caplog):
    def fail(*args):
        raise psycopg2.OperationalError("postgresql://user:secret@host/db")
    monkeypatch.setattr(catalog, "query", fail)
    response = client.get("/api/teams")
    assert response.status_code == 503
    assert response.json["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert "secret" not in response.get_data(as_text=True) + caplog.text


def test_connection_is_reused_and_closed(app, monkeypatch):
    # The app context lets us check reuse inside it and cleanup when it ends.
    connection = MagicMock()
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(database.psycopg2, "connect", connect)
    app.config["DATABASE_URL"] = "postgresql://test"
    with app.app_context():
        assert database.get_db() is connection
        assert database.get_db() is connection
        connect.assert_called_once_with("postgresql://test", connect_timeout=5)
        connection.set_session.assert_called_once_with(readonly=True)
        connection.cursor.return_value.__enter__.return_value.execute.assert_called_once_with(
            "SET LOCAL statement_timeout = 5000"
        )
    connection.close.assert_called_once()


@pytest.mark.parametrize("method,path", [
    ("post", "/api/valuation"), ("post", "/api/trade/validate"), ("get", "/api/picks")
])
def test_pending_features_do_not_claim_analysis(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 501
    assert response.json["error"]["code"] == "NOT_IMPLEMENTED"


def test_cors_allows_configured_frontend_only(client):
    # Browsers send this OPTIONS check before certain cross-origin requests.
    response = client.options("/api/trade/validate", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type",
    })
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    response = client.get("/api/health", headers={"Origin": "https://unconfigured.example"})
    assert "Access-Control-Allow-Origin" not in response.headers


@pytest.mark.parametrize("path", [
    "/api/players?season_id=2147483648",
    "/api/players/2147483648",
    "/api/players/0",
])
def test_invalid_database_ids_do_not_reach_sql(client, monkeypatch, path):
    query = MagicMock()
    monkeypatch.setattr(catalog, "query", query)
    response = client.get(path)
    assert response.status_code == 400
    assert response.json["error"]["code"] == "BAD_REQUEST"
    query.assert_not_called()


def test_cors_environment_accepts_spaces_and_empty_entries(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", " http://localhost:5173, , http://localhost:3000, ")
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()
    for origin in ("http://localhost:5173", "http://localhost:3000"):
        response = client.get("/api/health", headers={"Origin": origin})
        assert response.headers["Access-Control-Allow-Origin"] == origin
