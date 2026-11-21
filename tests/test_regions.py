from pathlib import Path

import pytest

from app.etl import ingest_records
from app.regions import assign_voivodeship, load_voivodeships, region_stats

GEOJSON = Path(__file__).resolve().parent.parent / "data" / "wojewodztwa.geojson"


@pytest.fixture(scope="module")
def regions():
    return load_voivodeships(GEOJSON)


def test_loads_all_16(regions):
    assert len(regions) == 16


@pytest.mark.parametrize("lat,lon,expected", [
    (52.2297, 21.0122, "mazowieckie"),
    (50.0614, 19.9366, "małopolskie"),
    (53.1235, 18.0085, "kujawsko-pomorskie"),
    (54.6, 18.8, None),  # Zatoka Gdańska
])
def test_assign(regions, lat, lon, expected):
    assert assign_voivodeship(lat, lon, regions) == expected


def test_region_stats(db, regions):
    ingest_records(db, [
        {"source_name": "T", "source_id": "1", "latitude": 52.2297, "longitude": 21.0122,
         "location_description": "Hol główny", "opening_hours": "24/7",
         "operator_phone": "+48 22 000 00 00"},
        {"source_name": "T", "source_id": "4", "latitude": 52.23, "longitude": 21.02,
         "location_description": "Bez kontaktu", "opening_hours": "24/7"},
        {"source_name": "T", "source_id": "2", "latitude": 50.0614, "longitude": 19.9366},
        {"source_name": "T", "source_id": "3", "latitude": 54.6, "longitude": 18.8},
    ])
    stats = region_stats(db, regions)
    by_name = {s.name: s for s in stats}
    assert by_name["mazowieckie"].pct_complete == 50.0  # drugi AED bez kontaktu
    assert by_name["małopolskie"].pct_complete == 0.0
    assert stats[-1].name == "nieprzypisane" and stats[-1].total == 1
    assert sum(s.total for s in stats) == 4
    # posortowane malejąco (bez wiersza nieprzypisanych)
    pcts = [s.pct_complete for s in stats[:-1]]
    assert pcts == sorted(pcts, reverse=True)


def test_endpoint_missing_file_returns_503(monkeypatch):
    import app.main as main
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "REGIONS_PATH", "data/nie_ma_takiego_pliku.geojson")
    monkeypatch.setattr(main, "_regions_cache", None)
    with TestClient(main.app) as c:
        r = c.get("/api/v1/stats/regions")
    assert r.status_code == 503


def test_endpoint_returns_ranking():
    import app.main as main
    from fastapi.testclient import TestClient
    main._regions_cache = None
    with TestClient(main.app) as c:
        r = c.get("/api/v1/stats/regions")
    assert r.status_code == 200
    data = r.json()
    assert data and {"name", "total", "complete", "pct_complete"} <= set(data[0])


def test_regions_handler_runs_in_threadpool():
    """Liczenie rankingu (~0,7 s) nie może blokować pętli zdarzeń (ścieżka 112)."""
    import inspect
    import app.main as main
    assert not inspect.iscoroutinefunction(main.api_stats_regions)


def test_ingest_invalidates_ranking_cache(monkeypatch):
    import app.main as main
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "API_KEY", "")
    main._regions_cache = None
    with TestClient(main.app) as c:
        before = sum(r["total"] for r in c.get("/api/v1/stats/regions").json())
        c.post("/api/v1/ingest/json", json={"source_name": "T_cache", "source_id": "x1",
                                            "latitude": 50.30, "longitude": 22.10})
        after = sum(r["total"] for r in c.get("/api/v1/stats/regions").json())
    main._regions_cache = None
    assert after == before + 1


def test_polygon_with_hole_and_multipolygon(tmp_path):
    import json
    square = lambda x0, y0, x1, y1: [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    geo = {"type": "FeatureCollection", "features": [
        # „pierścień”: kwadrat 0–10 z dziurą 4–6
        {"type": "Feature", "properties": {"nazwa": "z-dziura"},
         "geometry": {"type": "Polygon", "coordinates": [square(0, 0, 10, 10), square(4, 4, 6, 6)]}},
        # dwie rozłączne wyspy
        {"type": "Feature", "properties": {"nazwa": "wyspy"},
         "geometry": {"type": "MultiPolygon", "coordinates": [[square(20, 0, 22, 2)], [square(30, 0, 32, 2)]]}},
    ]}
    path = tmp_path / "test.geojson"
    path.write_text(json.dumps(geo))
    regions = load_voivodeships(path)
    # (lat, lon) – lon to x
    assert assign_voivodeship(2, 2, regions) == "z-dziura"
    assert assign_voivodeship(5, 5, regions) is None          # w dziurze
    assert assign_voivodeship(1, 21, regions) == "wyspy"
    assert assign_voivodeship(1, 31, regions) == "wyspy"
    assert assign_voivodeship(1, 25, regions) is None         # między wyspami
