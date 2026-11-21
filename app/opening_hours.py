"""Pulsmap – parser godzin dostępności w formacie OSM `opening_hours` (podzbiór).

Obsługiwane:
  * ``24/7``
  * reguły rozdzielone ``;`` – późniejsza reguła nadpisuje wcześniejszą dla dni,
    które wybiera (semantyka OSM), np. ``Mo-Fr 08:00-16:00; We 10:00-12:00``
  * wiele przedziałów w regule: ``Mo-Fr 08:00-12:00,13:00-16:00``
  * przedziały przez północ: ``Mo-Su 20:00-02:00`` oraz ``22:00-26:00``
  * modyfikatory ``off`` / ``closed`` / ``open`` / ``unknown``
  * święta państwowe w Polsce (``PH``), liczone łącznie z Wielkanocą

Wszystko, czego nie rozumiemy (miesiące, ``sunrise``, komentarze, ``SH``…), daje
stan ``unknown`` zamiast ``closed`` – dla dyspozytora lepiej pokazać AED z
ostrzeżeniem niż je ukryć.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from functools import lru_cache


class Availability(str, Enum):
    open = "open"
    closed = "closed"
    unknown = "unknown"


_DAY_MAP = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}
_DAY_NAMES_PL = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
_ALL_DAYS = frozenset(range(7))

_TIME = r"(\d{1,2}):(\d{2})"
_RANGE_RE = re.compile(rf"^{_TIME}\s*-\s*{_TIME}$")
_TIMES_SUFFIX_RE = re.compile(
    rf"(?:^|\s)({_TIME}\s*-\s*{_TIME}(?:\s*,\s*{_TIME}\s*-\s*{_TIME})*)$"
)
_MODIFIER_RE = re.compile(r"(?:^|\s)(off|closed|open|unknown)$", re.IGNORECASE)


class OpeningHoursError(ValueError):
    """Ciąg opening_hours spoza obsługiwanego podzbioru."""


@dataclass(frozen=True)
class _Rule:
    days: frozenset[int]
    holidays: bool  # reguła wybiera święta (PH)
    weekdays_selected: bool  # reguła ma selektor dni tygodnia (lub brak selektora)
    times: tuple[tuple[int, int], ...]  # minuty od północy; koniec może być > 1440
    modifier: str = "open"  # open | off | unknown

    def selects(self, d: date) -> bool:
        if self.holidays and is_polish_holiday(d):
            return True
        return self.weekdays_selected and d.weekday() in self.days


@dataclass
class _Schedule:
    rules: list[_Rule] = field(default_factory=list)


# ── Święta państwowe w Polsce ─────────────────────────────────────────
def _easter(year: int) -> date:
    """Wielkanoc (algorytm Meeusa/Jonesa/Butchera, kalendarz gregoriański)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=64)
def polish_holidays(year: int) -> frozenset[date]:
    easter = _easter(year)
    fixed = [(1, 1), (1, 6), (5, 1), (5, 3), (8, 15), (11, 1), (11, 11), (12, 25), (12, 26)]
    if year >= 2025:  # Wigilia dniem wolnym od pracy od 2025 r.
        fixed.append((12, 24))
    days = {date(year, m, d) for m, d in fixed}
    days |= {
        easter,
        easter + timedelta(days=1),   # Poniedziałek Wielkanocny
        easter + timedelta(days=49),  # Zielone Świątki
        easter + timedelta(days=60),  # Boże Ciało
    }
    return frozenset(days)


def is_polish_holiday(d: date) -> bool:
    return d in polish_holidays(d.year)


# ── Parsowanie ────────────────────────────────────────────────────────
def _parse_minutes(h: str, m: str) -> int:
    hh, mm = int(h), int(m)
    if mm > 59 or hh > 48:
        raise OpeningHoursError(f"Nieprawidłowa godzina {h}:{m}")
    return hh * 60 + mm


def _parse_times(text: str) -> tuple[tuple[int, int], ...]:
    out = []
    for part in text.split(","):
        m = _RANGE_RE.match(part.strip())
        if not m:
            raise OpeningHoursError(f"Nieprawidłowy przedział czasu: {part!r}")
        start = _parse_minutes(m.group(1), m.group(2))
        end = _parse_minutes(m.group(3), m.group(4))
        if start >= 1440:
            raise OpeningHoursError(f"Początek przedziału po północy: {part!r}")
        if end <= start:  # przez północ, np. 20:00-02:00
            end += 1440
        out.append((start, end))
    return tuple(out)


def _parse_selector(text: str) -> tuple[frozenset[int], bool, bool]:
    """Zwraca (dni_tygodnia, czy_PH, czy_wybrano_dni_tygodnia)."""
    text = text.strip()
    if not text:
        return _ALL_DAYS, True, True
    days: set[int] = set()
    holidays = False
    weekdays_selected = False
    for token in (t.strip() for t in text.split(",")):
        if token == "PH":
            holidays = True
        elif token == "SH":
            pass  # ferie szkolne – brak kalendarza, selektor nie wybiera żadnego dnia
        elif token in _DAY_MAP:
            days.add(_DAY_MAP[token])
            weekdays_selected = True
        elif "-" in token:
            a, b = (x.strip() for x in token.split("-", 1))
            if a not in _DAY_MAP or b not in _DAY_MAP:
                raise OpeningHoursError(f"Nieobsługiwany selektor: {token!r}")
            si, ei = _DAY_MAP[a], _DAY_MAP[b]
            days.update(range(si, ei + 1) if si <= ei else [*range(si, 7), *range(0, ei + 1)])
            weekdays_selected = True
        else:
            raise OpeningHoursError(f"Nieobsługiwany selektor: {token!r}")
    return frozenset(days), holidays, weekdays_selected


