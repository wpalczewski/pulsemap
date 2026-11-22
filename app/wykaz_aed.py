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


# ── Wzorcowy zakres danych (XLSX) – ten sam zakres, który sprawdza portal ──
WYKAZ_SPEC: list[tuple[str, str, str, str, str, str]] = [
    # kolumna, typ, obowiązkowa, opis, przykład, dozwolone wartości / format
    ("Lp.", "liczba całkowita", "Tak", "Numer porządkowy wiersza", "1", "1, 2, 3…"),
    ("Identyfikator AED", "tekst", "Tak", "Stały, unikalny identyfikator urządzenia nadany przez dysponenta", "aed-byd-0001", "unikalny w wykazie; nie zmienia się przy aktualizacji"),
    ("Szerokość geograficzna", "liczba dziesiętna", "Tak", "Szerokość geograficzna lokalizacji AED (WGS84)", "53.123950", "49.0–54.9, kropka dziesiętna"),
    ("Długość geograficzna", "liczba dziesiętna", "Tak", "Długość geograficzna lokalizacji AED (WGS84)", "18.000550", "14.1–24.2, kropka dziesiętna"),
    ("Miejscowość", "tekst", "Nie", "Nazwa miejscowości", "Bydgoszcz", ""),
    ("Ulica i numer", "tekst", "Nie", "Ulica i numer budynku", "Stary Rynek 1", ""),
    ("Kod pocztowy", "tekst", "Nie", "Kod pocztowy", "85-105", "NN-NNN"),
    ("Województwo", "tekst", "Nie", "Województwo, w którym stoi AED", "kujawsko-pomorskie", "nazwa województwa małymi literami"),
    ("Opis lokalizacji", "tekst", "Nie (zalecane)", "Dokładne miejsce w budynku – kluczowe dla świadka", "Parter, przy głównej klatce schodowej obok windy", ""),
    ("Wewnątrz budynku", "tak/nie", "Tak", "Czy AED jest wewnątrz budynku", "TAK", "TAK, NIE"),
    ("Dostępność", "słownik", "Tak", "Kto ma dostęp do AED", "publiczna", "publiczna, dla klientów, za zgodą właściciela, ograniczona"),
    ("Szafka zamykana na kod", "tak/nie", "Tak", "Czy szafka jest zamykana na kod (sam kod NIE jest publikowany)", "NIE", "TAK, NIE"),
    ("Godziny dostępności", "tekst", "Tak", "Godziny dostępności w formacie OSM opening_hours", "Mo-Fr 08:00-18:00; Sa 09:00-14:00", "24/7 lub składnia opening_hours (Mo, Tu, We, Th, Fr, Sa, Su, PH)"),
    ("Status", "słownik", "Tak", "Stan urządzenia", "aktywny", "aktywny, czasowo niedostępny, uszkodzony, niezweryfikowany"),
    ("Opiekun urządzenia", "tekst", "Nie (zalecane)", "Instytucja lub osoba odpowiedzialna za AED", "Urząd Miasta Bydgoszczy", ""),
    ("Telefon opiekuna", "tekst", "Nie (zalecane)", "Telefon kontaktowy opiekuna", "+48 52 000 00 00", ""),
    ("E-mail opiekuna", "tekst", "Nie (zalecane)", "Adres e-mail opiekuna", "aed@example.pl", ""),
    ("Data aktualizacji danych", "data", "Tak", "Data ostatniej weryfikacji lub aktualizacji rekordu", "2026-11-20", "RRRR-MM-DD"),
]


def wzorcowy_zakres_xlsx(sample_rows: list[dict]) -> io.BytesIO:
    """Plik XLSX: opis zakresu danych, szablon wykazu z przykładami i zasady zasilania portalu."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="00875A")
    wb = Workbook()

    ws = wb.active
    ws.title = "Zakres_danych"
    ws.append(["Kolumna", "Typ", "Obowiązkowa", "Opis", "Przykład", "Dozwolone wartości / format"])
    for row in WYKAZ_SPEC:
        ws.append(list(row))
    for col, width in zip("ABCDEF", (28, 18, 16, 60, 36, 56)):
        ws.column_dimensions[col].width = width

    tpl = wb.create_sheet("Wykaz_AED")
    tpl.append(WYKAZ_COLUMNS)
    for r in sample_rows:
        tpl.append([r.get(c, "") for c in WYKAZ_COLUMNS])
    for i in range(len(WYKAZ_COLUMNS)):
        tpl.column_dimensions[chr(ord("A") + i)].width = 22

    info = wb.create_sheet("Zasady")
    for line in [
        "Wzorcowy zakres danych – Wykaz defibrylatorów AED (akcja „Otwórz AED”)",
        "",
        "1. Arkusz „Wykaz_AED” to szablon: nazwy i kolejność kolumn muszą pozostać bez zmian – portal dane.gov.pl odrzuca wykaz o innym układzie.",
        "2. Zasilanie ręczne: w panelu dane.gov.pl dodaj zasób (xlsx, xls lub csv) i zaznacz „Wykaz defibrylatorów AED: Tak”.",
        "3. Zasilanie automatyczne: źródło danych typu import XML (schemat 1.13), zasób z elementem <containsAedData>true</containsAedData>.",
        "4. Portal codziennie scala wykazy wszystkich dysponentów w zbiór „Wykaz defibrylatorów AED – raport zbiorczy”.",
        "5. Kod do szafki AED NIE jest publikowany – podaj tylko, czy szafka jest zamykana na kod.",
        "6. Format: UTF-8, współrzędne WGS84 z kropką dziesiętną, daty RRRR-MM-DD, jeden wiersz = jedno urządzenie.",
        "Licencja danych: CC0 1.0.",
    ]:
        info.append([line])
    info.column_dimensions["A"].width = 130

    for sheet in (ws, tpl):
        for cell in sheet[1]:
            cell.font, cell.fill = head_font, head_fill
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        sheet.freeze_panes = "A2"
    info["A1"].font = Font(bold=True, size=13)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
