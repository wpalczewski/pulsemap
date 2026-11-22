"""Pulsmap pobiera ogólnopolski wykaz zbiorczy AED z portalu dane.gov.pl."""

import httpx

from app.etl import ingest_records
from app.portal_sync import (
    PORTAL_DATASET_TITLE,
    find_wykaz_csv_url,
    parse_wykaz_csv,
    sync_from_portal,
    wykaz_row_to_record,
)

HEADER = (
    "Lp.,Nazwa dysponenta danych,Identyfikator AED,Szerokość geograficzna,Długość geograficzna,Miejscowość,"
    "Ulica i numer,Kod pocztowy,Województwo,Opis lokalizacji,Wewnątrz budynku,Dostępność,Szafka zamykana na kod,"
    "Godziny dostępności,Status,Opiekun urządzenia,Telefon opiekuna,E-mail opiekuna,Data aktualizacji danych"
)
CSV = HEADER + "\n" + "\n".join([
    "1,Urząd miasta,aed-portal-1,53.123950,18.000550,Bydgoszcz,Stary Rynek 1,85-105,kujawsko-pomorskie,"
    "Parter,TAK,publiczna,TAK,Mo-Fr 08:00-18:00,czasowo niedostępny,Urząd,+48 52 000 00 00,aed@example.pl,2026-11-20",
    "2,Szpital,aed-portal-2,52.229700,21.012200,,,,mazowieckie,,NIE,dla klientów,NIE,24/7,aktywny,,,,2026-11-21",
]) + "\n"


def test_row_maps_back_to_pulsmap_record():
    rec = wykaz_row_to_record(parse_wykaz_csv(CSV)[0])
    assert rec["source_name"] == "dane.gov.pl"
    assert rec["source_id"] == "aed-portal-1"
    assert rec["latitude"] == 53.12395 and rec["longitude"] == 18.00055
    assert rec["indoor"] is True
    assert rec["access_type"] == "public"
    assert rec["status"] == "temporarily_unavailable"
    assert rec["opening_hours"] == "Mo-Fr 08:00-18:00"
    assert rec["operator_name"] == "Urząd"
    # Kodu szafki nie ma w otwartym wykazie – nie nadpisujemy go pustą wartością
    assert "access_code" not in rec


def test_operator_falls_back_to_disponent():
    rec = wykaz_row_to_record(parse_wykaz_csv(CSV)[1])
    assert rec["operator_name"] == "Szpital"
    assert rec["access_type"] == "customers"
    assert rec["indoor"] is False


def _portal(handler_calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        handler_calls.append(str(request.url))
        if request.url.path == "/datasets":
            return httpx.Response(200, json={"data": [
                {"id": "4211", "attributes": {"title": "Wykaz defibrylatorów <mark>AED</mark> – Pulsmap"}},
                {"id": "4213", "attributes": {"title": "Wykaz defibrylatorów <mark>AED</mark> – raport zbiorczy"}},
            ]})
        if request.url.path == "/datasets/4213/resources":
            return httpx.Response(200, json={"data": [
                {"id": "40209", "attributes": {"title": "Wykaz defibrylatorów AED",
                                               "csv_file_url": "https://api.mcod.local/media/wykaz.csv"}},
            ]})
        if request.url.path == "/media/wykaz.csv":
            return httpx.Response(200, content=CSV.encode("utf-8"))
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.mcod.local")


def test_find_csv_url_picks_aggregated_dataset():
    calls = []
    with _portal(calls) as client:
        assert find_wykaz_csv_url(client) == "https://api.mcod.local/media/wykaz.csv"
    assert PORTAL_DATASET_TITLE == "Wykaz defibrylatorów AED – raport zbiorczy"


def test_sync_imports_and_merges_with_existing(db):
    # AED już znany z OSM w tym samym miejscu → scalenie, nie duplikat
    ingest_records(db, [{"source_name": "OSM", "source_id": "node/1", "latitude": 53.12395, "longitude": 18.00055,
                         "access_code": "1912"}])
    calls = []
    with _portal(calls) as client:
        report = sync_from_portal(db, client=client)
    assert report.valid == 2
    assert db.execute("SELECT count(*) FROM aed").fetchone()[0] == 2
    # kod szafki z wcześniejszego źródła zostaje
    assert db.execute("SELECT access_code FROM aed WHERE latitude = 53.12395").fetchone()[0] == "1912"
    sources = {r[0] for r in db.execute("SELECT source_name FROM aed_source")}
    assert {"OSM", "dane.gov.pl"} <= sources