def _parse_rule(raw: str) -> _Rule:
    rule = raw.strip()
    modifier = "open"
    m = _MODIFIER_RE.search(rule)
    if m:
        modifier = {"closed": "off"}.get(m.group(1).lower(), m.group(1).lower())
        rule = rule[: m.start()].strip()

    if rule == "24/7":
        return _Rule(_ALL_DAYS, True, True, ((0, 1440),), modifier)

    # Reguła bez godzin (np. "Mo-Fr") oznacza w OSM całą dobę.
    times: tuple[tuple[int, int], ...] = ((0, 1440),)
    tm = _TIMES_SUFFIX_RE.search(rule)
    if tm:
        times = _parse_times(tm.group(1))
        rule = rule[: tm.start()].strip()
    if modifier == "off" and tm:
        # "Mo 12:00-13:00 off" – częściowe zamknięcie; nie modelujemy.
        raise OpeningHoursError("Częściowe zamknięcie ('HH:MM-HH:MM off') nieobsługiwane")

    days, holidays, weekdays_selected = _parse_selector(rule)
    return _Rule(days, holidays, weekdays_selected, times, modifier)


_DAY_ALT = r"(?:Mo|Tu|We|Th|Fr|Sa|Su|PH)"
_ALWAYS_RE = re.compile(r"^(?:24/7|24h|całodobow[oy]|całą dobę|non-?stop)\.?$", re.IGNORECASE)


def normalize(value: str) -> str:
    """Naprawia częste błędy zapisu spotykane w danych OSM/dysponentów."""
    v = re.sub(r"\s+", " ", (value or "").strip())
    if _ALWAYS_RE.match(v):
        return "24/7"
    v = re.sub(rf"\b({_DAY_ALT})(?=\d)", r"\1 ", v)  # "Su10:00" → "Su 10:00"
    # "Mo 10:00-16:00, Tu 08:00-16:00" / "Mo-Fr 06:30-20:00 Sa ..." → reguły rozdzielone ";"
    v = re.sub(rf"(?<=\d)(?:\s*,\s*|\s+)(?={_DAY_ALT}\b)", "; ", v)
    return v


@lru_cache(maxsize=4096)
def parse_opening_hours(value: str) -> _Schedule:
    value = normalize(value)
    if not value:
        raise OpeningHoursError("Brak godzin")
    if '"' in value or "||" in value:
        raise OpeningHoursError("Komentarze i reguły zapasowe nieobsługiwane")
    rules = [_parse_rule(r) for r in value.split(";") if r.strip()]
    if not rules:
        raise OpeningHoursError("Brak reguł")
    return _Schedule(rules)


def is_valid(value: str) -> bool:
    try:
        parse_opening_hours(value)
        return True
    except OpeningHoursError:
        return False


# ── Ewaluacja ─────────────────────────────────────────────────────────
def _effective_rule(schedule: _Schedule, d: date) -> _Rule | None:
    """Ostatnia reguła wybierająca dany dzień (późniejsze nadpisują wcześniejsze)."""
    chosen = None
    for r in schedule.rules:
        if r.selects(d):
            chosen = r
    return chosen


def availability(value: str, dt: datetime) -> tuple[Availability, str]:
    """Stan dostępności AED w chwili *dt* i komunikat (pusty, gdy otwarte)."""
    raw = normalize(value)
    if raw == "24/7":
        return Availability.open, ""
    try:
        schedule = parse_opening_hours(raw)
    except OpeningHoursError:
        return Availability.unknown, f"Nierozpoznane godziny dostępności „{raw or '—'}” – potwierdź telefonicznie"

    now = dt.hour * 60 + dt.minute
    today = dt.date()
    stamp = f"{_DAY_NAMES_PL[dt.weekday()]} {dt.strftime('%H:%M')}"

    # Przedziały z wczoraj przechodzące przez północ
    prev = _effective_rule(schedule, today - timedelta(days=1))
    if prev and prev.modifier == "open":
        if any(end > 1440 and now < end - 1440 for _, end in prev.times):
            return Availability.open, ""

    rule = _effective_rule(schedule, today)
    if rule is None:
        return Availability.closed, f"Zamknięte ({stamp}) – brak godzin na ten dzień; godziny: {raw}"
    if rule.modifier == "unknown":
        return Availability.unknown, f"Godziny oznaczone jako nieznane ({stamp}) – potwierdź telefonicznie"
    if rule.modifier == "off":
        holiday = " (święto)" if is_polish_holiday(today) else ""
        return Availability.closed, f"Zamknięte ({stamp}{holiday}); godziny: {raw}"
    if any(start <= now < end for start, end in rule.times):
        return Availability.open, ""
    return Availability.closed, f"Zamknięte ({stamp}); godziny: {raw}"
