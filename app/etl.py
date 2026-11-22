"""Pulsmap – ETL engine: validation, Haversine dedup, opening_hours parser, xlsx generator."""

from __future__ import annotations

import math
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

from app.models import AEDRecord, AEDRecordIngest, AEDStatus, IngestReport
from app.opening_hours import Availability, availability


# ═══════════════════════════════════════════════════════════════════════
# 1. HAVERSINE DISTANCE
# ═══════════════════════════════════════════════════════════════════════
EARTH_RADIUS_M = 6_371_000


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in metres between two WGS84 points."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ═══════════════════════════════════════════════════════════════════════
# 2. OPENING HOURS – patrz app/opening_hours.py
# ═══════════════════════════════════════════════════════════════════════
def is_open(opening_hours: str, dt: datetime) -> tuple[bool, str]:
    """Zgodność wsteczna: True tylko dla potwierdzonego „otwarte”."""
    state, reason = availability(opening_hours, dt)
    return state == Availability.open, reason


# ═══════════════════════════════════════════════════════════════════════
# 3. QUALITY SCORE CALCULATOR
# ═══════════════════════════════════════════════════════════════════════
def compute_quality_score(rec: dict) -> int:
    score = 0
    # Required fields present
    if rec.get("address_city"):
        score += 10
    if rec.get("address_street"):
        score += 10
    if rec.get("address_postal_code"):
        score += 5
    if rec.get("location_description"):
        score += 15
    if rec.get("operator_name"):
        score += 10
    if rec.get("operator_phone"):
        score += 10
    if rec.get("operator_email"):
        score += 5
    if rec.get("opening_hours"):
        score += 10
    if rec.get("last_verified_at"):
        score += 15
        # Freshness bonus: within last 6 months
        try:
            lv = datetime.fromisoformat(rec["last_verified_at"])
            if (datetime.now() - lv) < timedelta(days=180):
                score += 10
        except (ValueError, TypeError):
            pass
    # Indoor flag explicitly set counts
    score += 5  # indoor field always present as bool
    return min(score, 100)


# ═══════════════════════════════════════════════════════════════════════
# 4. INGEST + DEDUPLIKACJA (source_id → przestrzennie)
# ═══════════════════════════════════════════════════════════════════════
DEDUP_RADIUS_M = 30.0
# ~30 m w stopniach na szerokości Polski
_DLAT, _DLON = 0.00035, 0.00055

# Pola, których nie nadpisujemy danymi źródła
_META_FIELDS = {"aed_id", "source_name", "source_id", "quality_score", "created_at", "updated_at"}
# Pola, które przy świeższej weryfikacji z innego źródła mają pierwszeństwo
_FRESHNESS_FIELDS = {"status", "opening_hours", "access_type", "location_description"}
# Statusy zgłoszone „z terenu” – nie cofamy ich importem bez świeższej weryfikacji
_FIELD_REPORTED_STATUSES = {"temporarily_unavailable", "damaged"}


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def _blank(v) -> bool:
    return v is None or v == ""


def _parse_dt(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v))
    except ValueError:
        return None
    return dt.replace(tzinfo=None)


def _is_newer(a, b) -> bool:
    """Czy znacznik *a* jest świeższy niż *b* (brak = najstarszy)."""
    da, db_ = _parse_dt(a), _parse_dt(b)
    return da is not None and (db_ is None or da > db_)


def _merge_records(existing: dict, new_rec: dict) -> dict:
    """Scalenie rekordów z RÓŻNYCH źródeł opisujących to samo urządzenie.

    Domyślnie zostają wartości istniejące, puste pola uzupełniamy nowymi.
    Jeżeli nowy rekord ma świeższą weryfikację (last_verified_at), jego status,
    godziny, dostępność i opis lokalizacji wygrywają.
    """
    merged = dict(existing)
    fresher = _is_newer(new_rec.get("last_verified_at"), existing.get("last_verified_at"))
    for key, new_val in new_rec.items():
        if key in ("aed_id", "created_at", "updated_at", "source_id", "quality_score"):
            continue
        if key == "source_name":
            sources = {s for s in (existing.get("source_name") or "").split("+") if s}
            sources.add(new_val)
            merged["source_name"] = "+".join(sorted(sources))
            continue
        if _blank(new_val):
            continue
        if _blank(existing.get(key)) or (fresher and (key in _FRESHNESS_FIELDS or key == "last_verified_at")):
            merged[key] = new_val
    now = datetime.now().isoformat()
    if merged.get("status") != existing.get("status"):
        merged["status_updated_at"] = now
    merged["quality_score"] = compute_quality_score(merged)
    merged["updated_at"] = now
    return merged


