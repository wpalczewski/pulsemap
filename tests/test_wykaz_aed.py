"""Wykaz defibrylatorów AED w formacie portalu dane.gov.pl (zasilanie ręczne i automatyczne)."""

import csv
import hashlib
import io
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app.wykaz_aed import WYKAZ_COLUMNS, aed_to_wykaz_row, dane_gov_pl_xml


@pytest.fixture
def client():
    import app.main as main
    with TestClient(main.app) as c:
        yield c

# Te same kolumny co AED_COLUMNS w backendzie portalu (mcod/resources/aed_constants.py)
PORTAL_AED_COLUMNS = [
    "Lp.", "Identyfikator AED", "Szerokość geograficzna", "Długość geograficzna", "Miejscowość",
    "Ulica i numer", "Kod pocztowy", "Województwo", "Opis lokalizacji", "Wewnątrz budynku", "Dostępność",
    "Szafka zamykana na kod", "Godziny dostępności", "Status", "Opiekun urządzenia", "Telefon opiekuna",
    "E-mail opiekuna", "Data aktualizacji danych",
]

AED = {
    "aed_id": "aed-1", "latitude": 53.12395, "longitude": 18.00055, "address_city": "Bydgoszcz",
    "address_street": "Stary Rynek 1", "address_postal_code": "85-105", "location_description": "Parter",
    "indoor": 1, "access_type": "public", "access_code": "1912", "opening_hours": "Mo-Fr 08:00-18:00",
    "status": "temporarily_unavailable", "operator_name": "Urząd", "operator_phone": "+48 52 000 00 00",
    "operator_email": "aed@example.pl", "last_verified_at": "2026-11-20T10:00:00",
}


def test_columns_match_portal_wykaz():
    assert WYKAZ_COLUMNS == PORTAL_AED_COLUMNS


def test_row_mapping_is_polish_and_hides_access_code():
    row = aed_to_wykaz_row(AED, lp=7, voivodeship="kujawsko-pomorskie")
    assert list(row) == WYKAZ_COLUMNS
    assert row["Lp."] == 7
    assert row["Województwo"] == "kujawsko-pomorskie"
    assert row["Wewnątrz budynku"] == "TAK"
    assert row["Szafka zamykana na kod"] == "TAK"
    assert row["Dostępność"] == "publiczna"
    assert row["Status"] == "czasowo niedostępny"
    assert row["Godziny dostępności"] == "Mo-Fr 08:00-18:00"
    assert row["Data aktualizacji danych"] == "2026-11-20"
    no_verif = dict(AED, last_verified_at=None, updated_at="2026-10-01 12:00:00")
    assert aed_to_wykaz_row(no_verif, 1, None)["Data aktualizacji danych"] == "2026-10-01"
    pl = dict(AED, last_verified_at="03.04.2023")
    assert aed_to_wykaz_row(pl, 1, None)["Data aktualizacji danych"] == "2023-04-03"
    partial = dict(AED, last_verified_at="2025-02", updated_at="2026-10-01 12:00:00")
    assert aed_to_wykaz_row(partial, 1, None)["Data aktualizacji danych"] == "2026-10-01"
    assert "1912" not in [str(v) for v in row.values()]


def test_xml_has_aed_flag_and_points_to_csv():
    xml = dane_gov_pl_xml("https://mcod.local/pulsmap", today="2026-11-22")
    root = ET.fromstring(xml)
    assert root.tag == "{urn:otwarte-dane:harvester:1.13}datasets"
    res = root.find("dataset/resources/resource")
    assert res.findtext("url") == "https://mcod.local/pulsmap/api/v1/export/wykaz-aed.csv"
    assert res.findtext("containsAedData") == "true"
    assert root.findtext("dataset/categories/category") == "HEAL"


def test_export_endpoints(client: TestClient):
    r = client.get("/api/v1/export/wykaz-aed.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0] == WYKAZ_COLUMNS and len(rows) > 1

    x = client.get("/api/v1/export/dane-gov-pl.xml")
    assert x.status_code == 200 and b"containsAedData" in x.content
    md5 = client.get("/api/v1/export/dane-gov-pl.xml.md5")
    assert md5.text.strip() == hashlib.md5(x.content).hexdigest()
    # harvester portalu: HEAD na XML i plik MD5 o tej samej nazwie bazowej
    assert client.head("/api/v1/export/dane-gov-pl.xml").status_code == 200
    assert client.get("/api/v1/export/dane-gov-pl.md5").text.strip() == md5.text.strip()
