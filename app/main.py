"""Pulsmap – FastAPI main application: API endpoints + HTML views."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import time
import secrets
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, UploadFile, File, Form, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import ensure_demo_records, get_db, seed_database
from app.etl import (
    haversine_m,
    ingest_records,
    generate_schema_xlsx,
    fetch_osm_aeds_snapshot,
)
from app.opening_hours import Availability, availability, format_pl
from app.regions import RegionStat, assign_voivodeship, load_voivodeships, region_stats
from app.wykaz_aed import aed_to_wykaz_row, dane_gov_pl_xml, wykaz_csv, wzorcowy_zakres_xlsx
from app.portal_sync import sync_from_portal
import httpx
from app.dispatch import ScanResult, scan_radius
from urllib.parse import urlparse
from app.models import (
    DispatcherSessionRequest,
    SessionCreated,
    NearestAED,
    RejectedAED,
    DispatcherResponse,
    DispatcherSendRouteRequest,
    RescueEventRequest,
    RescueStatusResponse,
    VerificationRequest,
    StatsResponse,
    IngestReport,
)

logger = logging.getLogger("pulsemap")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# Klucz chroniący endpointy zapisu (import danych). Bez niego API działa w trybie
# demonstracyjnym – każdy może importować dane (ostrzeżenie w logach).
API_KEY = os.environ.get("PULSEMAP_API_KEY", "")

# Po tym czasie link ratunkowy /go/{token} nie może już zmieniać stanu AED.
RESCUE_SESSION_TTL = timedelta(hours=6)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db = get_db()
    count = seed_database(db)
    if count:
        logger.info(f"Seed: wstawiono {count} rekordów AED (Bydgoszcz)")
    ensure_demo_records(db)
    if not API_KEY:
        logger.warning("PULSEMAP_API_KEY nie ustawiony – endpointy importu są otwarte (tryb demo)")
    logger.info("Pulsmap started ✓")
    yield


app = FastAPI(
    title="Pulsmap – Ogólnopolska Baza AED",
    description="Prototyp systemu agregacji danych o defibrylatorach AED – HackNation 2026",
    version="1.0.0",
    lifespan=lifespan,
)


def require_api_key(x_api_key: str = Header(default="")) -> None:
    if API_KEY and not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Wymagany poprawny nagłówek X-API-Key")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["hours_pl"] = format_pl
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ═══════════════════════════════════════════════════════════════════════
# HELPER: row → dict
# ═══════════════════════════════════════════════════════════════════════
def _row_dict(row) -> dict:
    return {k: row[k] for k in row.keys()}


def _all_aeds(db=None) -> list[dict]:
    if db is None:
        db = get_db()
    rows = db.execute("SELECT * FROM aed ORDER BY address_city, address_street").fetchall()
    return [_row_dict(r) for r in rows]


# Pola, których nie publikujemy w otwartym zbiorze. Kod do szafki AED trafia
# wyłącznie do dyspozytora 112 i na ekran świadka w trakcie akcji ratunkowej.
NON_PUBLIC_FIELDS = ("access_code",)


def _public_aed(aed: dict) -> dict:
    out = {k: v for k, v in aed.items() if k not in NON_PUBLIC_FIELDS}
    out["has_access_code"] = bool(aed.get("access_code"))
    out["indoor"] = bool(aed.get("indoor"))
    return out


def _public_aeds(db=None) -> list[dict]:
    return [_public_aed(a) for a in _all_aeds(db)]


PL_TZ = ZoneInfo("Europe/Warsaw")


def now_pl() -> datetime:
    """Aktualny czas w Polsce (naiwny) – godziny AED są podawane w czasie lokalnym,
    a kontener zwykle działa w UTC."""
    return datetime.now(PL_TZ).replace(tzinfo=None)


def _session_expired(session: dict) -> bool:
    try:
        created = datetime.fromisoformat(session.get("created_at") or "")
    except ValueError:
        return False
    return datetime.now(timezone.utc).replace(tzinfo=None) - created > RESCUE_SESSION_TTL


# ═══════════════════════════════════════════════════════════════════════
# API: OPEN DATA EXPORTS
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/v1/aeds")
async def api_aeds():
    """Return all AEDs as JSON (for map). Bez kodów do szafek.

    ``hours_status`` (open/closed/unknown) to stan chwilowy dla mapy – nie trafia
    do eksportów zbioru danych.
    """
    now = now_pl()
    aeds = _public_aeds()
    for a in aeds:
        a["hours_status"] = availability(a.get("opening_hours") or "24/7", now)[0].value
    return aeds


@app.get("/api/v1/export/csv")
async def export_csv():
    """Export full dataset as CSV (UTF-8 BOM, dane.gov.pl ready)."""
    aeds = _public_aeds()
    if not aeds:
        return JSONResponse({"error": "Brak danych"}, status_code=404)

    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM for Excel
    fieldnames = [
        "aed_id", "source_name", "source_id", "latitude", "longitude",
        "address_city", "address_street", "address_postal_code",
        "location_description", "indoor", "access_type", "has_access_code",
        "opening_hours", "status", "operator_name", "operator_phone",
        "operator_email", "last_verified_at", "quality_score",
        "certified", "certified_at", "certified_by", "verification_count",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for aed in aeds:
        writer.writerow({k: aed.get(k, "") for k in fieldnames})

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=pulsemap_aed_export.csv"},
    )


@app.get("/api/v1/export/json")
async def export_json():
    """Export as JSON array (dane.gov.pl ready)."""
    aeds = _public_aeds()
    return JSONResponse(
        content=aeds,
        headers={"Content-Disposition": "attachment; filename=pulsemap_aed_export.json"},
    )


@app.get("/api/v1/export/geojson")
async def export_geojson():
    """Export as GeoJSON FeatureCollection (dane.gov.pl / map apps ready)."""
    aeds = _public_aeds()
    features = []
    for a in aeds:
        props = {k: v for k, v in a.items() if k not in ("latitude", "longitude")}
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [a["longitude"], a["latitude"]],
            },
            "properties": props,
        })
    geojson = {"type": "FeatureCollection", "features": features}
    return JSONResponse(
        content=geojson,
        headers={"Content-Disposition": "attachment; filename=pulsemap_aed_export.geojson"},
    )


@app.get("/api/v1/export/schema-xlsx")
async def export_schema_xlsx():
    """Download wzorcowy_zakres_danych_aed.xlsx."""
    # Zakres danych wykazu defibrylatorów AED – identyczny z tym, który sprawdza portal dane.gov.pl
    buf = wzorcowy_zakres_xlsx(_wykaz_rows()[:5])
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=wzorcowy_zakres_danych_aed.xlsx"},
    )


# ═══════════════════════════════════════════════════════════════════════
# dane.gov.pl: wykaz defibrylatorów AED (zasilanie ręczne i automatyczne)
# ═══════════════════════════════════════════════════════════════════════
_wykaz_cache: tuple[datetime, list[dict]] | None = None


def _wykaz_rows() -> list[dict]:
    """Wiersze wykazu AED (z województwem liczonym ze współrzędnych), cache 10 min."""
    global _wykaz_cache
    now = datetime.now()
    if _wykaz_cache and now - _wykaz_cache[0] < REGIONS_CACHE_TTL:
        return _wykaz_cache[1]
    regions = load_voivodeships(REGIONS_PATH)
    db = get_db()
    rows = []
    for i, r in enumerate(db.execute("SELECT * FROM aed ORDER BY aed_id"), start=1):
        aed = _row_dict(r)
        rows.append(aed_to_wykaz_row(aed, i, assign_voivodeship(aed["latitude"], aed["longitude"], regions)))
    _wykaz_cache = (now, rows)
    return rows


@app.api_route("/api/v1/export/wykaz-aed.csv", methods=["GET", "HEAD"])
def export_wykaz_aed_csv():
    """Wykaz AED w zakresie kolumn portalu dane.gov.pl – plik do zasilenia ręcznego
    (panel administracyjny) i źródło zasobu przy imporcie XML."""
    return Response(
        content=wykaz_csv(_wykaz_rows()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=wykaz_defibrylatorow_aed.csv"},
    )


def _dane_gov_pl_xml_bytes() -> bytes:
    # Portal przyjmuje w imporcie XML tylko adresy https – lokalnie Pulsmap jest
    # wystawiony przez nginx portalu pod https://mcod.local/pulsmap
    base = os.environ.get("PULSEMAP_DANE_GOV_PL_SOURCE_URL") or "https://mcod.local/pulsmap"
    return dane_gov_pl_xml(base, today=now_pl().date().isoformat()).encode("utf-8")


@app.api_route("/api/v1/export/dane-gov-pl.xml", methods=["GET", "HEAD"])
def export_dane_gov_pl_xml():
    """Plik XML dla źródła danych portalu (import XML, schemat 1.13 z elementem containsAedData)."""
    return Response(content=_dane_gov_pl_xml_bytes(), media_type="application/xml")


@app.api_route("/api/v1/export/dane-gov-pl.md5", methods=["GET", "HEAD"])
@app.api_route("/api/v1/export/dane-gov-pl.xml.md5", methods=["GET", "HEAD"])
def export_dane_gov_pl_xml_md5():
    """Suma kontrolna MD5 pliku XML – portal pobiera ją razem z plikiem."""
    return Response(content=hashlib.md5(_dane_gov_pl_xml_bytes()).hexdigest(), media_type="text/plain")


@app.get("/api/v1/stats")
async def api_stats():
    """Quality statistics for the dataset."""
    db = get_db()
    aeds = _all_aeds(db)
    total = len(aeds)
    active = sum(1 for a in aeds if a.get("status") == "active")
    h24 = sum(1 for a in aeds if a.get("opening_hours", "").strip() == "24/7")
    avg_q = sum(a.get("quality_score", 0) for a in aeds) / max(total, 1)
    dedup = db.execute("SELECT COUNT(*) FROM dedup_log").fetchone()[0]

    sources: dict[str, int] = {}
    for a in aeds:
        for s in a.get("source_name", "").split("+"):
            s = s.strip()
            if s:
                sources[s] = sources.get(s, 0) + 1

    return StatsResponse(
        total_aed=total,
        active_aed=active,
        pct_24_7=round(h24 / max(total, 1) * 100, 1),
        avg_quality_score=round(avg_q, 1),
        duplicates_removed=dedup,
        sources=sources,
    )


# ═══════════════════════════════════════════════════════════════════════
# API: TWO-TIER VERIFICATION & CERTIFICATE
# ═══════════════════════════════════════════════════════════════════════

@app.post("/api/v1/aeds/{aed_id}/verify")
async def api_verify_aed(aed_id: str, req: VerificationRequest):
    """Register citizen or professional verification for an AED."""
    db = get_db()
    row = db.execute("SELECT * FROM aed WHERE aed_id = ?", (aed_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="AED nie został znaleziony")

    aed = _row_dict(row)
    now_iso = now_pl().isoformat()

    db.execute(
        """INSERT INTO aed_verification 
           (aed_id, verifier_type, verifier_name, verifier_badge, cabinet_present,
            led_blinking, accessible, pads_expiry, battery_expiry, rko_kit_complete, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            aed_id, req.verifier_type, req.verifier_name or "", req.verifier_badge or "",
            1 if req.cabinet_present else 0,
            1 if req.led_blinking else 0,
            1 if req.accessible else 0,
            req.pads_expiry or "",
            req.battery_expiry or "",
            1 if req.rko_kit_complete else 0,
            req.notes or "",
            now_iso,
        ),
    )

    current_score = aed.get("quality_score", 0) or 0
    new_count = (aed.get("verification_count") or 0) + 1

    if req.verifier_type == "professional":
        cert_by = (req.verifier_badge or "").strip() or (req.verifier_name or "").strip() or "Ratownik Medyczny (PRM)"
        db.execute(
            """UPDATE aed 
               SET certified = 1, certified_at = ?, certified_by = ?,
                   last_verified_at = ?, quality_score = 100, verification_count = ?
               WHERE aed_id = ?""",
            (now_iso, cert_by, now_iso, new_count, aed_id),
        )
        db.commit()
        return {
            "ok": True,
            "verifier_type": "professional",
            "certified": True,
            "certified_by": cert_by,
            "certified_at": now_iso,
            "quality_score": 100,
            "verification_count": new_count,
            "certificate_url": f"/certificate/{aed_id}",
            "message": "Autoryzowany audyt ratowniczy zakończony sukcesem. Przyznano Certyfikat Bezpiecznego Obiektu AED (100/100 pkt jakości)!"
        }
    else:
        if req.cabinet_present and req.led_blinking and req.accessible:
            new_score = min(85, max(current_score, current_score + 10))
            db.execute(
                """UPDATE aed 
                   SET last_verified_at = ?, quality_score = ?, verification_count = ?
                   WHERE aed_id = ?""",
                (now_iso, new_score, new_count, aed_id),
            )
            db.commit()
            return {
                "ok": True,
                "verifier_type": "citizen",
                "certified": bool(aed.get("certified")),
                "quality_score": new_score,
                "verification_count": new_count,
                "message": f"Dziękujemy! Obywatelskie potwierdzenie obecności i sprawności zostało zarejestrowane (Jakość: {new_score}/100 pkt)."
            }
        else:
            new_score = max(20, current_score - 15)
            db.execute(
                """UPDATE aed 
                   SET last_verified_at = ?, quality_score = ?, verification_count = ?
                   WHERE aed_id = ?""",
                (now_iso, new_score, new_count, aed_id),
            )
            db.commit()
            return {
                "ok": True,
                "verifier_type": "citizen",
                "warning": True,
                "quality_score": new_score,
                "verification_count": new_count,
                "message": "Zgłoszenie nieprawidłowości (brak szafki lub problem z dostępem) zostało zarejestrowane i przekazane do weryfikacji."
            }