def _apply_source_update(existing: dict, new_rec: dict) -> dict:
    """Aktualizacja rekordu przez TO SAMO źródło (ponowny import): źródło jest
    autorytatywne dla podanych przez siebie pól, więc nadpisujemy niepuste wartości."""
    updated = dict(existing)
    for key, new_val in new_rec.items():
        if key in _META_FIELDS or _blank(new_val):
            continue
        if (
            key == "status"
            and existing.get("status") in _FIELD_REPORTED_STATUSES
            and not _is_newer(new_rec.get("last_verified_at"), existing.get("status_updated_at"))
        ):
            continue
        updated[key] = new_val
    now = datetime.now().isoformat()
    if updated.get("status") != existing.get("status"):
        updated["status_updated_at"] = now
    updated["quality_score"] = compute_quality_score(updated)
    updated["updated_at"] = now
    return updated


def _write_update(db: sqlite3.Connection, aed_id: str, rec: dict) -> None:
    cols = [k for k in rec if k != "aed_id"]
    db.execute(
        f"UPDATE aed SET {', '.join(f'{c} = ?' for c in cols)} WHERE aed_id = ?",
        [int(rec[c]) if isinstance(rec[c], bool) else rec[c] for c in cols] + [aed_id],
    )


def _link_source(db: sqlite3.Connection, source_name: str, source_id: str, aed_id: str) -> None:
    if not source_id:
        return
    now = datetime.now().isoformat()
    db.execute(
        """INSERT INTO aed_source (source_name, source_id, aed_id, first_seen_at, last_seen_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(source_name, source_id) DO UPDATE SET aed_id = excluded.aed_id,
                                                           last_seen_at = excluded.last_seen_at""",
        (source_name, source_id, aed_id, now, now),
    )


def _find_spatial_duplicate(db: sqlite3.Connection, rec: dict) -> tuple[Optional[dict], float]:
    """Najbliższe AED w promieniu DEDUP_RADIUS_M, które może być tym samym urządzeniem.

    Pomijamy kandydatów, którzy mają już powiązanie z TYM SAMYM źródłem pod innym
    source_id – źródło twierdzi wtedy, że to dwa różne urządzenia (np. dwa AED
    w jednym budynku), więc nie wolno ich scalić.
    """
    lat, lon = rec["latitude"], rec["longitude"]
    rows = db.execute(
        "SELECT * FROM aed WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?",
        (lat - _DLAT, lat + _DLAT, lon - _DLON, lon + _DLON),
    ).fetchall()
    best, best_dist = None, float("inf")
    for row in rows:
        cand = _row_to_dict(row)
        dist = haversine_m(lat, lon, cand["latitude"], cand["longitude"])
        if dist > DEDUP_RADIUS_M or dist >= best_dist:
            continue
        if rec.get("source_id"):
            same_source = db.execute(
                "SELECT 1 FROM aed_source WHERE aed_id = ? AND source_name = ? AND source_id != ?",
                (cand["aed_id"], rec["source_name"], rec["source_id"]),
            ).fetchone()
            if same_source:
                continue
        best, best_dist = cand, dist
    return best, best_dist


