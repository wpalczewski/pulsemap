"""Pulsmap – Pydantic v2 models & SQLite schema for AED registry."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.opening_hours import to_osm


# ── Enums ──────────────────────────────────────────────────────────────
class AccessType(str, Enum):
    public = "public"
    customers = "customers"
    private = "private"
    permissive = "permissive"


class AEDStatus(str, Enum):
    active = "active"
    temporarily_unavailable = "temporarily_unavailable"
    damaged = "damaged"
    unverified = "unverified"


# ── Core AED Model ────────────────────────────────────────────────────
class AEDRecord(BaseModel):
    aed_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_name: str = Field(..., min_length=1, description="Źródło danych, np. OSM, UM_Bydgoszcz")
    source_id: str = Field(default="", description="ID w systemie źródłowym")
    latitude: float = Field(..., ge=49.0, le=54.9, description="Szerokość geogr. WGS84")
    longitude: float = Field(..., ge=14.1, le=24.2, description="Długość geogr. WGS84")
    address_city: str = Field(default="")
    address_street: str = Field(default="")
    address_postal_code: str = Field(default="")
    location_description: str = Field(default="", description="Dokładny opis lokalizacji")
    indoor: bool = Field(default=False)
    access_type: AccessType = Field(default=AccessType.public)
    access_code: Optional[str] = Field(default=None, description="Kod do szafki AED")
    opening_hours: str = Field(default="24/7", description="Godziny dostępności w formacie OSM")
    status: AEDStatus = Field(default=AEDStatus.active)
    operator_name: str = Field(default="")
    operator_phone: str = Field(default="")
    operator_email: str = Field(default="")
    last_verified_at: Optional[str] = Field(default=None, description="Data ostatniej weryfikacji ISO-8601")
    quality_score: int = Field(default=0, ge=0, le=100, description="Wynik jakości 0-100")
    certified: bool = Field(default=False, description="Certyfikat potwierdzony przez personel medyczny")
    certified_at: Optional[str] = Field(default=None, description="Data certyfikacji ISO-8601")
    certified_by: Optional[str] = Field(default=None, description="Identyfikator ratownika/jednostki")
    verification_count: int = Field(default=0, description="Liczba weryfikacji społecznych")

    @field_validator("latitude")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not 49.0 <= v <= 54.9:
            raise ValueError("Szerokość geograficzna poza granicami Polski (49.0–54.9)")
        return round(v, 6)

    @field_validator("longitude")
    @classmethod
    def validate_lon(cls, v: float) -> float:
        if not 14.1 <= v <= 24.2:
            raise ValueError("Długość geograficzna poza granicami Polski (14.1–24.2)")
        return round(v, 6)


class AEDRecordIngest(BaseModel):
    """Model for incoming records (aed_id is optional)."""
    aed_id: Optional[str] = None
    source_name: str = Field(..., min_length=1)
    source_id: str = Field(default="")
    latitude: float = Field(..., ge=49.0, le=54.9)
    longitude: float = Field(..., ge=14.1, le=24.2)
    address_city: str = Field(default="")
    address_street: str = Field(default="")
    address_postal_code: str = Field(default="")
    location_description: str = Field(default="")
    indoor: bool = Field(default=False)
    access_type: AccessType = Field(default=AccessType.public)
    access_code: Optional[str] = Field(default=None)
    opening_hours: str = Field(default="24/7")
    status: AEDStatus = Field(default=AEDStatus.active)
    operator_name: str = Field(default="")
    operator_phone: str = Field(default="")
    operator_email: str = Field(default="")
    last_verified_at: Optional[str] = Field(default=None)
    quality_score: Optional[int] = Field(default=None)

    @field_validator("opening_hours")
    @classmethod
    def opening_hours_to_osm(cls, v: str) -> str:
        """Formularz przyjmuje „Pn-Pt 08:00-18:00”; w bazie i otwartych danych zapis OSM."""
        return to_osm((v or "").strip()) or "24/7"


# ── Dispatcher response models ────────────────────────────────────────
class NearestAED(BaseModel):
    aed_id: str
    latitude: float
    longitude: float
    distance_m: float
    walk_time_s: float
    address_city: str
    address_street: str
    location_description: str
    access_code: Optional[str]
    opening_hours: str
    operator_phone: str
    google_maps_url: str
    hours_confirmed: bool = True
    availability_note: str = ""


class RejectedAED(BaseModel):
    aed_id: str
    latitude: float
    longitude: float
    distance_m: float
    address_street: str
    location_description: str
    reason: str


class DispatcherResponse(BaseModel):
    nearest: list[NearestAED]
    rejected_closed: list[RejectedAED]
    rescue_token: str
    rescue_url: str
    sms_text: str
    call_ref: str = ""


class DispatcherSendRouteRequest(BaseModel):
    token: str
    caller_phone: str = Field(default="", description="Numer telefonu dzwoniącego, np. +48 601 234 567")
    dispatch_channel: str = Field(default="mobywatel", description="mobywatel | sms | qr")
    call_ref: str = Field(default="", description="Sygnatura zgłoszenia CPR")


AedState = Literal["open", "closed", "unavailable", "unknown"]


class ScannedAED(BaseModel):
    aed_id: str
    latitude: float
    longitude: float
    distance_m: float
    walk_time_s: float
    round_trip_s: float
    state: AedState
    reason: str
    address_street: str
    address_city: str
    location_description: str
    opening_hours: str
    has_access_code: bool
    access_code: Optional[str]
    google_maps_url: str
    reported_recently: bool = False


class DispatcherSessionRequest(BaseModel):
    lat: float = Field(..., ge=49.0, le=54.9)
    lon: float = Field(..., ge=14.1, le=24.2)
    radius_m: int = Field(400, ge=200, le=800)
    timestamp: Optional[str] = None
    caller_phone: str = ""
    dispatch_channel: str = "sms"


class SessionCreated(BaseModel):
    token: str
    scenario: Literal["AED_FOUND", "CPR_ONLY"]
    rescue_url: str
    sms_text: str
    call_ref: str
    public_url_warning: Optional[str]
    aed: Optional[ScannedAED]


class RescueEventRequest(BaseModel):
    event: Literal["opened", "en_route", "acquired", "unavailable"]


class VerificationRequest(BaseModel):
    verifier_type: Literal["citizen", "professional"] = "citizen"
    verifier_name: Optional[str] = ""
    verifier_badge: Optional[str] = ""
    cabinet_present: bool = True
    led_blinking: bool = True
    accessible: bool = True
    pads_expiry: Optional[str] = ""
    battery_expiry: Optional[str] = ""
    rko_kit_complete: bool = True
    notes: Optional[str] = ""


class RescueStatusResponse(BaseModel):
    token: str
    status: str
    active_slot: int
    caller_phone: str
    dispatch_channel: str
    call_ref: str
    aed_id: str
    caller_lat: float
    caller_lon: float
    updated_at: str


class IngestReport(BaseModel):
    total_submitted: int
    valid: int
    duplicates_merged: int
    inserted: int = 0
    updated: int = 0
    marked_missing: int = 0
    errors: list[str]


class StatsResponse(BaseModel):
    total_aed: int
    active_aed: int
    pct_24_7: float
    avg_quality_score: float
    duplicates_removed: int
    sources: dict[str, int]


# ── SQLite DDL ─────────────────────────────────────────────────────────
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS aed (
    aed_id          TEXT PRIMARY KEY,
    source_name     TEXT NOT NULL,
    source_id       TEXT DEFAULT '',
    latitude        REAL NOT NULL,
    longitude       REAL NOT NULL,
    address_city    TEXT DEFAULT '',
    address_street  TEXT DEFAULT '',
    address_postal_code TEXT DEFAULT '',
    location_description TEXT DEFAULT '',
    indoor          INTEGER DEFAULT 0,
    access_type     TEXT DEFAULT 'public',
    access_code     TEXT,
    opening_hours   TEXT DEFAULT '24/7',
    status          TEXT DEFAULT 'active',
    status_updated_at TEXT,
    operator_name   TEXT DEFAULT '',
    operator_phone  TEXT DEFAULT '',
    operator_email  TEXT DEFAULT '',
    last_verified_at TEXT,
    quality_score   INTEGER DEFAULT 0,
    certified       INTEGER DEFAULT 0,
    certified_at    TEXT DEFAULT '',
    certified_by    TEXT DEFAULT '',
    verification_count INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS aed_verification (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    aed_id          TEXT NOT NULL,
    verifier_type   TEXT NOT NULL,
    verifier_name   TEXT DEFAULT '',
    verifier_badge  TEXT DEFAULT '',
    cabinet_present INTEGER DEFAULT 1,
    led_blinking    INTEGER DEFAULT 1,
    accessible      INTEGER DEFAULT 1,
    pads_expiry     TEXT DEFAULT '',
    battery_expiry  TEXT DEFAULT '',
    rko_kit_complete INTEGER DEFAULT 1,
    notes           TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_aed_verif_aed ON aed_verification(aed_id);

CREATE TABLE IF NOT EXISTS rescue_session (
    token       TEXT PRIMARY KEY,
    aed_id_1    TEXT NOT NULL,
    aed_id_2    TEXT,
    caller_lat  REAL NOT NULL,
    caller_lon  REAL NOT NULL,
    created_at  TEXT DEFAULT (datetime('now')),
    active_slot INTEGER DEFAULT 1,
    caller_phone TEXT DEFAULT '',
    dispatch_channel TEXT DEFAULT 'mobywatel',
    status      TEXT DEFAULT 'pending',
    updated_at  TEXT DEFAULT (datetime('now')),
    call_ref    TEXT DEFAULT '',
    scenario    TEXT DEFAULT 'AED_FOUND',
    radius_m    INTEGER DEFAULT 400,
    sim_ts      TEXT
);

-- Zgłoszenia świadków „AED zamknięte / brak na miejscu”. Nie zmieniają
-- aed.status (anonimowe zgłoszenie nie może trwale wyłączyć urządzenia) –
-- skan tylko oznacza takie AED i obniża ich priorytet przez REPORT_WINDOW.
CREATE TABLE IF NOT EXISTS aed_report (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    aed_id      TEXT NOT NULL,
    token       TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_aed_report_aed ON aed_report(aed_id, created_at);

CREATE TABLE IF NOT EXISTS dedup_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kept_aed_id TEXT NOT NULL,
    merged_source TEXT NOT NULL,
    distance_m  REAL NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_aed_lat_lon ON aed(latitude, longitude);

-- Pochodzenie: które rekordy których źródeł opisują dane AED.
-- Pozwala aktualizować rekord przy ponownym imporcie i nie scalać dwóch
-- różnych urządzeń z tego samego źródła stojących obok siebie.
CREATE TABLE IF NOT EXISTS aed_source (
    source_name   TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    aed_id        TEXT NOT NULL,
    first_seen_at TEXT DEFAULT (datetime('now')),
    last_seen_at  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (source_name, source_id)
);

CREATE INDEX IF NOT EXISTS idx_aed_source_aed ON aed_source(aed_id);

"""