@app.get("/certificate/{aed_id}", response_class=HTMLResponse)
async def view_certificate(request: Request, aed_id: str):
    """View & print the official Certificate of Safe AED Facility."""
    db = get_db()
    row = db.execute("SELECT * FROM aed WHERE aed_id = ?", (aed_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="AED nie został znaleziony")
    aed = _row_dict(row)

    verif = db.execute(
        "SELECT * FROM aed_verification WHERE aed_id = ? AND verifier_type = 'professional' ORDER BY id DESC LIMIT 1",
        (aed_id,)
    ).fetchone()
    verif_dict = _row_dict(verif) if verif else {}

    return templates.TemplateResponse("certificate.html", {
        "request": request,
        "aed": aed,
        "verif": verif_dict,
        "base_url": str(request.base_url).rstrip("/"),
    })


REGIONS_PATH = str(BASE_DIR.parent / "data" / "wojewodztwa.geojson")
REGIONS_CACHE_TTL = timedelta(minutes=10)
_regions_cache: tuple[datetime, list[RegionStat]] | None = None


def _invalidate_regions_cache() -> None:
    """Po każdym imporcie ranking i wykaz AED mają od razu uwzględnić nowe AED."""
    global _regions_cache, _wykaz_cache
    _regions_cache = None
    _wykaz_cache = None


@app.get("/api/v1/stats/regions", response_model=list[RegionStat])
def api_stats_regions():
    """Ranking województw wg kompletności danych (opis lokalizacji + poprawne godziny
    + kontakt do opiekuna).

    Zwykłe ``def`` – FastAPI uruchamia je w puli wątków, więc liczenie (~0,7 s)
    nie blokuje pozostałych żądań, w tym ścieżki dyspozytora 112.
    """
    global _regions_cache
    now = datetime.now()
    if _regions_cache and now - _regions_cache[0] < REGIONS_CACHE_TTL:
        return _regions_cache[1]
    try:
        regions = load_voivodeships(REGIONS_PATH)
    except (OSError, ValueError, KeyError) as e:
        logger.warning(f"Granice województw niedostępne: {e}")
        return JSONResponse({"error": "Ranking województw chwilowo niedostępny"}, status_code=503)
    stats = region_stats(get_db(), regions)
    _regions_cache = (now, stats)
    return stats


# ═══════════════════════════════════════════════════════════════════════
# API: DISPATCHER 112
# ═══════════════════════════════════════════════════════════════════════

WALK_SPEED_MS = 1.4  # m/s average walking speed
UNKNOWN_HOURS_PENALTY = 1.5


# Presety scenariuszy demonstracyjnych (współrzędne dobrane na pełnych danych OSM:
# „biuro” – wieczorem w 400 m tylko zamknięte AED, „obrzeża” – brak AED w 800 m).
DISPATCH_PRESETS = [
    {"id": "centrum", "label": "Centrum – AED dostępne 24/7",
     "lat": 53.1235, "lon": 18.0000, "timestamp": None},
    {"id": "biuro", "label": "Biuro wieczorem – AED zamknięte",
     "lat": 53.1225, "lon": 18.0550, "timestamp": "2026-11-25T20:30:00"},
    {"id": "obrzeza", "label": "Obrzeża – brak AED w zasięgu",
     "lat": 53.1025, "lon": 17.9500, "timestamp": "2026-11-25T20:30:00"},
]
RADIUS_MIN_M, RADIUS_MAX_M, RADIUS_DEFAULT_M = 200, 800, 400


@app.get("/api/v1/dispatcher/presets")
async def dispatcher_presets():
    return DISPATCH_PRESETS


def _parse_sim_time(timestamp: Optional[str]) -> datetime:
    if not timestamp:
        return now_pl()
    try:
        return datetime.fromisoformat(timestamp).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=400, detail="Nieprawidłowy format timestamp (ISO-8601)")


