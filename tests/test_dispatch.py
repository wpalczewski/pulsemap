from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.database import ensure_demo_records
from app.dispatch import scan_radius
from app.etl import ingest_records

WED_2030 = datetime(2026, 11, 25, 20, 30)
CENTRUM = (53.1235, 18.0000)


@pytest.fixture
def demo_db(db):
    ensure_demo_records(db)
    return db


def _add(db, sid, lat, lon, **kw):
    ingest_records(db, [{"source_name": "T", "source_id": sid, "latitude": lat, "longitude": lon, **kw}])


def test_scan_classifies_states(demo_db):
    lat, lon = 53.2000, 18.2000
    _add(demo_db, "open", lat + 0.0005, lon, opening_hours="24/7")
    _add(demo_db, "day", lat + 0.0010, lon, opening_hours="Mo-Fr 08:00-18:00")
    _add(demo_db, "broken", lat + 0.0015, lon, opening_hours="24/7", status="temporarily_unavailable")
    _add(demo_db, "far", lat + 0.0200, lon, opening_hours="24/7")  # ~2,2 km
    res = scan_radius(demo_db, lat, lon, 400, WED_2030)
    states = {a.opening_hours + "|" + a.state for a in res.in_radius}
    assert "24/7|open" in states
    closed = next(a for a in res.in_radius if a.state == "closed")
    assert "Mo-Fr 08:00-18:00" in closed.reason
    assert any(a.state == "unavailable" for a in res.in_radius)
    assert all(a.distance_m <= 400 for a in res.in_radius)
    assert len(res.in_radius) == 3
    assert res.scenario == "AED_FOUND"


def test_scan_scenario_b_when_nothing_open(demo_db):
    lat, lon = 53.2000, 18.2000
    _add(demo_db, "day", lat + 0.0010, lon, opening_hours="Mo-Fr 08:00-18:00")
    _add(demo_db, "far", lat + 0.0200, lon, opening_hours="24/7")
    res = scan_radius(demo_db, lat, lon, 400, WED_2030)
    assert res.scenario == "CPR_ONLY"
    assert res.candidates == []
    assert res.nearest_open_outside_m is not None and res.nearest_open_outside_m > 400


def test_candidates_prefer_open_over_unknown(demo_db):
    lat, lon = 53.2000, 18.2000
    _add(demo_db, "unk", lat + 0.0003, lon, opening_hours="sunrise-sunset")
    _add(demo_db, "open", lat + 0.0020, lon, opening_hours="24/7")
    res = scan_radius(demo_db, lat, lon, 400, WED_2030)
    assert res.candidates[0].state == "open"
    assert res.candidates[1].state == "unknown"


def test_round_trip(demo_db):
    res = scan_radius(demo_db, *CENTRUM, 400, WED_2030)
    c = res.candidates[0]
    assert c.round_trip_s == pytest.approx(2 * c.walk_time_s)


def test_demo_records_idempotent(db):
    ensure_demo_records(db)
    n1 = db.execute("SELECT COUNT(*) FROM aed WHERE aed_id LIKE 'aed-demo-%'").fetchone()[0]
    ensure_demo_records(db)
    rows = [dict(r) for r in db.execute("SELECT * FROM aed WHERE aed_id LIKE 'aed-demo-%'")]
    assert len(rows) == n1 >= 2
    assert any(r["access_code"] == "1912" for r in rows)
    assert any(r["opening_hours"] == "Mo-Fr 08:00-18:00" for r in rows)
    assert sum(len(r["location_description"]) > 40 for r in rows) >= 2


@pytest.fixture
def client():
    import app.main as main
    with TestClient(main.app) as c:
        yield c


def _preset(client, pid):
    presets = client.get("/api/v1/dispatcher/presets").json()
    return next(p for p in presets if p["id"] == pid)


def _scan(client, p, radius):
    params = {"lat": p["lat"], "lon": p["lon"], "radius_m": radius}
    if p["timestamp"]:
        params["timestamp"] = p["timestamp"]
    return client.get("/api/v1/dispatcher/scan", params=params)


def test_presets_produce_expected_scenarios(client):
    r = _scan(client, _preset(client, "centrum"), 400).json()
    assert r["scenario"] == "AED_FOUND"
    assert r["candidates"][0]["opening_hours"] == "24/7"
    assert r["candidates"][0]["has_access_code"] is True  # sam kod dopiero w sesji

    r = _scan(client, _preset(client, "biuro"), 400).json()
    assert any(a["state"] == "closed" and a["opening_hours"] == "Mo-Fr 08:00-18:00" for a in r["in_radius"])
    assert r["scenario"] == "CPR_ONLY"

    r = _scan(client, _preset(client, "obrzeza"), 800).json()
    assert r["scenario"] == "CPR_ONLY"


@pytest.mark.parametrize("radius", [150, 900])
def test_scan_radius_bounds(client, radius):
    r = client.get("/api/v1/dispatcher/scan", params={"lat": 53.12, "lon": 18.0, "radius_m": radius})
    assert r.status_code == 422


