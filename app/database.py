"""Pulsmap – SQLite database layer & realistic Bydgoszcz seed data."""

from __future__ import annotations

import sqlite3
import os
from pathlib import Path

from app.models import CREATE_TABLE_SQL

DB_PATH = os.environ.get("PULSEMAP_DB", "data/pulsemap.db")

_connection: sqlite3.Connection | None = None


def _run_migrations(con: sqlite3.Connection) -> None:
    """Ensure optional columns in rescue_session exist."""
    cur = con.cursor()
    cur.execute("PRAGMA table_info(rescue_session)")
    cols = {row[1] for row in cur.fetchall()}
    needed = {
        "caller_phone": "TEXT DEFAULT ''",
        "dispatch_channel": "TEXT DEFAULT 'mobywatel'",
        "status": "TEXT DEFAULT 'pending'",
        "updated_at": "TEXT DEFAULT ''",
        "call_ref": "TEXT DEFAULT ''",
        "scenario": "TEXT DEFAULT 'AED_FOUND'",
        "radius_m": "INTEGER DEFAULT 400",
        "sim_ts": "TEXT",
    }
    for col_name, col_def in needed.items():
        if col_name not in cols:
            con.execute(f"ALTER TABLE rescue_session ADD COLUMN {col_name} {col_def}")
    aed_cols = {row[1] for row in con.execute("PRAGMA table_info(aed)")}
    if "status_updated_at" not in aed_cols:
        con.execute("ALTER TABLE aed ADD COLUMN status_updated_at TEXT")
    # Seed z Bydgoszczy ma fikcyjne ID węzłów OSM – nie podpisujemy ich jako OSM,
    # bo synchronizacja z prawdziwym OSM oznaczyłaby je jako zniknięte.
    con.execute(
        "UPDATE aed SET source_name = replace(source_name, 'OSM', 'Demo_OSM') "
        "WHERE aed_id GLOB 'aed-byd-*' AND source_id GLOB 'node/98012345*' "
        "AND source_name NOT LIKE '%Demo_OSM%'"
    )
    con.execute(
        "UPDATE aed_source SET source_name = 'Demo_OSM' "
        "WHERE source_name = 'OSM' AND aed_id GLOB 'aed-byd-*' AND source_id GLOB 'node/98012345*'"
    )
    backfill_source_links(con)
    con.commit()


def backfill_source_links(con: sqlite3.Connection) -> None:
    """Uzupełnia tabelę aed_source dla rekordów sprzed jej wprowadzenia.

    Kolumna aed.source_id przechowuje ID ze źródła, które pierwsze dodało rekord.
    Dla scalonych nazw ("OSM+X") rozpoznajemy źródło po formacie ID.
    """
    con.execute(
        """
        INSERT OR IGNORE INTO aed_source (source_name, source_id, aed_id)
        SELECT src, source_id, aed_id FROM (
            SELECT aed_id, source_id,
                   CASE
                     WHEN instr(source_name, 'Demo_OSM') > 0 AND source_id GLOB 'node/98012345*'
                          THEN 'Demo_OSM'
                     WHEN source_id GLOB 'node/*' OR source_id GLOB 'way/*'
                          OR source_id GLOB 'relation/*' THEN 'OSM'
                     WHEN instr(source_name, '+') = 0 THEN source_name
                     WHEN source_id GLOB 'ZD-*' THEN 'Zgloszenie_Dysponenta'
                     WHEN source_id GLOB 'UM-*' THEN 'UM_Bydgoszcz'
                   END AS src
            FROM aed
            WHERE source_id != ''
              AND aed_id NOT IN (SELECT aed_id FROM aed_source)
        ) WHERE src IS NOT NULL
        """
    )