def ingest_records(
    db: sqlite3.Connection,
    records: list[dict],
    *,
    sync_source: Optional[str] = None,
) -> IngestReport:
    """Walidacja, dopasowanie i zapis rekordów.

    Kolejność dopasowania:
      1. (source_name, source_id) już znane → aktualizacja tego samego rekordu,
      2. AED innego źródła w promieniu 30 m → scalenie,
      3. w przeciwnym razie nowy rekord.

    ``sync_source`` – podaj, gdy *records* to PEŁNY zrzut danego źródła; urządzenia
    tego źródła, których w zrzucie zabrakło (i nie potwierdza ich inne źródło),
    dostają status ``unverified``.
    """
    errors: list[str] = []
    valid_count = inserted = updated = dedup_count = 0
    seen_ids: set[str] = set()

    for i, raw in enumerate(records):
        raw = dict(raw)
        raw.setdefault("aed_id", None)
        try:
            rec = AEDRecordIngest(**raw)
        except Exception as e:
            errors.append(f"Rekord {i + 1}: {e}")
            continue

        rec_dict = rec.model_dump(mode="json")
        rec_dict["aed_id"] = rec_dict["aed_id"] or str(uuid.uuid4())
        src, sid = rec_dict["source_name"], rec_dict["source_id"]
        if sid:
            seen_ids.add(sid)

        # 1. Ten sam rekord tego samego źródła
        known = None
        if sid:
            known = db.execute(
                """SELECT a.* FROM aed_source s JOIN aed a ON a.aed_id = s.aed_id
                   WHERE s.source_name = ? AND s.source_id = ?""",
                (src, sid),
            ).fetchone()
        if known:
            existing = _row_to_dict(known)
            _write_update(db, existing["aed_id"], _apply_source_update(existing, rec_dict))
            _link_source(db, src, sid, existing["aed_id"])
            updated += 1
            valid_count += 1
            continue

        # 2. To samo urządzenie z innego źródła
        duplicate_of, dist = _find_spatial_duplicate(db, rec_dict)
        if duplicate_of:
            _write_update(db, duplicate_of["aed_id"], _merge_records(duplicate_of, rec_dict))
            _link_source(db, src, sid, duplicate_of["aed_id"])
            db.execute(
                "INSERT INTO dedup_log (kept_aed_id, merged_source, distance_m) VALUES (?, ?, ?)",
                (duplicate_of["aed_id"], src, dist),
            )
            dedup_count += 1
        else:
            # 3. Nowe urządzenie
            # quality_score zawsze liczymy sami – wartość od dysponenta ignorujemy
            rec_dict["quality_score"] = compute_quality_score(rec_dict)
            cols = list(rec_dict)
            db.execute(
                f"INSERT INTO aed ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [int(v) if isinstance(v, bool) else v for v in rec_dict.values()],
            )
            _link_source(db, src, sid, rec_dict["aed_id"])
            inserted += 1

        valid_count += 1

    marked_missing = 0
    if sync_source:
        marked_missing = _mark_missing_from_source(db, sync_source, seen_ids)

    db.commit()
    return IngestReport(
        total_submitted=len(records),
        valid=valid_count,
        duplicates_merged=dedup_count,
        inserted=inserted,
        updated=updated,
        marked_missing=marked_missing,
        errors=errors,
    )


def _mark_missing_from_source(db: sqlite3.Connection, source_name: str, seen_ids: set[str]) -> int:
    """Urządzenia potwierdzane wyłącznie przez *source_name*, których nie ma w
    pełnym zrzucie, oznaczamy jako ``unverified`` (nie usuwamy – historia zostaje)."""
    rows = db.execute(
        """SELECT s.source_id, a.aed_id, a.source_name FROM aed_source s
           JOIN aed a ON a.aed_id = s.aed_id
           WHERE s.source_name = ? AND a.status = 'active'""",
        (source_name,),
    ).fetchall()
    now = datetime.now().isoformat()
    count = 0
    for source_id, aed_id, combined_sources in rows:
        if source_id in seen_ids or combined_sources != source_name:
            continue
        db.execute(
            "UPDATE aed SET status = 'unverified', updated_at = ?, status_updated_at = ? WHERE aed_id = ?",
            (now, now, aed_id),
        )
        count += 1
    return count


# ═══════════════════════════════════════════════════════════════════════
# 5. XLSX SCHEMA GENERATOR
# ═══════════════════════════════════════════════════════════════════════

