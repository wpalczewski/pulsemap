"""Pulsmap – skan AED w promieniu od zgłaszającego (logika dyspozytora 112).

Czysta logika bez FastAPI: dla punktu, promienia i chwili symulacji zwraca
wszystkie AED w okręgu z ich stanem, do 2 kandydatów do wysłania świadka
oraz proponowany scenariusz (AED_FOUND / CPR_ONLY).
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from app.etl import haversine_m
from app.models import AedState, ScannedAED
from app.opening_hours import Availability, availability

WALK_SPEED_MS = 1.4  # m/s – szybki marsz
OUTSIDE_SEARCH_M = 5000  # jak daleko szukamy „najbliższego otwartego poza promieniem”
REPORT_WINDOW = "-2 hours"  # jak długo zgłoszenie świadka obniża priorytet AED

Scenario = Literal["AED_FOUND", "CPR_ONLY"]


class ScanResult(BaseModel):
    in_radius: list[ScannedAED]
    candidates: list[ScannedAED]
    nearest_open_outside_m: Optional[float]
    scenario: Scenario


def _bbox(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    dlat = radius_m / 111_320
    dlon = radius_m / (111_320 * math.cos(math.radians(lat)))
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon


def _state(row: dict, dt: datetime) -> tuple[AedState, str]:
    if row.get("status") != "active":
        return "unavailable", f"Urządzenie niedostępne (status: {row.get('status')})"
    st, reason = availability(row.get("opening_hours") or "24/7", dt)
    if st == Availability.closed:
        return "closed", reason
    if st == Availability.unknown:
        return "unknown", reason
    return "open", ""


def _scanned(row: dict, dist: float, state: AedState, reason: str) -> ScannedAED:
    walk = dist / WALK_SPEED_MS
    return ScannedAED(
        aed_id=row["aed_id"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        distance_m=round(dist, 1),
        walk_time_s=round(walk),
        round_trip_s=round(walk) * 2,
        state=state,
        reason=reason,
        address_street=row.get("address_street") or "",
        address_city=row.get("address_city") or "",
        location_description=row.get("location_description") or "",
        opening_hours=row.get("opening_hours") or "24/7",
        has_access_code=bool(row.get("access_code")),
        access_code=row.get("access_code") or None,
        google_maps_url=(
            "https://www.google.com/maps/dir/?api=1"
            f"&destination={row['latitude']},{row['longitude']}&travelmode=walking"
        ),
    )


def scan_radius(db: sqlite3.Connection, lat: float, lon: float, radius_m: int, dt: datetime) -> ScanResult:
    """AED w promieniu *radius_m* od (lat, lon) w chwili *dt*."""
    s, n, w, e = _bbox(lat, lon, OUTSIDE_SEARCH_M)
    rows = db.execute(
        "SELECT * FROM aed WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?",
        (s, n, w, e),
    ).fetchall()

    in_radius: list[ScannedAED] = []
    nearest_outside: Optional[float] = None
    for r in rows:
        row = dict(r)
        dist = haversine_m(lat, lon, row["latitude"], row["longitude"])
        if dist > OUTSIDE_SEARCH_M:
            continue
        state, reason = _state(row, dt)
        if dist <= radius_m:
            in_radius.append(_scanned(row, dist, state, reason))
        elif state == "open" and (nearest_outside is None or dist < nearest_outside):
            nearest_outside = dist

    in_radius.sort(key=lambda a: a.distance_m)
    if in_radius:
        ids = [a.aed_id for a in in_radius]
        reported = {r[0] for r in db.execute(
            f"SELECT DISTINCT aed_id FROM aed_report WHERE created_at >= datetime('now', ?) "
            f"AND aed_id IN ({','.join('?' * len(ids))})",
            [REPORT_WINDOW, *ids],
        )}
        for a in in_radius:
            a.reported_recently = a.aed_id in reported
    # Kolejność: otwarte → nieznane godziny → dopiero potem świeżo zgłoszone przez świadka
    usable = [a for a in in_radius if a.state in ("open", "unknown")]
    candidates = sorted(usable, key=lambda a: (a.reported_recently, a.state != "open", a.distance_m))[:2]
    return ScanResult(
        in_radius=in_radius,
        candidates=candidates,
        nearest_open_outside_m=round(nearest_outside, 1) if nearest_outside is not None else None,
        scenario="AED_FOUND" if candidates else "CPR_ONLY",
    )
