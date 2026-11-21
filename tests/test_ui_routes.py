import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    import app.main as main
    with TestClient(main.app) as c:
        yield c


@pytest.mark.parametrize("path", ["/", "/mapa", "/dispatcher", "/submit", "/opendata"])
def test_pages_ok(client, path):
    assert client.get(path).status_code == 200


def test_brand_replaces_gov_imitation(client):
    html = client.get("/").text
    assert "Serwis Rzeczypospolitej Polskiej" not in html
    assert "PolishEagleCrest" not in html
    assert "Otwórz AED" in html
    title = re.search(r"<title>(.*?)</title>", html, re.S).group(1).strip()
    assert title.startswith("Otwórz AED")


def test_witness_screen_branded(client):
    r = client.get("/api/v1/dispatcher/nearest",
                   params={"lat": 53.1235, "lon": 18.0085, "timestamp": "2026-11-25T10:00:00"})
    token = r.json()["rescue_token"]
    html = client.get(f"/go/{token}").text
    assert "mObywatel" not in html
    assert "Otwórz AED" in html
    assert "user-scalable=no" not in html
