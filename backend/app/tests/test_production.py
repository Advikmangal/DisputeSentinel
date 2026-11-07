import secrets

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app import db


@pytest.mark.parametrize("secret", ["", "x" * 31, "é" * 16, "replace-with-a-long-random-secret-value"])
def test_production_startup_rejects_invalid_jwt(secret):
    settings = Settings(_env_file=None, environment="production", jwt_secret=secret,
                        frontend_origin="https://frontend.example.invalid")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        with TestClient(create_app(settings)):
            pass


def test_production_starts_with_valid_config(monkeypatch):
    calls = []
    monkeypatch.setattr("app.main.seed_on_startup", lambda settings: calls.append(settings))
    settings = Settings(_env_file=None, environment="production", jwt_secret=secrets.token_hex(32),
                        frontend_origin="https://frontend.example.invalid")
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/api/transactions").status_code == 401
    assert calls == [settings]


def test_cors_allows_only_configured_origin_including_auth_preflight():
    origin = "https://frontend.example.invalid"
    settings = Settings(_env_file=None, environment="test", frontend_origin=origin)
    with TestClient(create_app(settings)) as client:
        headers = {"Origin": origin, "Access-Control-Request-Method": "POST",
                   "Access-Control-Request-Headers": "authorization,content-type,idempotency-key"}
        response = client.options("/api/payments/create-order", headers=headers)
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        for other in ("https://other.example.invalid", origin + ".evil.invalid", "null"):
            response = client.options("/api/payments/create-order", headers={**headers, "Origin": other})
            assert response.status_code == 400
            assert "access-control-allow-origin" not in response.headers
        response = client.get("/api/transactions", headers={"Origin": origin})
        assert response.status_code == 401
        assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", ["*", "https://*.example.invalid", "https://example.invalid/path", "https://example.invalid/", "https://example.invalid?x=1", "https://example.invalid#x", "null"])
def test_invalid_cors_origins_rejected(origin):
    with pytest.raises(ValidationError, match="FRONTEND_ORIGIN"):
        Settings(_env_file=None, frontend_origin=origin)


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_database_url_normalizes_render_scheme_without_losing_components(monkeypatch, scheme):
    settings = Settings(_env_file=None, database_url=f"{scheme}://example:synthetic%40value@db.example.invalid:5432/demo?sslmode=require")
    monkeypatch.setattr(db, "get_settings", lambda: settings)
    url = db.database_url()
    assert url.drivername == "postgresql+psycopg"
    assert url.username == "example" and url.password == "synthetic@value"
    assert url.host == "db.example.invalid" and url.port == 5432
    assert url.database == "demo" and url.query["sslmode"] == "require"
