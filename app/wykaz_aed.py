"""Wykaz defibrylatorów AED w formacie portalu dane.gov.pl.

Pulsmap działa jako narzędzie dysponenta danych: przygotowuje wykaz AED
w zakresie kolumn obowiązującym w portalu (zasób oznaczony jako „Wykaz
defibrylatorów AED”) oraz plik XML do automatycznego zasilania portalu
(import XML, schemat `xml_import_otwarte_dane_1_13.xsd` z elementem
`containsAedData`).

Kolumny muszą być identyczne z `AED_COLUMNS` w backendzie portalu
(`mcod/resources/aed_constants.py`) – portal odrzuca wykaz o innym układzie.
Kod do szafki AED nie trafia do wykazu – publikujemy tylko informację, czy
szafka jest zamykana na kod.
"""

from __future__ import annotations

import csv
import io
import re
from xml.sax.saxutils import escape

WYKAZ_COLUMNS: list[str] = [
    "Lp.",
    "Identyfikator AED",
    "Szerokość geograficzna",
    "Długość geograficzna",
    "Miejscowość",
    "Ulica i numer",
    "Kod pocztowy",
    "Województwo",
    "Opis lokalizacji",
    "Wewnątrz budynku",
    "Dostępność",
    "Szafka zamykana na kod",
    "Godziny dostępności",
    "Status",
    "Opiekun urządzenia",
    "Telefon opiekuna",
    "E-mail opiekuna",
    "Data aktualizacji danych",
]

ACCESS_PL = {
    "public": "publiczna",
    "customers": "dla klientów",
    "permissive": "za zgodą właściciela",
    "private": "ograniczona",
}
STATUS_PL = {
    "active": "aktywny",
    "temporarily_unavailable": "czasowo niedostępny",
    "damaged": "uszkodzony",
    "unverified": "niezweryfikowany",
}

XML_NS = "urn:otwarte-dane:harvester:1.13"
DATASET_EXT_IDENT = "pulsmap-otworz-aed-wykaz-aed-0000001"  # 36 znaków, stały
RESOURCE_EXT_IDENT = "pulsmap-otworz-aed-wykaz-aed-csv-001"


def _tak_nie(value) -> str:
    return "TAK" if value in (1, True, "1", "true", "True") else "NIE"


_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_PL_DATE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")


def _iso_date(value) -> str | None:
    """Pełna data w formacie RRRR-MM-DD albo None (daty niepełne, np. „2025-02”, odrzucamy)."""
    text = str(value or "").strip()
    if m := _ISO_DATE.match(text):
        return "-".join(m.groups())
    if m := _PL_DATE.match(text):
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def aed_to_wykaz_row(aed: dict, lp: int, voivodeship: str | None) -> dict:
    """Jeden AED z bazy Pulsmap → wiersz wykazu w zakresie kolumn portalu."""
    # Data weryfikacji, a gdy jej brak (lub jest niepełna) – data ostatniej aktualizacji rekordu
    updated = (
        _iso_date(aed.get("last_verified_at"))
        or _iso_date(aed.get("updated_at"))
        or _iso_date(aed.get("created_at"))
        or ""
    )
    return {
        "Lp.": lp,
        "Identyfikator AED": aed["aed_id"],
        "Szerokość geograficzna": round(float(aed["latitude"]), 6),
        "Długość geograficzna": round(float(aed["longitude"]), 6),
        "Miejscowość": aed.get("address_city") or "",
        "Ulica i numer": aed.get("address_street") or "",
        "Kod pocztowy": aed.get("address_postal_code") or "",
        "Województwo": voivodeship or "",
        "Opis lokalizacji": aed.get("location_description") or "",
        "Wewnątrz budynku": _tak_nie(aed.get("indoor")),
        "Dostępność": ACCESS_PL.get(aed.get("access_type") or "", aed.get("access_type") or ""),
        "Szafka zamykana na kod": _tak_nie(bool(aed.get("access_code"))),
        "Godziny dostępności": aed.get("opening_hours") or "24/7",
        "Status": STATUS_PL.get(aed.get("status") or "", aed.get("status") or ""),
        "Opiekun urządzenia": aed.get("operator_name") or "",
        "Telefon opiekuna": aed.get("operator_phone") or "",
        "E-mail opiekuna": aed.get("operator_email") or "",
        "Data aktualizacji danych": updated,
    }


def wykaz_csv(rows: list[dict]) -> str:
    """CSV UTF-8 z BOM (Excel), separator przecinek – jak wzorcowe pliki portalu."""
    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.DictWriter(buf, fieldnames=WYKAZ_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def dane_gov_pl_xml(base_url: str, today: str) -> str:
    """Plik XML do automatycznego zasilania portalu (źródło danych typu „import XML”)."""
    base = base_url.rstrip("/")
    csv_url = escape(f"{base}/api/v1/export/wykaz-aed.csv")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ns2:datasets xmlns:ns2="{XML_NS}">
    <dataset status="published">
        <extIdent>{DATASET_EXT_IDENT}</extIdent>
        <title>
            <polish>Wykaz defibrylatorów AED – Pulsmap (OpenStreetMap i dysponenci)</polish>
        </title>
        <description>
            <polish>Wykaz automatycznych defibrylatorów zewnętrznych (AED) przygotowany w ramach akcji „Otwórz AED”. Dane z OpenStreetMap i od dysponentów urządzeń, po walidacji i deduplikacji (do 30 m). Kod do szafki nie jest publikowany.</polish>
        </description>
        <updateFrequency>daily</updateFrequency>
        <categories>
            <category>HEAL</category>
        </categories>
        <resources>
            <resource>
                <extIdent>{RESOURCE_EXT_IDENT}</extIdent>
                <url>{csv_url}</url>
                <title>
                    <polish>Wykaz defibrylatorów AED</polish>
                </title>
                <description>
                    <polish>Wykaz AED w zakresie kolumn wykazu defibrylatorów AED portalu dane.gov.pl.</polish>
                </description>
                <availability>local</availability>
                <dataDate>{today}</dataDate>
                <containsAedData>true</containsAedData>
            </resource>
        </resources>
        <tags>
            <tag lang="pl">AED</tag>
            <tag lang="pl">defibrylatory</tag>
            <tag lang="pl">Otwórz AED</tag>
        </tags>
    </dataset>
</ns2:datasets>
"""
