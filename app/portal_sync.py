"""Pobieranie ogólnopolskiego wykazu AED z portalu dane.gov.pl do bazy dyspozytora.

Obieg danych: dysponenci zasilają wykaz AED w portalu (ręcznie lub importem
XML) → portal codziennie tworzy „Wykaz defibrylatorów AED – raport zbiorczy”
→ Pulsmap pobiera ten wykaz przez API portalu i importuje go do bazy, z której
korzysta dyspozytor 112 i ekran świadka.

Wykaz nie zawiera kodu do szafki (dane niepubliczne), więc import go nie
nadpisuje – kod pozostaje z wcześniejszych źródeł (np. zgłoszenia dysponenta).

Użycie:  python -m app.portal_sync
Zmienne: PULSEMAP_PORTAL_API_URL (domyślnie https://api.mcod.local),
         PULSEMAP_PORTAL_CA – plik certyfikatu CA portalu (instancja lokalna).
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import sqlite3
from typing import Optional

import httpx

from app.etl import ingest_records
from app.models import IngestReport
from app.wykaz_aed import ACCESS_PL, STATUS_PL

logger = logging.getLogger("pulsmap.portal_sync")

PORTAL_DATASET_TITLE = "Wykaz defibrylatorów AED – raport zbiorczy"
SOURCE_NAME = "dane.gov.pl"

_ACCESS_FROM_PL = {v: k for k, v in ACCESS_PL.items()}
_STATUS_FROM_PL = {v: k for k, v in STATUS_PL.items()}
_TAGS = re.compile(r"<[^>]+>")


def parse_wykaz_csv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


def wykaz_row_to_record(row: dict) -> dict:
    """Wiersz wykazu zbiorczego z portalu → rekord do importu Pulsmap."""
    def get(col: str) -> str:
        return (row.get(col) or "").strip()

    return {
        "source_name": SOURCE_NAME,
        "source_id": get("Identyfikator AED"),
        "latitude": float(get("Szerokość geograficzna")),
        "longitude": float(get("Długość geograficzna")),
        "address_city": get("Miejscowość"),
        "address_street": get("Ulica i numer"),
        "address_postal_code": get("Kod pocztowy"),
        "location_description": get("Opis lokalizacji"),
        "indoor": get("Wewnątrz budynku").upper() == "TAK",
        "access_type": _ACCESS_FROM_PL.get(get("Dostępność"), "public"),
        "opening_hours": get("Godziny dostępności") or "24/7",
        "status": _STATUS_FROM_PL.get(get("Status"), "active"),
        "operator_name": get("Opiekun urządzenia") or get("Nazwa dysponenta danych"),
        "operator_phone": get("Telefon opiekuna"),
        "operator_email": get("E-mail opiekuna"),
    }


def find_wykaz_csv_url(client: httpx.Client) -> str:
    """Adres pliku CSV wygenerowanego przez portal dla wykazu zbiorczego AED."""
    found = client.get("/datasets", params={"q": PORTAL_DATASET_TITLE, "per_page": 20}).raise_for_status().json()
    dataset_id: Optional[str] = next(
        (d["id"] for d in found.get("data", []) if _TAGS.sub("", d["attributes"].get("title", "")).strip() == PORTAL_DATASET_TITLE),
        None,
    )
    if dataset_id is None:
        raise LookupError(f"Nie znaleziono zbioru „{PORTAL_DATASET_TITLE}” w portalu")
    resources = client.get(f"/datasets/{dataset_id}/resources").raise_for_status().json()
    for res in resources.get("data", []):
        attrs = res["attributes"]
        url = attrs.get("csv_file_url") or attrs.get("csv_download_url")
        if url:
            return url
    raise LookupError(f"Zbiór {dataset_id} nie ma zasobu z plikiem CSV")


def _default_client() -> httpx.Client:
    api = os.environ.get("PULSEMAP_PORTAL_API_URL", "https://api.mcod.local")
    verify: str | bool = os.environ.get("PULSEMAP_PORTAL_CA") or True
    return httpx.Client(base_url=api, verify=verify, timeout=60.0, follow_redirects=True)


def sync_from_portal(db: sqlite3.Connection, client: Optional[httpx.Client] = None) -> IngestReport:
    """Pobiera wykaz zbiorczy AED z dane.gov.pl i importuje go do bazy Pulsmap."""
    own = client is None
    client = client or _default_client()
    try:
        url = find_wykaz_csv_url(client)
        text = client.get(url).raise_for_status().content.decode("utf-8-sig")
    finally:
        if own:
            client.close()
    records, errors = [], []
    for i, row in enumerate(parse_wykaz_csv(text), start=2):
        try:
            records.append(wykaz_row_to_record(row))
        except (TypeError, ValueError) as exc:
            errors.append(f"Wiersz {i}: {exc}")
    report = ingest_records(db, records, sync_source=SOURCE_NAME)
    report.errors = errors + report.errors
    logger.info("Synchronizacja z dane.gov.pl: %s", report.model_dump())
    return report


if __name__ == "__main__":
    from app.database import get_db

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    r = sync_from_portal(get_db())
    print(f"dane.gov.pl → Pulsmap: poprawne {r.valid}, nowe {r.inserted}, zaktualizowane {r.updated}, "
          f"scalone {r.duplicates_merged}, błędy {len(r.errors)}")
