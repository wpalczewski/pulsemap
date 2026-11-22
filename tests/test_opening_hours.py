from datetime import datetime

import pytest

from app.opening_hours import Availability, availability, is_polish_holiday, normalize

MON_14 = datetime(2026, 11, 23, 14, 0)  # poniedziałek
MON_23 = datetime(2026, 11, 23, 23, 0)
TUE_01 = datetime(2026, 11, 24, 1, 0)
NOV_11 = datetime(2026, 11, 11, 10, 0)  # środa, Święto Niepodległości
SAT_10 = datetime(2026, 11, 28, 10, 0)


def state(oh, dt):
    return availability(oh, dt)[0]


@pytest.mark.parametrize("oh,dt,expected", [
    ("24/7", MON_23, Availability.open),
    ("Mo-Fr 08:00-16:00", MON_14, Availability.open),
    ("Mo-Fr 08:00-16:00", MON_23, Availability.closed),
    ("Mo-Fr 08:00-16:00", SAT_10, Availability.closed),
    # wiele przedziałów w jednej regule
    ("Mo-Fr 08:00-12:00,13:00-16:00", MON_14, Availability.open),
    ("Mo-Fr 08:00-12:00,13:00-16:00", datetime(2026, 11, 23, 12, 30), Availability.closed),
    # przez północ – wieczór i noc następnego dnia
    ("Mo-Su 20:00-02:00", MON_23, Availability.open),
    ("Mo-Su 20:00-02:00", TUE_01, Availability.open),
    ("Mo-Su 20:00-02:00", MON_14, Availability.closed),
    ("Mo 22:00-26:00", TUE_01, Availability.open),
    # późniejsza reguła nadpisuje wcześniejszą (semantyka OSM)
    ("Mo-Fr 08:00-16:00; Mo 10:00-12:00", MON_14, Availability.closed),
    ("Mo-Su 08:00-20:00; Sa off", SAT_10, Availability.closed),
    # święta
    ("Mo-Fr 08:00-16:00; PH off", NOV_11, Availability.closed),
    ("Mo-Fr 08:00-16:00; Sa-Su, PH off", MON_14, Availability.open),
    ("Mo-Fr 07:00-17:00; Sa-Su, PH, SH off", MON_14, Availability.open),
    # dni bez godzin = cała doba
    ("Mo-Fr", MON_23, Availability.open),
    # częste błędy zapisu naprawiane przez normalize()
    ("Całodobowo", MON_23, Availability.open),
    ("Mo 10:00-16:00, Tu 08:00-16:00", MON_14, Availability.open),
    ("Mo-Fr 06:30-20:00 Sa 07:00-14:00", SAT_10, Availability.open),
    # nierozpoznane → unknown, nigdy „zamknięte”
    ("sunrise-sunset", MON_14, Availability.unknown),
    ("Jun-Aug Mo-Su 09:30-18:30", MON_14, Availability.unknown),
    ("w godzinach pracy budynku", MON_14, Availability.unknown),
    ("", MON_14, Availability.unknown),
    ("Mo-Fr 08:00-16:00; We unknown", datetime(2026, 11, 25, 10, 0), Availability.unknown),
])
def test_availability(oh, dt, expected):
    assert state(oh, dt) == expected


def test_closed_reason_mentions_hours():
    st, reason = availability("Mo-Fr 08:00-16:00", SAT_10)
    assert st == Availability.closed and "Pn-Pt 08:00-16:00" in reason


@pytest.mark.parametrize("d", ["2026-04-05", "2026-04-06", "2026-06-04", "2026-12-24", "2026-05-03"])
def test_polish_holidays(d):
    assert is_polish_holiday(datetime.fromisoformat(d).date())


def test_not_holiday():
    assert not is_polish_holiday(MON_14.date())


def test_normalize_keeps_time_lists():
    assert normalize("Mo-Fr 08:00-12:00, 13:00-16:00") == "Mo-Fr 08:00-12:00, 13:00-16:00"
    assert normalize("Su10:00-18:00") == "Su 10:00-18:00"


# ── Polskie skróty dni tygodnia ───────────────────────────────────────
from app.opening_hours import format_pl, to_osm  # noqa: E402


def test_format_pl_translates_days_and_keywords():
    assert format_pl("Mo-Fr 08:00-18:00") == "Pn-Pt 08:00-18:00"
    assert format_pl("Mo-Sa 09:00-21:00; Su 10:00-20:00") == "Pn-Sb 09:00-21:00; Nd 10:00-20:00"
    assert format_pl("We,Th 10:00-12:00; PH off") == "Śr,Cz 10:00-12:00; święta nieczynne"
    assert format_pl("24/7") == "24/7"
    assert format_pl("") == "24/7"


def test_to_osm_accepts_polish_input():
    assert to_osm("Pn-Pt 08:00-18:00") == "Mo-Fr 08:00-18:00"
    assert to_osm("Pn-Sb 09:00-21:00; Nd 10:00-20:00") == "Mo-Sa 09:00-21:00; Su 10:00-20:00"
    assert to_osm("Śr 10:00-12:00; święta nieczynne") == "We 10:00-12:00; PH off"
    assert to_osm("Mo-Fr 08:00-18:00") == "Mo-Fr 08:00-18:00"


def test_parser_understands_polish_days():
    assert availability("Pn-Pt 08:00-16:00", MON_14)[0] == Availability.open
    assert availability("Pn-Pt 08:00-16:00", SAT_10)[0] == Availability.closed


def test_closed_reason_uses_polish_days():
    _, reason = availability("Mo-Fr 08:00-16:00", SAT_10)
    assert "Pn-Pt 08:00-16:00" in reason and "Mo-Fr" not in reason