SCHEMA_FIELDS = [
    ("aed_id", "TEXT (UUID)", "Tak", "Unikalny identyfikator urządzenia AED",
     "550e8400-e29b-41d4-a716-446655440000", "UUID v4, unikalny w zbiorze"),
    ("source_name", "TEXT", "Tak", "Nazwa źródła danych",
     "OSM", "Niepuste, np. OSM, UM_Bydgoszcz, Zgloszenie_Dysponenta"),
    ("source_id", "TEXT", "Nie", "Identyfikator rekordu w systemie źródłowym",
     "node/9801234567", "Dowolny tekst"),
    ("latitude", "REAL", "Tak", "Szerokość geograficzna w układzie WGS84",
     "53.1325", "49.0 ≤ lat ≤ 54.9 (granice Polski)"),
    ("longitude", "REAL", "Tak", "Długość geograficzna w układzie WGS84",
     "18.0010", "14.1 ≤ lon ≤ 24.2 (granice Polski)"),
    ("address_city", "TEXT", "Nie", "Nazwa miasta", "Bydgoszcz", "Tekst"),
    ("address_street", "TEXT", "Nie", "Ulica i numer", "ul. Zygmunta Augusta 7", "Tekst"),
    ("address_postal_code", "TEXT", "Nie", "Kod pocztowy", "85-082", "Format XX-XXX"),
    ("location_description", "TEXT", "Nie",
     "Dokładny opis lokalizacji urządzenia",
     "Hala główna dworca, filar przy wejściu", "Tekst, jak najdokładniejszy"),
    ("indoor", "BOOLEAN", "Tak", "Czy urządzenie znajduje się wewnątrz budynku",
     "true", "true / false"),
    ("access_type", "ENUM", "Tak", "Typ dostępności",
     "public", "Dozwolone: public, customers, private, permissive"),
    ("access_code", "TEXT", "Nie",
     "Kod dostępu do szafki AED. NIE jest publikowany w otwartym zbiorze – przekazywany "
     "wyłącznie do CPR/dyspozytorów 112. W publicznym zbiorze zastępuje go pole has_access_code.",
     "1234", "Tekst lub null; pole niepubliczne"),
    ("has_access_code", "BOOLEAN", "Tak",
     "Czy szafka AED jest zamykana na kod (pole publiczne, wyliczane z access_code)",
     "false", "true / false"),
    ("opening_hours", "TEXT", "Tak", "Godziny dostępności w formacie OSM opening_hours",
     "24/7", "Np. 24/7, Mo-Fr 08:00-18:00 (= Pn-Pt), Mo-Sa 09:00-21:00; Su 10:00-20:00. Skróty dni OSM: Mo=Pn, Tu=Wt, We=Śr, Th=Cz, Fr=Pt, Sa=Sb, Su=Nd, PH=święta. Formularz przyjmuje też zapis polski i zapisuje go w standardzie OSM."),
    ("status", "ENUM", "Tak", "Status urządzenia",
     "active", "Dozwolone: active, temporarily_unavailable, damaged, unverified"),
    ("operator_name", "TEXT", "Nie", "Nazwa operatora/właściciela",
     "PKP SA", "Tekst"),
    ("operator_phone", "TEXT", "Nie", "Telefon kontaktowy operatora",
     "+48 52 345 67 89", "Format międzynarodowy"),
    ("operator_email", "TEXT", "Nie", "Adres e-mail operatora",
     "aed@pkp.pl", "Poprawny format e-mail"),
    ("last_verified_at", "DATETIME", "Nie", "Data i czas ostatniej weryfikacji",
     "2026-09-15T10:00:00", "ISO-8601 (YYYY-MM-DDTHH:MM:SS)"),
    ("quality_score", "INTEGER", "Tak",
     "Wynik jakości rekordu obliczany automatycznie na podstawie kompletności pól i świeżości weryfikacji",
     "95", "0–100, wyliczany automatycznie"),
]


