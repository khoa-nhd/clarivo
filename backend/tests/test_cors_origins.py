"""Which browser origins the backend accepts.

When the frontend lives on Vercel and this backend is reached over a tunnel,
CORS is the whole handshake between them. A refused origin surfaces in the
browser as a failed fetch with no readable detail, which the frontend then
reports as "voice/visual offline" - indistinguishable from the machine being
switched off. These tests pin the two ways an origin gets allowed.
"""

import importlib
import sys
import types

_ov = types.ModuleType("openvino")
_ov.Core = object
sys.modules.setdefault("openvino", _ov)

import pytest
from starlette.testclient import TestClient


def _load_app(monkeypatch, *, origins: str = "", regex: str = ""):
    """Import main.py with the CORS environment we want.

    The middleware is configured at import time, so the module has to be
    reloaded for a change to take effect.
    """
    monkeypatch.setenv("ALLOWED_ORIGINS", origins)
    monkeypatch.setenv("ALLOWED_ORIGIN_REGEX", regex)
    # load_dotenv() must not put the developer's own .env back over the top.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    sys.modules.pop("main", None)
    return importlib.import_module("main")


def _allowed(client: TestClient, origin: str) -> bool:
    response = client.get("/api/health", headers={"Origin": origin})
    return response.headers.get("access-control-allow-origin") == origin


def test_localhost_is_always_allowed(monkeypatch):
    main = _load_app(monkeypatch)
    with TestClient(main.app) as client:
        assert _allowed(client, "http://localhost:5173")


def test_a_named_origin_is_allowed(monkeypatch):
    main = _load_app(monkeypatch, origins="https://clarivo-kohl.vercel.app")
    with TestClient(main.app) as client:
        assert _allowed(client, "https://clarivo-kohl.vercel.app")


def test_an_unrelated_origin_is_refused(monkeypatch):
    main = _load_app(monkeypatch, origins="https://clarivo-kohl.vercel.app")
    with TestClient(main.app) as client:
        assert not _allowed(client, "https://someone-elses-site.example")


def test_a_preview_deployment_is_allowed_by_the_pattern(monkeypatch):
    """The reason the pattern exists: Vercel renames every deployment."""
    main = _load_app(monkeypatch, regex=r"https://clarivo-[a-z0-9-]+\.vercel\.app")
    with TestClient(main.app) as client:
        assert _allowed(client, "https://clarivo-git-main-someone.vercel.app")


def test_the_pattern_does_not_open_the_backend_to_every_vercel_site(monkeypatch):
    main = _load_app(monkeypatch, regex=r"https://clarivo-[a-z0-9-]+\.vercel\.app")
    with TestClient(main.app) as client:
        assert not _allowed(client, "https://unrelated-project.vercel.app")


def test_an_empty_pattern_is_treated_as_unset(monkeypatch):
    """An empty env var must not become a regex that matches every origin."""
    main = _load_app(monkeypatch, regex="   ")
    with TestClient(main.app) as client:
        assert not _allowed(client, "https://anything.example")


@pytest.mark.parametrize("method", ["POST"])
def test_preflight_is_answered_for_uploads(monkeypatch, method):
    main = _load_app(monkeypatch, origins="https://clarivo-kohl.vercel.app")
    with TestClient(main.app) as client:
        response = client.options(
            "/api/analyze/vision",
            headers={
                "Origin": "https://clarivo-kohl.vercel.app",
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://clarivo-kohl.vercel.app"