def get_db() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _connection = sqlite3.connect(DB_PATH, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA journal_mode=WAL")
        _connection.execute("PRAGMA foreign_keys=ON")
        _connection.executescript(CREATE_TABLE_SQL)
        _run_migrations(_connection)
        _connection.commit()
    return _connection


def reset_db() -> sqlite3.Connection:
    global _connection
    if _connection:
        _connection.close()
        _connection = None
    p = Path(DB_PATH)
    if p.exists():
        p.unlink()
    return get_db()


# ── Realistic Bydgoszcz seed (25-30 AEDs) ────────────────────────────
# Contains intentional duplicates (entries 26-28 within 30m of earlier ones)
# and some devices with limited hours or non-active status.

SEED_DATA: list[dict] = [
    # 1 — Dworzec Główny PKP
    {
        "aed_id": "aed-byd-001",
        "source_name": "Demo_OSM",
        "source_id": "node/9801234567",
        "latitude": 53.1325,
        "longitude": 18.0010,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Zygmunta Augusta 7",
        "address_postal_code": "85-082",
        "location_description": "Hala główna dworca, filar przy wejściu od ul. Zygmunta Augusta, obok kiosku Relay",
        "indoor": True,
        "access_type": "public",
        "opening_hours": "24/7",
        "status": "active",
        "operator_name": "PKP SA",
        "operator_phone": "+48 52 345 67 89",
        "operator_email": "aed@pkp.pl",
        "last_verified_at": "2026-09-15T10:00:00",
        "quality_score": 95,
    },
    # 2 — Galeria Focus Mall
    {
        "aed_id": "aed-byd-002",
        "source_name": "Demo_OSM",
        "source_id": "node/9801234568",
        "latitude": 53.1218,
        "longitude": 17.9942,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Jagiellońska 39-47",
        "address_postal_code": "85-097",
        "location_description": "Parter galerii, przy punkcie informacyjnym obok wejścia głównego",
        "indoor": True,
        "access_type": "customers",
        "opening_hours": "Mo-Sa 09:00-21:00; Su 10:00-20:00",
        "status": "active",
        "operator_name": "Focus Mall Bydgoszcz",
        "operator_phone": "+48 52 567 89 01",
        "operator_email": "info@focusmall.pl",
        "last_verified_at": "2026-10-01T14:30:00",
        "quality_score": 90,
    },
    # 3 — Urząd Miasta Bydgoszczy
    {
        "aed_id": "aed-byd-003",
        "source_name": "UM_Bydgoszcz",
        "source_id": "UM-AED-003",
        "latitude": 53.1235,
        "longitude": 18.0085,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Jezuicka 1",
        "address_postal_code": "85-102",
        "location_description": "Parter budynku głównego, korytarz przy portierni, wejście A od ul. Jezuickiej",
        "indoor": True,
        "access_type": "public",
        "opening_hours": "Mo-Fr 07:30-15:30",
        "status": "active",
        "operator_name": "Urząd Miasta Bydgoszczy",
        "operator_phone": "+48 52 585 86 86",
        "operator_email": "aed@um.bydgoszcz.pl",
        "last_verified_at": "2026-11-01T08:00:00",
        "quality_score": 92,
    },
    # 4 — Stary Rynek / Ratusz
    {
        "aed_id": "aed-byd-004",
        "source_name": "Demo_OSM",
        "source_id": "node/9801234570",
        "latitude": 53.1240,
        "longitude": 18.0045,
        "address_city": "Bydgoszcz",
        "address_street": "Stary Rynek 1",
        "address_postal_code": "85-104",
        "location_description": "Zewnętrzna szafka AED na ścianie Ratusza od strony fontanny",
        "indoor": False,
        "access_type": "public",
        "access_code": "1234",
        "opening_hours": "24/7",
        "status": "active",
        "operator_name": "Miasto Bydgoszcz",
        "operator_phone": "+48 52 585 86 00",
        "last_verified_at": "2026-10-20T12:00:00",
        "quality_score": 88,
    },
    # 5 — Szpital Uniwersytecki nr 1 (SOR)
    {
        "aed_id": "aed-byd-005",
        "source_name": "UM_Bydgoszcz",
        "source_id": "UM-AED-005",
        "latitude": 53.1180,
        "longitude": 18.0160,
        "address_city": "Bydgoszcz",
        "address_street": "ul. M. Skłodowskiej-Curie 9",
        "address_postal_code": "85-094",
        "location_description": "Hol główny SOR, przy drzwiach automatycznych",
        "indoor": True,
        "access_type": "public",
        "opening_hours": "24/7",
        "status": "active",
        "operator_name": "Szpital Uniwersytecki nr 1",
        "operator_phone": "+48 52 585 40 00",
        "operator_email": "szpital@jurasza.pl",
        "last_verified_at": "2026-11-10T09:00:00",
        "quality_score": 98,
    },
    # 6 — Centrum Handlowe Zielone Arkady
    {
        "aed_id": "aed-byd-006",
        "source_name": "Demo_OSM",
        "source_id": "node/9801234572",
        "latitude": 53.1290,
        "longitude": 18.0005,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Wojska Polskiego 1",
        "address_postal_code": "85-171",
        "location_description": "Poziom 0, obok punktu obsługi klienta przy fontannie",
        "indoor": True,
        "access_type": "customers",
        "opening_hours": "Mo-Sa 10:00-21:00; Su 10:00-20:00",
        "status": "active",
        "operator_name": "Zielone Arkady",
        "operator_phone": "+48 52 320 50 00",
        "operator_email": "biuro@zielonearkady.pl",
        "last_verified_at": "2026-08-15T11:00:00",
        "quality_score": 85,
    },
    # 7 — Stadion Zawiszy
    {
        "aed_id": "aed-byd-007",
        "source_name": "Demo_OSM",
        "source_id": "node/9801234573",
        "latitude": 53.1340,
        "longitude": 18.0290,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Gdańska 163",
        "address_postal_code": "85-915",
        "location_description": "Budynek klubowy, wejście główne, hol przy portierni",
        "indoor": True,
        "access_type": "permissive",
        "opening_hours": "Mo-Fr 08:00-20:00; Sa 09:00-18:00",
        "status": "active",
        "operator_name": "Zawisza Bydgoszcz",
        "operator_phone": "+48 52 345 11 22",
        "last_verified_at": "2026-07-01T16:00:00",
        "quality_score": 70,
    },
    # 8 — Wyższa Szkoła Gospodarki
    {
        "aed_id": "aed-byd-008",
        "source_name": "Zgloszenie_Dysponenta",
        "source_id": "ZD-2026-008",
        "latitude": 53.1200,
        "longitude": 18.0100,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Garbary 2",
        "address_postal_code": "85-229",
        "location_description": "Parter budynku A, korytarz główny, obok recepcji studenckiej",
        "indoor": True,
        "access_type": "permissive",
        "opening_hours": "Mo-Fr 07:00-21:00; Sa 08:00-16:00",
        "status": "active",
        "operator_name": "WSG Bydgoszcz",
        "operator_phone": "+48 52 567 00 00",
        "operator_email": "aed@wsg.bydgoszcz.pl",
        "last_verified_at": "2026-09-20T10:00:00",
        "quality_score": 82,
    },
    # 9 — Basen Astoria
    {
        "aed_id": "aed-byd-009",
        "source_name": "Demo_OSM",
        "source_id": "node/9801234575",
        "latitude": 53.1310,
        "longitude": 17.9880,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Szubińska 4",
        "address_postal_code": "85-312",
        "location_description": "Hol wejściowy basenu, ściana obok szatni, obudowa metalowa",
        "indoor": True,
        "access_type": "customers",
        "opening_hours": "Mo-Fr 06:00-22:00; Sa-Su 08:00-20:00",
        "status": "active",
        "operator_name": "MOSiR Bydgoszcz",
        "operator_phone": "+48 52 341 22 33",
        "last_verified_at": "2026-10-10T07:30:00",
        "quality_score": 78,
    },
    # 10 — Galeria Pomorska
    {
        "aed_id": "aed-byd-010",
        "source_name": "Demo_OSM",
        "source_id": "node/9801234576",
        "latitude": 53.1370,
        "longitude": 17.9700,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Fordońska 141",
        "address_postal_code": "85-739",
        "location_description": "Parter, przy eskalatorach, obok bankomatu",
        "indoor": True,
        "access_type": "customers",
        "opening_hours": "Mo-Sa 10:00-21:00; Su 10:00-20:00",
        "status": "active",
        "operator_name": "Galeria Pomorska",
        "operator_phone": "+48 52 361 00 00",
        "last_verified_at": "2026-06-30T14:00:00",
        "quality_score": 75,
    },
    # 11 — Uniwersytet Kazimierza Wielkiego (UKW)
    {
        "aed_id": "aed-byd-011",
        "source_name": "UM_Bydgoszcz",
        "source_id": "UM-AED-011",
        "latitude": 53.1226,
        "longitude": 18.0040,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Chodkiewicza 30",
        "address_postal_code": "85-064",
        "location_description": "Budynek rektoratu, parter, hol przy wejściu głównym",
        "indoor": True,
        "access_type": "permissive",
        "opening_hours": "Mo-Fr 07:00-20:00",
        "status": "active",
        "operator_name": "Uniwersytet Kazimierza Wielkiego",
        "operator_phone": "+48 52 341 91 00",
        "operator_email": "aed@ukw.edu.pl",
        "last_verified_at": "2026-10-15T09:00:00",
        "quality_score": 87,
    },
    # 12 — Biblioteka Miejska
    {
        "aed_id": "aed-byd-012",
        "source_name": "UM_Bydgoszcz",
        "source_id": "UM-AED-012",
        "latitude": 53.1250,
        "longitude": 18.0070,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Długa 39",
        "address_postal_code": "85-034",
        "location_description": "Parter biblioteki, przy wejściu głównym, obok szafek czytelników",
        "indoor": True,
        "access_type": "public",
        "opening_hours": "Mo-Fr 09:00-19:00; Sa 09:00-15:00",
        "status": "active",
        "operator_name": "Wojewódzka i Miejska Biblioteka Publiczna",
        "operator_phone": "+48 52 340 50 00",
        "last_verified_at": "2026-09-05T11:00:00",
        "quality_score": 80,
    },
    # 13 — Wyspa Młyńska (zewnętrzny)
    {
        "aed_id": "aed-byd-013",
        "source_name": "Demo_OSM",
        "source_id": "node/9801234579",
        "latitude": 53.1230,
        "longitude": 18.0060,
        "address_city": "Bydgoszcz",
        "address_street": "Wyspa Młyńska",
        "address_postal_code": "85-032",
        "location_description": "Totem AED przy moście prowadzącym na wyspę, strona zachodnia",
        "indoor": False,
        "access_type": "public",
        "access_code": "2580",
        "opening_hours": "24/7",
        "status": "active",
        "operator_name": "Miasto Bydgoszcz",
        "operator_phone": "+48 52 585 86 00",
        "last_verified_at": "2026-11-05T08:00:00",
        "quality_score": 93,
    },
    # 14 — Hala Łuczniczka
    {
        "aed_id": "aed-byd-014",
        "source_name": "Demo_OSM",
        "source_id": "node/9801234580",
        "latitude": 53.1270,
        "longitude": 18.0210,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Toruńska 59",
        "address_postal_code": "85-023",
        "location_description": "Hol główny hali, filar przy kasach, szafka metalowa",
        "indoor": True,
        "access_type": "public",
        "opening_hours": "Mo-Fr 08:00-22:00; Sa-Su 09:00-20:00",
        "status": "active",
        "operator_name": "Hala Sportowa Łuczniczka",
        "operator_phone": "+48 52 341 60 00",
        "last_verified_at": "2026-08-20T13:00:00",
        "quality_score": 83,
    },
    # 15 — Leroy Merlin
    {
        "aed_id": "aed-byd-015",
        "source_name": "Zgloszenie_Dysponenta",
        "source_id": "ZD-2026-015",
        "latitude": 53.1480,
        "longitude": 17.9640,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Fordońska 246",
        "address_postal_code": "85-766",
        "location_description": "Wejście główne, ściana po prawej stronie, szafka na ścianie",
        "indoor": True,
        "access_type": "customers",
        "opening_hours": "Mo-Sa 07:00-21:00; Su 09:00-18:00",
        "status": "active",
        "operator_name": "Leroy Merlin Bydgoszcz",
        "operator_phone": "+48 52 377 50 00",
        "last_verified_at": "2026-07-10T15:00:00",
        "quality_score": 72,
    },
    # 16 — Park Kazimierza Wielkiego (zewnętrzny totem)
    {
        "aed_id": "aed-byd-016",
        "source_name": "UM_Bydgoszcz",
        "source_id": "UM-AED-016",
        "latitude": 53.1215,
        "longitude": 18.0030,
        "address_city": "Bydgoszcz",
        "address_street": "Park Kazimierza Wielkiego",
        "address_postal_code": "85-074",
        "location_description": "Totem AED przy wejściu do parku od ul. Libelta, obok ławek",
        "indoor": False,
        "access_type": "public",
        "opening_hours": "24/7",
        "status": "active",
        "operator_name": "Miasto Bydgoszcz",
        "operator_phone": "+48 52 585 86 00",
        "last_verified_at": "2026-11-01T10:00:00",
        "quality_score": 91,
    },
    # 17 — Centrum Kongresowe Opera Nova
    {
        "aed_id": "aed-byd-017",
        "source_name": "Demo_OSM",
        "source_id": "node/9801234583",
        "latitude": 53.1245,
        "longitude": 18.0100,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Marszałka Focha 5",
        "address_postal_code": "85-070",
        "location_description": "Foyer główne, lewa strona od wejścia, obok szatni",
        "indoor": True,
        "access_type": "customers",
        "opening_hours": "Mo-Fr 10:00-20:00; Sa-Su 12:00-20:00",
        "status": "active",
        "operator_name": "Opera Nova",
        "operator_phone": "+48 52 325 05 00",
        "operator_email": "aed@operanova.bydgoszcz.pl",
        "last_verified_at": "2026-09-28T09:00:00",
        "quality_score": 86,
    },
    # 18 — Pływalnia Wodny Park
    {
        "aed_id": "aed-byd-018",
        "source_name": "Demo_OSM",
        "source_id": "node/9801234584",
        "latitude": 53.1150,
        "longitude": 17.9950,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Słoneczna 1-3",
        "address_postal_code": "85-348",
        "location_description": "Recepcja główna, szafka AED na filarze, strona lewa",
        "indoor": True,
        "access_type": "customers",
        "opening_hours": "Mo-Fr 06:30-21:30; Sa-Su 08:00-21:00",
        "status": "active",
        "operator_name": "Wodny Park Bydgoszcz",
        "operator_phone": "+48 52 360 60 00",
        "last_verified_at": "2026-10-05T08:00:00",
        "quality_score": 79,
    },
    # 19 — Dworzec Autobusowy
    {
        "aed_id": "aed-byd-019",
        "source_name": "Demo_OSM",
        "source_id": "node/9801234585",
        "latitude": 53.1322,
        "longitude": 17.9995,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Jagiellońska 58",
        "address_postal_code": "85-097",
        "location_description": "Hala dworca autobusowego, ściana przy kasach, obok wyjścia na perony",
        "indoor": True,
        "access_type": "public",
        "opening_hours": "Mo-Su 05:00-23:00",
        "status": "active",
        "operator_name": "PKS Bydgoszcz",
        "operator_phone": "+48 52 322 42 40",
        "last_verified_at": "2026-08-01T07:00:00",
        "quality_score": 76,
    },
    # 20 — Komisariat Policji Śródmieście
    {
        "aed_id": "aed-byd-020",
        "source_name": "UM_Bydgoszcz",
        "source_id": "UM-AED-020",
        "latitude": 53.1260,
        "longitude": 18.0020,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Poniatowskiego 2",
        "address_postal_code": "85-671",
        "location_description": "Hol wejściowy komisariatu, dyżurka, AED w szafce po prawej od drzwi",
        "indoor": True,
        "access_type": "public",
        "opening_hours": "24/7",
        "status": "active",
        "operator_name": "KMP Bydgoszcz",
        "operator_phone": "+48 52 588 12 22",
        "last_verified_at": "2026-11-15T14:00:00",
        "quality_score": 94,
    },
    # 21 — Apteka Centrum (nocna)
    {
        "aed_id": "aed-byd-021",
        "source_name": "Zgloszenie_Dysponenta",
        "source_id": "ZD-2026-021",
        "latitude": 53.1238,
        "longitude": 18.0050,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Gdańska 25",
        "address_postal_code": "85-005",
        "location_description": "Witryna apteki, szafka AED po prawej stronie od wejścia",
        "indoor": False,
        "access_type": "public",
        "opening_hours": "24/7",
        "status": "active",
        "operator_name": "Apteka Centrum",
        "operator_phone": "+48 52 322 44 55",
        "last_verified_at": "2026-10-28T16:00:00",
        "quality_score": 89,
    },
    # 22 — Centrum sportowe Łuczniczka (II punkt)
    {
        "aed_id": "aed-byd-022",
        "source_name": "UM_Bydgoszcz",
        "source_id": "UM-AED-022",
        "latitude": 53.1266,
        "longitude": 18.0225,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Toruńska 59",
        "address_postal_code": "85-023",
        "location_description": "Szatnie sportowe, korytarz B, obok wejścia na halę treningową",
        "indoor": True,
        "access_type": "permissive",
        "opening_hours": "Mo-Fr 07:00-22:00; Sa-Su 08:00-20:00",
        "status": "active",
        "operator_name": "MOSiR Bydgoszcz",
        "operator_phone": "+48 52 341 60 00",
        "last_verified_at": "2026-08-20T13:30:00",
        "quality_score": 81,
    },
    # 23 — Bydgoszcz Główna - peron (USZKODZONY)
    {
        "aed_id": "aed-byd-023",
        "source_name": "Demo_OSM",
        "source_id": "node/9801234590",
        "latitude": 53.1330,
        "longitude": 18.0020,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Zygmunta Augusta 7",
        "address_postal_code": "85-082",
        "location_description": "Peron 2, wiata, szafka AED na filarze - UWAGA: USZKODZONY",
        "indoor": False,
        "access_type": "public",
        "opening_hours": "24/7",
        "status": "damaged",
        "operator_name": "PKP SA",
        "operator_phone": "+48 52 345 67 89",
        "last_verified_at": "2026-11-18T09:00:00",
        "quality_score": 30,
    },
    # 24 — Remontowany sklep (tymczasowo niedostępny)
    {
        "aed_id": "aed-byd-024",
        "source_name": "Zgloszenie_Dysponenta",
        "source_id": "ZD-2026-024",
        "latitude": 53.1280,
        "longitude": 17.9960,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Dworcowa 68",
        "address_postal_code": "85-010",
        "location_description": "Wejście do sklepu Rossmann - REMONT, AED zdemontowany tymczasowo",
        "indoor": True,
        "access_type": "customers",
        "opening_hours": "Mo-Sa 08:00-21:00; Su 10:00-18:00",
        "status": "temporarily_unavailable",
        "operator_name": "Rossmann Bydgoszcz",
        "operator_phone": "+48 52 371 00 00",
        "last_verified_at": "2026-11-10T10:00:00",
        "quality_score": 20,
    },
    # 25 — Niezweryfikowane zgłoszenie
    {
        "aed_id": "aed-byd-025",
        "source_name": "Zgloszenie_Dysponenta",
        "source_id": "ZD-2026-025",
        "latitude": 53.1190,
        "longitude": 18.0200,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Bernardyńska 10",
        "address_postal_code": "85-029",
        "location_description": "Wejście do kamienicy, klatka schodowa, brak szczegółów",
        "indoor": True,
        "access_type": "private",
        "opening_hours": "Mo-Fr 08:00-16:00",
        "status": "unverified",
        "operator_name": "",
        "operator_phone": "",
        "quality_score": 15,
    },
    # ── INTENTIONAL DUPLICATES (within 30m of earlier entries) ──
    # 26 — Duplicate of #1 (Dworzec) — 20m away, different source
    {
        "aed_id": "aed-byd-026",
        "source_name": "UM_Bydgoszcz",
        "source_id": "UM-AED-026",
        "latitude": 53.13265,
        "longitude": 18.00120,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Zygmunta Augusta 7",
        "address_postal_code": "85-082",
        "location_description": "Hala główna Dworca Bydgoszcz Główna",
        "indoor": True,
        "access_type": "public",
        "opening_hours": "24/7",
        "status": "active",
        "operator_name": "PKP SA",
        "operator_phone": "+48 52 345 67 89",
        "last_verified_at": "2026-10-10T12:00:00",
        "quality_score": 70,
    },
    # 27 — Duplicate of #4 (Stary Rynek) — 15m away
    {
        "aed_id": "aed-byd-027",
        "source_name": "Zgloszenie_Dysponenta",
        "source_id": "ZD-2026-027",
        "latitude": 53.12412,
        "longitude": 18.00465,
        "address_city": "Bydgoszcz",
        "address_street": "Rynek Staromiejski",
        "location_description": "",
        "indoor": False,
        "access_type": "public",
        "opening_hours": "24/7",
        "status": "active",
        "operator_name": "",
        "operator_phone": "",
        "quality_score": 25,
    },
    # 28 — Duplicate of #13 (Wyspa Młyńska) — 25m away
    {
        "aed_id": "aed-byd-028",
        "source_name": "Demo_OSM",
        "source_id": "node/9801234599",
        "latitude": 53.12282,
        "longitude": 18.00615,
        "address_city": "Bydgoszcz",
        "address_street": "Wyspa Młyńska",
        "location_description": "Totem przy moście, Wyspa Młyńska",
        "indoor": False,
        "access_type": "public",
        "opening_hours": "24/7",
        "status": "active",
        "operator_name": "Miasto Bydgoszcz",
        "operator_phone": "+48 52 585 86 00",
        "quality_score": 60,
    },
]


def seed_database(db: sqlite3.Connection) -> int:
    """Insert seed data, return count of inserted rows. Skips if data exists."""
    cur = db.execute("SELECT COUNT(*) FROM aed")
    if cur.fetchone()[0] > 0:
        return 0

    inserted = 0
    for rec in SEED_DATA:
        cols = list(rec.keys())
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        vals = []
        for c in cols:
            v = rec[c]
            if isinstance(v, bool):
                v = int(v)
            vals.append(v)
        db.execute(f"INSERT OR IGNORE INTO aed ({col_names}) VALUES ({placeholders})", vals)
        inserted += 1
    backfill_source_links(db)
    db.commit()
    return inserted


# ── Rekordy demonstracyjne dla presetów dyspozytora ──────────────────
# Dopisywane/odświeżane przy KAŻDYM starcie (także na bazie z pełnym importem),
# żeby scenariusze z prezentacji zawsze działały tak samo. Status wraca do
# „active”, więc zgłoszenie „AED niedostępny” z poprzedniego pokazu nie zostaje.
DEMO_RECORDS: list[dict] = [
    {
        "aed_id": "aed-demo-centrum",
        "source_name": "Demo_OSM",
        "source_id": "demo/centrum",
        "latitude": 53.12395,
        "longitude": 18.00055,
        "address_city": "Bydgoszcz",
        "address_street": "Stary Rynek 1",
        "address_postal_code": "85-105",
        "location_description": "Parter, na ścianie przy głównej klatce schodowej obok windy – wejście od strony Starego Rynku",
        "indoor": 1,
        "access_type": "public",
        "access_code": "1912",
        "opening_hours": "24/7",
        "status": "active",
        "operator_name": "Urząd Miasta Bydgoszczy",
        "operator_phone": "+48 52 585 80 00",
        "operator_email": "aed@um.bydgoszcz.pl",
        "last_verified_at": "2026-11-15T09:00:00",
        "quality_score": 100,
    },
    {
        "aed_id": "aed-demo-biuro",
        "source_name": "Demo_OSM",
        "source_id": "demo/biuro",
        "latitude": 53.12290,
        "longitude": 18.05580,
        "address_city": "Bydgoszcz",
        "address_street": "ul. Fordońska 120",
        "address_postal_code": "85-739",
        "location_description": "Hol przy recepcji, prawa ściana, za bramkami wejściowymi – budynek biurowy B, parter",
        "indoor": 1,
        "access_type": "customers",
        "access_code": None,
        "opening_hours": "Mo-Fr 08:00-18:00",
        "status": "active",
        "operator_name": "Centrum Biurowe Fordońska",
        "operator_phone": "+48 52 300 12 00",
        "operator_email": "recepcja@cbfordonska.pl",
        "last_verified_at": "2026-11-10T12:00:00",
        "quality_score": 100,
    },
]


def ensure_demo_records(db: sqlite3.Connection) -> None:
    for rec in DEMO_RECORDS:
        cols = list(rec)
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "aed_id")
        db.execute(
            f"INSERT INTO aed ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
            f"ON CONFLICT(aed_id) DO UPDATE SET {updates}, updated_at = datetime('now')",
            [rec[c] for c in cols],
        )
        db.execute(
            "INSERT OR IGNORE INTO aed_source (source_name, source_id, aed_id) VALUES (?, ?, ?)",
            (rec["source_name"], rec["source_id"], rec["aed_id"]),
        )
    db.commit()