def generate_schema_xlsx(db: sqlite3.Connection) -> BytesIO:
    """Generate wzorcowy_zakres_danych_aed.xlsx with two sheets."""
    wb = Workbook()

    # ── Sheet 1: Specyfikacja_Pol ──
    ws1 = wb.active
    ws1.title = "Specyfikacja_Pol"

    header_font = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
    header_fill = PatternFill(start_color="2E5090", end_color="2E5090", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    headers = ["Nazwa pola", "Typ danych", "Wymagane", "Opis", "Przykład", "Reguła walidacji"]
    for col, h in enumerate(headers, 1):
        cell = ws1.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    for row_idx, field in enumerate(SCHEMA_FIELDS, 2):
        for col_idx, val in enumerate(field, 1):
            cell = ws1.cell(row=row_idx, column=col_idx, value=val)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = thin_border

    # Column widths
    ws1.column_dimensions["A"].width = 22
    ws1.column_dimensions["B"].width = 15
    ws1.column_dimensions["C"].width = 12
    ws1.column_dimensions["D"].width = 45
    ws1.column_dimensions["E"].width = 35
    ws1.column_dimensions["F"].width = 40

    # ── Sheet 2: Przykladowe_Dane ──
    ws2 = wb.create_sheet("Przykladowe_Dane")

    field_names = [f[0] for f in SCHEMA_FIELDS]
    for col, h in enumerate(field_names, 1):
        cell = ws2.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    # Pull sample data from DB
    rows = db.execute("SELECT * FROM aed LIMIT 10").fetchall()
    for row_idx, row in enumerate(rows, 2):
        row_dict = _row_to_dict(row)
        for col_idx, fname in enumerate(field_names, 1):
            val = row_dict.get(fname, "")
            if fname == "access_code":
                val = None  # pole niepubliczne – nie pokazujemy prawdziwych kodów
            elif fname == "has_access_code":
                val = bool(row_dict.get("access_code"))
            if fname == "indoor":
                val = bool(val) if val is not None else False
            cell = ws2.cell(row=row_idx, column=col_idx, value=val)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = thin_border

    # Auto-width for sheet 2
    for col_idx, fname in enumerate(field_names, 1):
        ws2.column_dimensions[ws2.cell(row=1, column=col_idx).column_letter].width = max(len(fname) + 4, 15)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════════════
# 6. OVERPASS API FETCHER (live OSM data with fallback)
# ═══════════════════════════════════════════════════════════════════════

OVERPASS_QUERY_PL = """
[out:json][timeout:120];
area["ISO3166-1"="PL"]->.poland;
(
  node["emergency"="defibrillator"](area.poland);
  way["emergency"="defibrillator"](area.poland);
);
out center body;
"""

# Regional grid for fallback (if full-country query times out)
_PL_REGIONS = [
    # (name, south, west, north, east)
    ("Dolnośląskie",        50.8, 14.8, 51.8, 17.1),
    ("Kujawsko-Pomorskie",  52.3, 17.4, 53.6, 19.5),
    ("Lubelskie",           50.3, 21.5, 52.0, 24.2),
    ("Lubuskie",            51.4, 14.5, 52.6, 16.3),
    ("Łódzkie",             51.0, 18.5, 52.4, 20.5),
    ("Małopolskie",         49.2, 19.0, 50.5, 21.3),
    ("Mazowieckie",         51.0, 19.5, 53.0, 22.0),
    ("Opolskie",            50.2, 16.8, 51.1, 18.4),
    ("Podkarpackie",        49.0, 21.0, 50.6, 23.2),
    ("Podlaskie",           52.6, 21.5, 54.4, 24.2),
    ("Pomorskie",           53.5, 16.7, 54.9, 19.7),
    ("Śląskie",             49.6, 18.0, 50.8, 20.0),
    ("Świętokrzyskie",      50.3, 19.7, 51.1, 21.4),
    ("Warmińsko-Mazurskie", 53.2, 19.0, 54.5, 22.5),
    ("Wielkopolskie",       51.5, 15.8, 53.0, 18.6),
    ("Zachodniopomorskie",  53.1, 14.1, 54.5, 17.0),
]


def _parse_osm_element(el: dict) -> dict:
    """Convert an Overpass API element to our AED record format."""
    tags = el.get("tags", {})

    # center for ways, direct lat/lon for nodes
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")
    if lat is None or lon is None:
        return {}

    # Clamp to Poland bounds
    if not (49.0 <= lat <= 54.9 and 14.1 <= lon <= 24.2):
        return {}

    # Parse access type
    access_raw = tags.get("access", "yes")
    access_map = {"yes": "public", "public": "public", "customers": "customers",
                  "private": "private", "permissive": "permissive", "no": "private"}
    access_type = access_map.get(access_raw, "public")

    # Build location description from multiple OSM tags
    desc_parts = []
    for tag_key in ("defibrillator:location", "defibrillator:location:pl",
                    "description", "description:pl", "note"):
        v = tags.get(tag_key, "").strip()
        if v and v not in desc_parts:
            desc_parts.append(v)
    location_desc = "; ".join(desc_parts)

    return {
        "source_name": "OSM",
        "source_id": f"{el.get('type', 'node')}/{el['id']}",
        "latitude": lat,
        "longitude": lon,
        "address_city": tags.get("addr:city", tags.get("addr:place", "")),
        "address_street": _build_street(tags),
        "address_postal_code": tags.get("addr:postcode", ""),
        "location_description": location_desc,
        "indoor": tags.get("indoor", "no") == "yes",
        "access_type": access_type,
        "access_code": tags.get("defibrillator:access:code",
                                tags.get("access:code", None)) or None,
        "opening_hours": tags.get("opening_hours", "24/7"),
        "status": "active",
        "operator_name": tags.get("operator", ""),
        "operator_phone": tags.get("phone", tags.get("contact:phone", "")),
        "operator_email": tags.get("email", tags.get("contact:email", "")),
    }


def _build_street(tags: dict) -> str:
    street = tags.get("addr:street", "")
    housenumber = tags.get("addr:housenumber", "")
    if street and housenumber:
        return f"{street} {housenumber}"
    return street or housenumber


async def _fetch_overpass(query: str, timeout: int = 120) -> list[dict]:
    """Execute a single Overpass query. Returns raw elements."""
    import httpx
    async with httpx.AsyncClient(timeout=timeout + 30) as client:
        resp = await client.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
        )
        resp.raise_for_status()
        data = resp.json()
    return data.get("elements", [])