@app.get("/api/v1/dispatcher/scan", response_model=ScanResult)
def dispatcher_scan(
    lat: float = Query(..., ge=49.0, le=54.9),
    lon: float = Query(..., ge=14.1, le=24.2),
    radius_m: int = Query(RADIUS_DEFAULT_M, ge=RADIUS_MIN_M, le=RADIUS_MAX_M),
    timestamp: Optional[str] = Query(None, description="ISO-8601, czas symulacji"),
):
    """AED w promieniu od zgłaszającego – bez tworzenia sesji ratunkowej.

    Kody do szafek nie są zwracane (endpoint jest publiczny) – kod trafia
    dopiero w odpowiedzi na utworzenie sesji i na ekran świadka.
    """
    result = scan_radius(get_db(), lat, lon, radius_m, _parse_sim_time(timestamp))
    for a in result.in_radius:
        a.access_code = None
    return result


def public_base_url(request: Request) -> tuple[str, Optional[str]]:
    """Adres, pod którym telefon świadka otworzy link z SMS/QR, + ostrzeżenie."""
    base = (os.environ.get("PULSEMAP_PUBLIC_URL") or str(request.base_url)).rstrip("/")
    host = (urlparse(base).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1", "testserver"):
        return base, (
            "Link wskazuje na ten komputer (localhost) – telefon go nie otworzy. "
            "Ustaw PULSEMAP_PUBLIC_URL, np. http://192.168.1.20:8000, i uruchom serwer z --host 0.0.0.0."
        )
    return base, None


def _sms_text(scenario: str, aed, rescue_url: str) -> str:
    if scenario == "CPR_ONLY" or aed is None:
        return (
            "112: Brak dostępnego AED w pobliżu. Nie opuszczaj poszkodowanego – "
            f"rozpocznij RKO. Instrukcja i rytm uciśnięć: {rescue_url}"
        )
    walk_min = max(1, round(aed.walk_time_s / 60))
    where = ", ".join(x for x in (aed.address_street, aed.location_description) if x)
    sms = f"112: AED {aed.distance_m:.0f} m (ok. {walk_min} min): {where}. "
    if aed.access_code:
        sms += f"Kod do szafki: {aed.access_code}. "
    return sms + f"Trasa: {rescue_url}"


SESSION_RATE_LIMIT = 30  # sesji na minutę z jednego adresu
_session_hits: dict[str, list[float]] = {}


def _check_session_rate(host: str) -> None:
    now = time.monotonic()
    hits = [t for t in _session_hits.get(host, []) if now - t < 60]
    if len(hits) >= SESSION_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Zbyt wiele sesji – spróbuj za chwilę")
    hits.append(now)
    _session_hits[host] = hits


@app.post("/api/v1/dispatcher/session", response_model=SessionCreated)
def dispatcher_create_session(req: DispatcherSessionRequest, request: Request):
    """Tworzy sesję ratunkową. Serwer sam liczy AED w promieniu i wybiera scenariusz."""
    _check_session_rate(request.client.host if request.client else "?")
    db = get_db()
    sim_dt = _parse_sim_time(req.timestamp)
    scan = scan_radius(db, req.lat, req.lon, req.radius_m, sim_dt)
    aed1 = scan.candidates[0] if scan.candidates else None
    aed2 = scan.candidates[1] if len(scan.candidates) > 1 else None

    token = secrets.token_urlsafe(8)
    call_ref = f"CPR-{now_pl().strftime('%m%d')}-{secrets.token_hex(2).upper()}"
    db.execute(
        """INSERT INTO rescue_session
           (token, aed_id_1, aed_id_2, caller_lat, caller_lon, call_ref, status,
            scenario, radius_m, caller_phone, dispatch_channel, sim_ts)
           VALUES (?, ?, ?, ?, ?, ?, 'dispatched', ?, ?, ?, ?, ?)""",
        (token, aed1.aed_id if aed1 else "", aed2.aed_id if aed2 else None, req.lat, req.lon,
         call_ref, scan.scenario, req.radius_m, req.caller_phone, req.dispatch_channel,
         req.timestamp or None),
    )
    db.commit()

    base, warning = public_base_url(request)
    rescue_url = f"{base}/go/{token}"
    return SessionCreated(
        token=token,
        scenario=scan.scenario,
        rescue_url=rescue_url,
        sms_text=_sms_text(scan.scenario, aed1, rescue_url),
        call_ref=call_ref,
        public_url_warning=warning,
        aed=aed1,
    )


@app.get("/api/v1/dispatcher/nearest")
async def dispatcher_nearest(
    request: Request,
    lat: float = Query(..., ge=49.0, le=54.9),
    lon: float = Query(..., ge=14.1, le=24.2),
    timestamp: Optional[str] = Query(None, description="ISO-8601 datetime for simulation"),
):
    """Find nearest open AEDs for dispatcher."""
    db = get_db()

    if timestamp:
        try:
            dt = datetime.fromisoformat(timestamp)
        except ValueError:
            return JSONResponse({"error": "Nieprawidłowy format timestamp (ISO-8601)"}, status_code=400)
    else:
        dt = now_pl()

    # Optimized spatial pre-filter: search within ~15km bounding box first
    dlat, dlon = 0.15, 0.25
    rows = db.execute(
        "SELECT * FROM aed WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?",
        (lat - dlat, lat + dlat, lon - dlon, lon + dlon)
    ).fetchall()
    if len(rows) < 5:
        # Fallback to wider search (~50km)
        dlat, dlon = 0.5, 0.8
        rows = db.execute(
            "SELECT * FROM aed WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?",
            (lat - dlat, lat + dlat, lon - dlon, lon + dlon)
        ).fetchall()
    if not rows:
        rows = db.execute("SELECT * FROM aed").fetchall()

    aeds = [_row_dict(r) for r in rows]
    candidates = []
    rejected = []

    for a in aeds:
        dist = haversine_m(lat, lon, a["latitude"], a["longitude"])

        # Only active devices
        if a.get("status") != "active":
            rejected.append(RejectedAED(
                aed_id=a["aed_id"], latitude=a["latitude"], longitude=a["longitude"],
                distance_m=round(dist, 1), address_street=a.get("address_street", ""),
                location_description=a.get("location_description", ""),
                reason=f"Status: {a.get('status', 'unknown')}",
            ))
            continue

        # Check opening hours
        state, reason = availability(a.get("opening_hours") or "24/7", dt)
        if state == Availability.closed:
            rejected.append(RejectedAED(
                aed_id=a["aed_id"], latitude=a["latitude"], longitude=a["longitude"],
                distance_m=round(dist, 1), address_street=a.get("address_street", ""),
                location_description=a.get("location_description", ""),
                reason=reason,
            ))
            continue

        # Nierozpoznane godziny: nie ukrywamy AED, ale traktujemy je jak o 50% dalsze,
        # żeby potwierdzone otwarte urządzenie w podobnej odległości miało pierwszeństwo.
        a["_availability_note"] = reason if state == Availability.unknown else ""
        rank = dist * (UNKNOWN_HOURS_PENALTY if state == Availability.unknown else 1.0)
        candidates.append((rank, dist, a))

    # Sort by (penalised) distance
    candidates.sort(key=lambda x: x[0])
    rejected.sort(key=lambda x: x.distance_m)

    # Take top 2
    nearest_list = []
    for _rank, dist, a in candidates[:2]:
        walk_time = dist / WALK_SPEED_MS
        gmaps = f"https://www.google.com/maps/dir/?api=1&destination={a['latitude']},{a['longitude']}&travelmode=walking"
        nearest_list.append(NearestAED(
            aed_id=a["aed_id"],
            latitude=a["latitude"],
            longitude=a["longitude"],
            distance_m=round(dist, 1),
            walk_time_s=round(walk_time, 0),
            address_city=a.get("address_city", ""),
            address_street=a.get("address_street", ""),
            location_description=a.get("location_description", ""),
            access_code=a.get("access_code"),
            opening_hours=a.get("opening_hours", ""),
            operator_phone=a.get("operator_phone", ""),
            google_maps_url=gmaps,
            hours_confirmed=not a["_availability_note"],
            availability_note=a["_availability_note"],
        ))

    # Create rescue session
    token = secrets.token_urlsafe(8)
    call_ref = f"CPR-{datetime.now().strftime('%m%d')}-{secrets.token_hex(2).upper()}"
    aed_id_1 = nearest_list[0].aed_id if len(nearest_list) > 0 else ""
    aed_id_2 = nearest_list[1].aed_id if len(nearest_list) > 1 else None

    if aed_id_1:
        db.execute(
            """INSERT INTO rescue_session 
               (token, aed_id_1, aed_id_2, caller_lat, caller_lon, call_ref, status) 
               VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
            (token, aed_id_1, aed_id_2, lat, lon, call_ref),
        )
        db.commit()

    base_url = str(request.base_url).rstrip("/")
    rescue_url = f"{base_url}/go/{token}"

    # SMS text
    if nearest_list:
        n = nearest_list[0]
        walk_min = max(1, int(n.walk_time_s / 60))
        sms = (
            f"⚡ AED {n.distance_m:.0f}m ({walk_min} min pieszo): "
            f"{n.address_street}, {n.location_description}. "
        )
        if n.access_code:
            sms += f"Kod: {n.access_code}. "
        sms += f"Nawiguj: {rescue_url}"
    else:
        sms = "Brak dostępnych AED w pobliżu."

    return DispatcherResponse(
        nearest=nearest_list,
        rejected_closed=rejected[:5],
        rescue_token=token,
        rescue_url=rescue_url,
        sms_text=sms,
        call_ref=call_ref,
    )


@app.post("/api/v1/dispatcher/send-route")
async def dispatcher_send_route(req: DispatcherSendRouteRequest):
    """Dispatcher commands active route push to the caller's phone."""
    db = get_db()
    session = db.execute("SELECT * FROM rescue_session WHERE token = ?", (req.token,)).fetchone()
    if not session:
        return JSONResponse({"error": "Sesja ratunkowa nie znaleziona"}, status_code=404)

    s_dict = _row_dict(session)
    active_slot = s_dict.get("active_slot", 1)
    aed_id = s_dict["aed_id_1"] if active_slot == 1 else s_dict.get("aed_id_2")

    aed_row = db.execute("SELECT * FROM aed WHERE aed_id = ?", (aed_id,)).fetchone()
    aed = _row_dict(aed_row) if aed_row else {}

    now_iso = datetime.now().isoformat()
    db.execute(
        """UPDATE rescue_session 
           SET caller_phone = ?, dispatch_channel = ?, status = 'dispatched', updated_at = ?,
               call_ref = CASE WHEN ? != '' THEN ? ELSE call_ref END
           WHERE token = ?""",
        (req.caller_phone, req.dispatch_channel, now_iso, req.call_ref, req.call_ref, req.token)
    )
    db.commit()

    dist_m = round(haversine_m(s_dict["caller_lat"], s_dict["caller_lon"], aed.get("latitude", 0), aed.get("longitude", 0)))
    walk_min = max(1, round(dist_m / WALK_SPEED_MS / 60))
    code_txt = f"Kod do szafki: {aed.get('access_code')}." if aed.get('access_code') else "Szafka nie wymaga kodu (pociągnij za uchwyt)."

    channel_names = {
        "mobywatel": "Powiadomienie PUSH (Otwórz AED, priorytet 112)",
        "sms": "SMS Ratunkowy (Link Zero-Install)",
        "qr": "Kod QR na pulpicie CPR / dla patrolu",
    }

    script = (
        f"„Wysłałem na Pana/Pani telefon trasę do defibrylatora ({channel_names.get(req.dispatch_channel, req.dispatch_channel)}). "
        f"Urządzenie znajduje się {dist_m} metrów stąd, około {walk_min} minuty biegu. "
        f"Adres: {aed.get('address_street', 'Wskazany na mapie')}. "
        f"Lokalizacja w obiekcie: {aed.get('location_description', 'Parter')}. "
        f"{code_txt} "
        f"Proszę biec prosto do celu, trzymam Pana na linii, mam podgląd w systemie. "
        f"Po wyjęciu AED proszę wcisnąć w aplikacji zielony przycisk POBRAŁEM AED.”"
    )

    return {
        "ok": True,
        "token": req.token,
        "status": "dispatched",
        "caller_phone": req.caller_phone,
        "dispatch_channel": req.dispatch_channel,
        "channel_label": channel_names.get(req.dispatch_channel, req.dispatch_channel),
        "guidance_script": script,
        "target_aed": {
            "address": aed.get("address_street"),
            "location_description": aed.get("location_description"),
            "access_code": aed.get("access_code"),
            "distance_m": dist_m,
            "walk_min": walk_min,
        }
    }


@app.get("/api/v1/rescue/{token}/status")
async def rescue_status(token: str):
    """Real-time telemetry poll for dispatcher console."""
    db = get_db()
    session = db.execute("SELECT * FROM rescue_session WHERE token = ?", (token,)).fetchone()
    if not session:
        return JSONResponse({"error": "Sesja nie znaleziona"}, status_code=404)

    s_dict = _row_dict(session)
    active_slot = s_dict.get("active_slot", 1)
    aed_id = s_dict["aed_id_1"] if active_slot == 1 else s_dict.get("aed_id_2")

    aed_row = db.execute("SELECT * FROM aed WHERE aed_id = ?", (aed_id,)).fetchone() if aed_id else None
    aed = _row_dict(aed_row) if aed_row else {}

    return {
        "token": token,
        "status": s_dict.get("status", "pending"),
        "scenario": s_dict.get("scenario") or "AED_FOUND",
        "unavailable_reports": db.execute(
            "SELECT COUNT(*) FROM aed_report WHERE token = ?", (token,)
        ).fetchone()[0],
        "active_slot": active_slot,
        "caller_phone": s_dict.get("caller_phone", ""),
        "dispatch_channel": s_dict.get("dispatch_channel", "mobywatel"),
        "call_ref": s_dict.get("call_ref", ""),
        "updated_at": s_dict.get("updated_at", ""),
        "caller_lat": s_dict.get("caller_lat"),
        "caller_lon": s_dict.get("caller_lon"),
        "aed": {
            "aed_id": aed.get("aed_id"),
            "address_street": aed.get("address_street"),
            "location_description": aed.get("location_description"),
            "latitude": aed.get("latitude"),
            "longitude": aed.get("longitude"),
            "access_code": aed.get("access_code"),
        } if aed else None
    }


def _report_unavailable(db, token: str, session: dict) -> dict:
    """Świadek zgłasza, że AED jest zamknięte/nie ma go na miejscu.

    Oznacza bieżące AED jako ``temporarily_unavailable`` i przełącza na drugie
    AED z promienia; gdy go nie ma – sesja przechodzi na ``CPR_ONLY`` (RKO).
    Wielokrotne zgłoszenie po przejściu na RKO niczego już nie zmienia.
    """
    now_iso = datetime.now().isoformat()
    if session.get("scenario") == "CPR_ONLY":
        return {"switched": False, "scenario": "CPR_ONLY", "status": session.get("status"),
                "message": "Instrukcja RKO"}

    active_slot = session.get("active_slot", 1)
    current_aed_id = session["aed_id_1"] if active_slot == 1 else session.get("aed_id_2")
    if current_aed_id:
        # Zgłoszenie zapisujemy osobno – nie zmieniamy aed.status (patrz aed_report)
        db.execute("INSERT INTO aed_report (aed_id, token) VALUES (?, ?)", (current_aed_id, token))
    if active_slot == 1 and session.get("aed_id_2"):
        db.execute(
            "UPDATE rescue_session SET active_slot = 2, status = 'unavailable_reported', updated_at = ? WHERE token = ?",
            (now_iso, token),
        )
        db.commit()
        return {"switched": True, "scenario": "AED_FOUND", "status": "unavailable_reported",
                "redirect": f"/go/{token}", "message": "Przepięto na AED rezerwowe #2"}

    db.execute(
        "UPDATE rescue_session SET scenario = 'CPR_ONLY', status = 'unavailable_reported', updated_at = ? WHERE token = ?",
        (now_iso, token),
    )
    db.commit()
    return {"switched": False, "scenario": "CPR_ONLY", "status": "unavailable_reported",
            "message": "Brak innego AED w promieniu – instrukcja RKO"}


@app.post("/api/v1/rescue/{token}/event")
async def rescue_event(token: str, req: RescueEventRequest):
    """Witness reports progress event (opened, en_route, acquired, unavailable)."""
    db = get_db()
    session = db.execute("SELECT * FROM rescue_session WHERE token = ?", (token,)).fetchone()
    if not session:
        return JSONResponse({"error": "Sesja nie znaleziona"}, status_code=404)

    if _session_expired(_row_dict(session)):
        return JSONResponse({"error": "Sesja ratunkowa wygasła"}, status_code=410)

    now_iso = datetime.now().isoformat()
    ev = req.event

    if ev == "unavailable":
        return _report_unavailable(db, token, _row_dict(session))

    new_status = ev
    db.execute("UPDATE rescue_session SET status = ?, updated_at = ? WHERE token = ?", (new_status, now_iso, token))
    db.commit()
    return {"ok": True, "status": new_status}


# ═══════════════════════════════════════════════════════════════════════
# WITNESS VIEW /go/{token}
# ═══════════════════════════════════════════════════════════════════════

@app.get("/go/{token}", response_class=HTMLResponse)
async def witness_go(request: Request, token: str):
    db = get_db()
    session = db.execute("SELECT * FROM rescue_session WHERE token = ?", (token,)).fetchone()
    if not session:
        return templates.TemplateResponse("witness_go.html", {
            "request": request, "error": True, "aed": None, "aed2": None, "token": token,
            "caller_lat": 0, "caller_lon": 0, "session": {}, "scenario": "CPR_ONLY",
        })

    session_dict = _row_dict(session)
    if _session_expired(session_dict):
        return templates.TemplateResponse("witness_go.html", {
            "request": request, "error": True, "aed": None, "aed2": None, "token": token,
            "caller_lat": 0, "caller_lon": 0, "session": {}, "scenario": "CPR_ONLY",
        })
    active_slot = session_dict.get("active_slot", 1)
    aed_id = session_dict["aed_id_1"] if active_slot == 1 else session_dict.get("aed_id_2")

    # If opened by witness, register status as 'opened' if was pending/dispatched
    cur_status = session_dict.get("status", "pending")
    if cur_status in ("pending", "dispatched"):
        db.execute("UPDATE rescue_session SET status = 'opened', updated_at = ? WHERE token = ?", (datetime.now().isoformat(), token))
        db.commit()
        session_dict["status"] = "opened"

    aed = None
    if aed_id:
        row = db.execute("SELECT * FROM aed WHERE aed_id = ?", (aed_id,)).fetchone()
        if row:
            aed = _row_dict(row)
            dist = haversine_m(session_dict["caller_lat"], session_dict["caller_lon"],
                               aed["latitude"], aed["longitude"])
            aed["distance_m"] = round(dist, 1)
            aed["walk_time_min"] = max(1, round(dist / WALK_SPEED_MS / 60, 1))
            # Stan godzin w chwili, dla której dyspozytor symulował zdarzenie
            sim_dt = now_pl()
            if session_dict.get("sim_ts"):
                try:
                    sim_dt = datetime.fromisoformat(session_dict["sim_ts"]).replace(tzinfo=None)
                except ValueError:
                    pass
            aed["hours_status"] = availability(aed.get("opening_hours") or "24/7", sim_dt)[0].value
            aed["google_maps_url"] = (
                f"https://www.google.com/maps/dir/?api=1"
                f"&destination={aed['latitude']},{aed['longitude']}&travelmode=walking"
            )

    # Second AED info
    aed2 = None
    aed_id_2 = session_dict.get("aed_id_2")
    if aed_id_2 and active_slot == 1:
        row2 = db.execute("SELECT * FROM aed WHERE aed_id = ?", (aed_id_2,)).fetchone()
        if row2:
            aed2 = _row_dict(row2)

    return templates.TemplateResponse("witness_go.html", {
        "request": request,
        "error": False,
        "aed": aed,
        "aed2": aed2,
        "token": token,
        "caller_lat": session_dict["caller_lat"],
        "caller_lon": session_dict["caller_lon"],
        "active_slot": active_slot,
        "session": session_dict,
        # AED usunięte z bazy w trakcie akcji → świadek dostaje instrukcję RKO, nie „sesja wygasła”
        "scenario": "CPR_ONLY" if aed is None else (session_dict.get("scenario") or "AED_FOUND"),
    })


@app.post("/go/{token}/report-unavailable")
async def report_unavailable(token: str):
    """Mark current AED as temporarily_unavailable and switch to backup."""
    db = get_db()
    session = db.execute("SELECT * FROM rescue_session WHERE token = ?", (token,)).fetchone()
    if not session:
        return JSONResponse({"error": "Sesja nie znaleziona"}, status_code=404)

    session_dict = _row_dict(session)
    if _session_expired(session_dict):
        return JSONResponse({"error": "Sesja ratunkowa wygasła"}, status_code=410)
    return JSONResponse(_report_unavailable(db, token, session_dict))


# ═══════════════════════════════════════════════════════════════════════
# API: INGEST (upload CSV/JSON)
# ═══════════════════════════════════════════════════════════════════════

@app.post("/api/v1/ingest/json", dependencies=[Depends(require_api_key)])
async def ingest_json(request: Request):
    """Ingest AED records from JSON body."""
    body = await request.json()
    records = body if isinstance(body, list) else [body]
    db = get_db()
    report = ingest_records(db, records)
    _invalidate_regions_cache()
    return report


@app.post("/api/v1/ingest/upload", dependencies=[Depends(require_api_key)])
async def ingest_upload(file: UploadFile = File(...)):
    """Ingest AED records from uploaded CSV or JSON file."""
    content = await file.read()
    text = content.decode("utf-8-sig")  # Handle BOM
    records = []

    fname = (file.filename or "").lower()
    if fname.endswith(".json"):
        try:
            data = json.loads(text)
            records = data if isinstance(data, list) else [data]
        except json.JSONDecodeError as e:
            return JSONResponse({"error": f"Błąd parsowania JSON: {e}"}, status_code=400)
    elif fname.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            # Type conversions
            for fld in ("latitude", "longitude"):
                if fld in row and row[fld]:
                    try:
                        row[fld] = float(row[fld])
                    except ValueError:
                        pass
            if "indoor" in row:
                row["indoor"] = row["indoor"].lower() in ("true", "1", "yes", "tak")
            if "quality_score" in row and row["quality_score"]:
                try:
                    row["quality_score"] = int(row["quality_score"])
                except ValueError:
                    row["quality_score"] = None
            records.append(row)
    else:
        return JSONResponse(
            {"error": "Nieobsługiwany format. Dozwolone: .csv, .json"}, status_code=400
        )

    db = get_db()
    report = ingest_records(db, records)
    _invalidate_regions_cache()
    return report


@app.post("/api/v1/ingest/single")
async def ingest_single(
    request: Request,
    source_name: str = Form("Zgloszenie_Dysponenta"),
    latitude: float = Form(...),
    longitude: float = Form(...),
    address_city: str = Form(""),
    address_street: str = Form(""),
    address_postal_code: str = Form(""),
    location_description: str = Form(""),
    indoor: bool = Form(False),
    access_type: str = Form("public"),
    access_code: str = Form(""),
    opening_hours: str = Form("24/7"),
    operator_name: str = Form(""),
    operator_phone: str = Form(""),
    operator_email: str = Form(""),
):
    """Ingest a single AED from form submission."""
    record = {
        "source_name": source_name,
        "latitude": latitude,
        "longitude": longitude,
        "address_city": address_city,
        "address_street": address_street,
        "address_postal_code": address_postal_code,
        "location_description": location_description,
        "indoor": indoor,
        "access_type": access_type,
        "access_code": access_code if access_code else None,
        "opening_hours": opening_hours,
        "status": "unverified",
        "operator_name": operator_name,
        "operator_phone": operator_phone,
        "operator_email": operator_email,
    }
    db = get_db()
    report = ingest_records(db, [record])
    _invalidate_regions_cache()
    return RedirectResponse(url="/submit?success=1", status_code=303)


# ═══════════════════════════════════════════════════════════════════════
# API: OSM LIVE FETCH
# ═══════════════════════════════════════════════════════════════════════

@app.post("/api/v1/ingest/osm", dependencies=[Depends(require_api_key)])
async def ingest_osm():
    """Fetch AEDs from Overpass API and ingest.

    Gdy pobrano pełny zrzut (wszystkie zapytania udane), urządzenia, które
    zniknęły z OSM, dostają status ``unverified``.
    """
    osm_records, complete = await fetch_osm_aeds_snapshot()
    if not osm_records:
        return JSONResponse({"message": "Brak danych z OSM (offline?)", "records": 0})
    db = get_db()
    report = ingest_records(db, osm_records, sync_source="OSM" if complete else None)
    _invalidate_regions_cache()
    return report


@app.post("/api/v1/ingest/dane-gov-pl", dependencies=[Depends(require_api_key)])
def ingest_dane_gov_pl():
    """Pobiera ogólnopolski wykaz zbiorczy AED z portalu dane.gov.pl do bazy dyspozytora."""
    try:
        report = sync_from_portal(get_db())
    except (httpx.HTTPError, LookupError) as exc:
        raise HTTPException(status_code=502, detail=f"Nie udało się pobrać wykazu z dane.gov.pl: {exc}")
    _invalidate_regions_cache()
    return report


# ═══════════════════════════════════════════════════════════════════════
# HTML VIEWS (React Unified CAD Application)
# ═══════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
@app.get("/mapa", response_class=HTMLResponse)
@app.get("/dispatcher", response_class=HTMLResponse)
@app.get("/submit", response_class=HTMLResponse)
@app.get("/opendata", response_class=HTMLResponse)
async def page_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