# ── Task 2: sesja ze scenariuszem ──────────────────────────────────────
def _session(client, pid, radius=400, **extra):
    p = _preset(client, pid)
    body = {"lat": p["lat"], "lon": p["lon"], "radius_m": radius, "timestamp": p["timestamp"], **extra}
    return client.post("/api/v1/dispatcher/session", json=body)


def test_session_aed_found(client):
    from app.database import get_db
    r = _session(client, "centrum")
    assert r.status_code == 200
    d = r.json()
    assert d["scenario"] == "AED_FOUND"
    assert d["rescue_url"] in d["sms_text"]
    assert "1912" in d["sms_text"]
    assert d["aed"]["aed_id"] == "aed-demo-centrum"
    row = get_db().execute("SELECT radius_m, scenario FROM rescue_session WHERE token = ?", (d["token"],)).fetchone()
    assert row["radius_m"] == 400 and row["scenario"] == "AED_FOUND"


def test_session_cpr_only(client):
    d = _session(client, "obrzeza", radius=800).json()
    assert d["scenario"] == "CPR_ONLY"
    assert d["aed"] is None
    assert "RKO" in d["sms_text"]


def test_fallback_to_second_then_cpr(client):
    from app.database import get_db
    db = get_db()
    lat, lon = 53.3000, 18.3000
    _add(db, "fb1", lat + 0.0005, lon, opening_hours="24/7")
    _add(db, "fb2", lat + 0.0015, lon, opening_hours="24/7")
    d = client.post("/api/v1/dispatcher/session", json={"lat": lat, "lon": lon, "radius_m": 400}).json()
    token = d["token"]
    r1 = client.post(f"/go/{token}/report-unavailable").json()
    assert r1["switched"] is True and r1["scenario"] == "AED_FOUND"
    r2 = client.post(f"/go/{token}/report-unavailable").json()
    assert r2["scenario"] == "CPR_ONLY"
    r3 = client.post(f"/go/{token}/report-unavailable")
    assert r3.status_code == 200 and r3.json()["scenario"] == "CPR_ONLY"
    # przez endpoint zdarzeń też
    r4 = client.post(f"/api/v1/rescue/{token}/event", json={"event": "unavailable"}).json()
    assert r4["scenario"] == "CPR_ONLY"


def test_public_url_warning(client, monkeypatch):
    monkeypatch.delenv("PULSEMAP_PUBLIC_URL", raising=False)
    d = _session(client, "centrum").json()
    assert d["public_url_warning"]
    monkeypatch.setenv("PULSEMAP_PUBLIC_URL", "http://192.168.1.20:8000/")
    d = _session(client, "centrum").json()
    assert d["rescue_url"].startswith("http://192.168.1.20:8000/go/")
    assert d["public_url_warning"] is None


def test_expired_session(client):
    from app.database import get_db
    token = _session(client, "centrum").json()["token"]
    db = get_db()
    db.execute("UPDATE rescue_session SET created_at = datetime('now', '-7 hours') WHERE token = ?", (token,))
    db.commit()
    assert client.post(f"/go/{token}/report-unavailable").status_code == 410
    assert "const hasError = true" in client.get(f"/go/{token}").text


def test_witness_gets_scenario(client):
    token = _session(client, "obrzeza", radius=800).json()["token"]
    assert 'const scenario = "CPR_ONLY"' in client.get(f"/go/{token}").text


@pytest.mark.parametrize("radius", [150, 900])
def test_session_radius_bounds(client, radius):
    r = client.post("/api/v1/dispatcher/session", json={"lat": 53.12, "lon": 18.0, "radius_m": radius})
    assert r.status_code == 422


# ── Task 4: ekran świadka ──────────────────────────────────────────────
def test_witness_views_copy(client):
    token = _session(client, "centrum").json()["token"]
    html = client.get(f"/go/{token}").text
    for text in ("OTWÓRZ NAWIGACJĘ PIESZĄ (Google Maps)", "URZĄDZENIE ZAMKNIĘTE / BRAK AED NA MIEJSCU",
                 "KOD DO SZAFKI", "OTWARTE TERAZ",
                 "Nie opuszczaj poszkodowanego — w pobliżu brak dostępnego AED. Rozpocznij resuscytację (RKO) do przyjazdu karetki.",
                 "URUCHOM RYTM UCISKÓW (110/min)", "100–120 uciśnięć na minutę"):
        assert text in html, text
    assert '"hours_status": "open"' in html


# ── Poprawki po przeglądzie końcowym ──────────────────────────────────
def _two_aed_session(client, lat, lon, **extra):
    from app.database import get_db
    db = get_db()
    _add(db, f"r1-{lat}", lat + 0.0005, lon, opening_hours="24/7", **extra)
    _add(db, f"r2-{lat}", lat + 0.0015, lon, opening_hours="24/7")
    return client.post("/api/v1/dispatcher/session", json={"lat": lat, "lon": lon, "radius_m": 400}).json()