async def fetch_osm_aeds() -> list[dict]:
    """Fetch ALL AEDs in Poland from Overpass API (list of parsed records)."""
    records, _complete = await fetch_osm_aeds_snapshot()
    return records


async def fetch_osm_aeds_snapshot() -> tuple[list[dict], bool]:
    """Fetch ALL AEDs in Poland from Overpass API.

    Strategy:
      1. Try full-country query first.
      2. If it times out, fall back to 16 regional queries.
    Returns (records, complete) – *complete* is True only when every query
    succeeded, i.e. the result can be treated as a full snapshot of OSM.
    """
    complete = True
    import httpx
    import asyncio
    import logging

    logger = logging.getLogger("pulsemap.etl")
    all_elements: list[dict] = []

    # ── Attempt 1: full country ──
    try:
        logger.info("OSM: pobieranie AED z całej Polski (pełne zapytanie)…")
        all_elements = await _fetch_overpass(OVERPASS_QUERY_PL, timeout=120)
        logger.info(f"OSM: pobrano {len(all_elements)} elementów (cała Polska)")
    except Exception as e:
        logger.warning(f"OSM: pełne zapytanie nie powiodło się ({e}), przechodzę do trybu regionalnego…")

        # ── Attempt 2: regional grid ──
        seen_ids: set[int] = set()
        for name, south, west, north, east in _PL_REGIONS:
            query = f"""
[out:json][timeout:30];
(
  node["emergency"="defibrillator"]({south},{west},{north},{east});
  way["emergency"="defibrillator"]({south},{west},{north},{east});
);
out center body;
"""
            try:
                elements = await _fetch_overpass(query, timeout=45)
                new_count = 0
                for el in elements:
                    eid = el.get("id")
                    if eid and eid not in seen_ids:
                        seen_ids.add(eid)
                        all_elements.append(el)
                        new_count += 1
                logger.info(f"  {name}: +{new_count} AED")
            except Exception as ex:
                complete = False
                logger.warning(f"  {name}: błąd ({ex})")
            # polite delay between requests
            await asyncio.sleep(1)

        logger.info(f"OSM: łącznie pobrano {len(all_elements)} elementów (tryb regionalny)")

    # ── Parse ──
    results = []
    for el in all_elements:
        rec = _parse_osm_element(el)
        if rec:
            results.append(rec)

    logger.info(f"OSM: sparsowano {len(results)} rekordów AED")
    return results, complete and bool(results)
