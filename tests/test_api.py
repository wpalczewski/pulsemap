import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "API_KEY", "")
    with TestClient(main.app) as c:
        yield c


def test_public_endpoints_hide_access_code(client):
    aeds = client.get("/api/v1/aeds").json()
    assert aeds and all("access_code" not in a for a in aeds)
    assert any(a["has_access_code"] for a in aeds)

    csv_text = client.get("/api/v1/export/csv").text
    header = csv_text.lstrip("﻿").splitlines()[0]
    assert "access_code" not in header.split(",") and "has_access_code" in header

    gj = client.get("/api/v1/export/geojson").json()
    assert all("access_code" not in f["properties"] for f in gj["features"])
    assert all("access_code" not in a for a in client.get("/api/v1/export/json").json())


def test_dispatcher_still_gets_access_code(client):
    # Bydgoszcz, środa 10:00
    r = client.get("/api/v1/dispatcher/nearest",
                   params={"lat": 53.1235, "lon": 18.0085, "timestamp": "2026-11-25T10:00:00"})
    assert r.status_code == 200
    assert "access_code" in r.json()["nearest"][0]


def test_ingest_requires_api_key_when_configured(client, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "API_KEY", "sekret")
    rec = {"source_name": "T", "latitude": 52.0, "longitude": 21.0}
    assert client.post("/api/v1/ingest/json", json=rec).status_code == 401
    r = client.post("/api/v1/ingest/json", json=rec, headers={"X-API-Key": "sekret"})
    assert r.status_code == 200 and r.json()["valid"] == 1


def test_rescue_event_rejects_unknown_values(client):
    r = client.get("/api/v1/dispatcher/nearest",
                   params={"lat": 53.1235, "lon": 18.0085, "timestamp": "2026-11-25T10:00:00"})
    token = r.json()["rescue_token"]
    assert client.post(f"/api/v1/rescue/{token}/event", json={"event": "hacked"}).status_code == 422
    assert client.post(f"/api/v1/rescue/{token}/event", json={"event": "en_route"}).status_code == 200


def test_schema_xlsx_matches_portal_wykaz(client):
    from io import BytesIO
    from openpyxl import load_workbook
    from app.wykaz_aed import WYKAZ_COLUMNS
    wb = load_workbook(BytesIO(client.get("/api/v1/export/schema-xlsx").content))
    spec = wb["Zakres_danych"]
    assert [r[0] for r in spec.iter_rows(min_row=2, values_only=True)] == WYKAZ_COLUMNS
    tpl = wb["Wykaz_AED"]
    assert [c.value for c in tpl[1]] == WYKAZ_COLUMNS
    # kod do szafki nie jest częścią otwartego wykazu
    assert not any(str(c.value).lower() in ("access_code", "kod do szafki", "kod szafki") for c in tpl[1])


def test_public_aeds_have_hours_status_but_exports_dont(client):
    aeds = client.get("/api/v1/aeds").json()
    assert all(a["hours_status"] in ("open", "closed", "unknown") for a in aeds)
    seed = next(a for a in aeds if a["aed_id"] == "aed-byd-001")  # 24/7
    assert seed["hours_status"] == "open"
    header = client.get("/api/v1/export/csv").text.lstrip("﻿").splitlines()[0]
    assert "hours_status" not in header
    assert all("hours_status" not in a for a in client.get("/api/v1/export/json").json())


def test_now_pl_uses_warsaw_time():
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    import app.main as main
    expected = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Warsaw")).replace(tzinfo=None)
    got = main.now_pl()
    assert got.tzinfo is None
    assert abs((got - expected).total_seconds()) < 5