def test_witness_report_does_not_change_aed_status(client):
    """Krytyczne: zgłoszenie świadka nie może trwale wyłączyć prawdziwego AED."""
    from app.database import get_db
    lat, lon = 53.4000, 18.4000
    d = _two_aed_session(client, lat, lon)
    aed_id = d["aed"]["aed_id"]
    client.post(f"/go/{d['token']}/report-unavailable")
    db = get_db()
    assert db.execute("SELECT status FROM aed WHERE aed_id = ?", (aed_id,)).fetchone()[0] == "active"
    assert db.execute("SELECT COUNT(*) FROM aed_report WHERE aed_id = ?", (aed_id,)).fetchone()[0] == 1
    # skan nadal widzi AED, ale z flagą zgłoszenia i za niezgłoszonym otwartym
    scan = client.get("/api/v1/dispatcher/scan", params={"lat": lat, "lon": lon, "radius_m": 400}).json()
    reported = next(a for a in scan["in_radius"] if a["aed_id"] == aed_id)
    assert reported["reported_recently"] is True
    assert scan["candidates"][0]["aed_id"] != aed_id


def test_scan_does_not_expose_access_codes(client):
    p = _preset(client, "centrum")
    scan = _scan(client, p, 400).json()
    assert all(a["access_code"] is None for a in scan["in_radius"])
    assert scan["candidates"][0]["has_access_code"] is True
    d = _session(client, "centrum").json()
    assert d["aed"]["access_code"] == "1912"


def test_status_reports_scenario_after_fallback(client):
    d = _session(client, "centrum", radius=200).json()
    token = d["token"]
    for _ in range(3):
        client.post(f"/go/{token}/report-unavailable")
    st = client.get(f"/api/v1/rescue/{token}/status").json()
    assert st["scenario"] == "CPR_ONLY"


def test_witness_hours_use_simulated_time(client):
    """AED czynne Mo-Fr 08-18 wysłane na symulację w środę 10:00 jest „open”, niezależnie od realnego czasu."""
    from app.database import get_db
    lat, lon = 53.5000, 18.5000
    _add(get_db(), "office-sim", lat + 0.0005, lon, opening_hours="Mo-Fr 08:00-18:00")
    d = client.post("/api/v1/dispatcher/session",
                    json={"lat": lat, "lon": lon, "radius_m": 400, "timestamp": "2026-11-25T10:00:00"}).json()
    assert d["scenario"] == "AED_FOUND"
    import app.main as main
    real_now = main.now_pl
    main.now_pl = lambda: __import__("datetime").datetime(2026, 11, 22, 23, 0)  # niedziela w nocy
    try:
        html = client.get(f"/go/{d['token']}").text
    finally:
        main.now_pl = real_now
    assert '"hours_status": "open"' in html


def test_session_rate_limit(client, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "SESSION_RATE_LIMIT", 3)
    main._session_hits.clear()
    codes = [client.post("/api/v1/dispatcher/session", json={"lat": 53.12, "lon": 18.0}).status_code for _ in range(4)]
    main._session_hits.clear()
    assert codes[:3] == [200, 200, 200] and codes[3] == 429


def test_cpr_copy_follows_erc(client):
    token = _session(client, "obrzeza", radius=800).json()["token"]
    html = client.get(f"/go/{token}").text
    assert "nie dłużej niż 10 s" in html
    assert "Jeśli nie oddycha prawidłowo" in html
    assert "pełni unieść" in html


# ── Odroczone drobne uwagi ─────────────────────────────────────────────
def test_status_keeps_report_after_en_route(client):
    """Po przełączeniu na rezerwowe świadek znów jest „w drodze”, ale konsola
    nadal ma wiedzieć, że zgłosił niedostępne AED."""
    d = _two_aed_session(client, 53.6000, 18.6000)
    token = d["token"]
    client.post(f"/go/{token}/report-unavailable")
    client.post(f"/api/v1/rescue/{token}/event", json={"event": "en_route"})
    st = client.get(f"/api/v1/rescue/{token}/status").json()
    assert st["status"] == "en_route"
    assert st["unavailable_reports"] == 1


def test_missing_aed_falls_back_to_cpr_view(client):
    from app.database import get_db
    d = _two_aed_session(client, 53.7000, 18.7000)
    db = get_db()
    db.execute("UPDATE rescue_session SET aed_id_1 = 'nie-ma-takiego' WHERE token = ?", (d["token"],))
    db.commit()
    html = client.get(f"/go/{d['token']}").text
    assert 'const scenario = "CPR_ONLY"' in html
    assert "const hasError = false" in html


def test_dispatch_module_imports_first():
    """Import app.dispatch jako pierwszego modułu nie może się wysypać (brak cyklu)."""
    import subprocess, sys
    r = subprocess.run([sys.executable, "-c", "import app.dispatch, app.models; print(app.models.SessionCreated.model_fields['aed'])"],
                       capture_output=True, text=True, cwd=str(__import__('pathlib').Path(__file__).resolve().parent.parent))
    assert r.returncode == 0, r.stderr
