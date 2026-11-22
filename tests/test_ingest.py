from app.etl import ingest_records

BASE = {"latitude": 53.1325, "longitude": 18.0010, "address_city": "Bydgoszcz"}


def rec(**kw):
    return {**BASE, **kw}


def aeds(db):
    return [dict(r) for r in db.execute("SELECT * FROM aed ORDER BY created_at, aed_id")]


def test_two_devices_from_same_source_are_not_merged(db):
    # dwa różne AED z OSM 10 m od siebie (np. w jednym budynku)
    ingest_records(db, [
        rec(source_name="OSM", source_id="node/1"),
        rec(source_name="OSM", source_id="node/2", latitude=53.13259),
    ])
    assert len(aeds(db)) == 2


def test_other_source_nearby_is_merged(db):
    ingest_records(db, [rec(source_name="OSM", source_id="node/1")])
    report = ingest_records(db, [rec(source_name="UM_Bydgoszcz", source_id="UM-1",
                                      latitude=53.13255, operator_phone="+48 52 000 00 00")])
    rows = aeds(db)
    assert report.duplicates_merged == 1 and len(rows) == 1
    assert rows[0]["source_name"] == "OSM+UM_Bydgoszcz"
    assert rows[0]["operator_phone"] == "+48 52 000 00 00"
    # oba źródła powiązane z tym samym AED
    links = db.execute("SELECT source_name FROM aed_source WHERE aed_id = ?", (rows[0]["aed_id"],)).fetchall()
    assert {l[0] for l in links} == {"OSM", "UM_Bydgoszcz"}


def test_reimport_updates_values_from_same_source(db):
    ingest_records(db, [rec(source_name="OSM", source_id="node/1", opening_hours="Mo-Fr 08:00-16:00")])
    report = ingest_records(db, [rec(source_name="OSM", source_id="node/1", opening_hours="24/7",
                                     latitude=53.1400)])  # przeniesiony o ~800 m
    rows = aeds(db)
    assert report.updated == 1 and report.inserted == 0
    assert len(rows) == 1
    assert rows[0]["opening_hours"] == "24/7"
    assert rows[0]["latitude"] == 53.14


def test_reimport_keeps_field_reported_unavailability(db):
    ingest_records(db, [rec(source_name="OSM", source_id="node/1")])
    db.execute("UPDATE aed SET status = 'temporarily_unavailable', status_updated_at = '2026-11-20T10:00:00'")
    ingest_records(db, [rec(source_name="OSM", source_id="node/1", status="active")])
    assert aeds(db)[0]["status"] == "temporarily_unavailable"
    # świeższa weryfikacja w źródle przywraca status
    ingest_records(db, [rec(source_name="OSM", source_id="node/1", status="active",
                            last_verified_at="2026-11-21T09:00:00")])
    assert aeds(db)[0]["status"] == "active"


def test_fresher_cross_source_verification_wins(db):
    ingest_records(db, [rec(source_name="OSM", source_id="node/1", opening_hours="24/7",
                            last_verified_at="2024-01-01T00:00:00")])
    ingest_records(db, [rec(source_name="UM_Bydgoszcz", source_id="UM-1",
                            opening_hours="Mo-Fr 07:30-15:30", last_verified_at="2026-10-01T00:00:00")])
    assert aeds(db)[0]["opening_hours"] == "Mo-Fr 07:30-15:30"


def test_full_snapshot_marks_missing_devices(db):
    ingest_records(db, [rec(source_name="OSM", source_id="node/1"),
                        rec(source_name="OSM", source_id="node/2", latitude=53.2)])
    report = ingest_records(db, [rec(source_name="OSM", source_id="node/1")], sync_source="OSM")
    status = {r["source_id"]: r["status"] for r in aeds(db)}
    assert report.marked_missing == 1
    assert status == {"node/1": "active", "node/2": "unverified"}


def test_quality_score_is_always_computed(db):
    ingest_records(db, [rec(source_name="X", source_id="1", quality_score=100)])
    assert aeds(db)[0]["quality_score"] < 100


def test_invalid_record_reported(db):
    report = ingest_records(db, [rec(source_name="X", latitude=10.0)])
    assert report.valid == 0 and len(report.errors) == 1


def test_polish_hours_are_stored_in_osm_format(db):
    ingest_records(db, [rec(source_name="Formularz", source_id="f/1", opening_hours="Pn-Pt 08:00-16:00")])
    assert aeds(db)[0]["opening_hours"] == "Mo-Fr 08:00-16:00"
