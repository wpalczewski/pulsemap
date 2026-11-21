"""Pulsmap – przypisanie AED do województw i ranking kompletności danych.

Granice: uproszczony GeoJSON województw (data/wojewodztwa.geojson, na podstawie
PRG/GUGiK). Punkt-w-wielokącie metodą ray casting, bez dodatkowych zależności.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from app.opening_hours import is_valid

UNASSIGNED = "nieprzypisane"

Ring = list[tuple[float, float]]  # (lon, lat)


@dataclass(frozen=True)
class Voivodeship:
    name: str
    polygons: tuple[tuple[Ring, ...], ...]  # każdy: pierścień zewnętrzny + dziury
    bbox: tuple[float, float, float, float]  # min_lon, min_lat, max_lon, max_lat


class RegionStat(BaseModel):
    name: str
    total: int
    complete: int
    pct_complete: float


def load_voivodeships(path: str | Path = "data/wojewodztwa.geojson") -> list[Voivodeship]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for feat in data["features"]:
        geom = feat["geometry"]
        raw = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        polygons = tuple(tuple([(float(x), float(y)) for x, y, *_ in ring] for ring in poly) for poly in raw)
        xs = [x for poly in polygons for x, _ in poly[0]]
        ys = [y for poly in polygons for _, y in poly[0]]
        out.append(Voivodeship(feat["properties"]["nazwa"], polygons, (min(xs), min(ys), max(xs), max(ys))))
    return out


def _in_ring(x: float, y: float, ring: Ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def assign_voivodeship(lat: float, lon: float, regions: list[Voivodeship]) -> str | None:
    for r in regions:
        min_x, min_y, max_x, max_y = r.bbox
        if not (min_x <= lon <= max_x and min_y <= lat <= max_y):
            continue
        for outer, *holes in r.polygons:
            if _in_ring(lon, lat, outer) and not any(_in_ring(lon, lat, h) for h in holes):
                return r.name
    return None


def _is_complete(row: sqlite3.Row) -> bool:
    """Kompletny = opis lokalizacji + poprawne godziny + kontakt do opiekuna AED."""
    has_contact = bool((row["operator_phone"] or "").strip() or (row["operator_email"] or "").strip())
    return (
        bool((row["location_description"] or "").strip())
        and is_valid(row["opening_hours"] or "")
        and has_contact
    )


def region_stats(db: sqlite3.Connection, regions: list[Voivodeship]) -> list[RegionStat]:
    counts: dict[str, list[int]] = {}
    for row in db.execute("SELECT latitude, longitude, location_description, opening_hours, operator_phone, operator_email FROM aed"):
        name = assign_voivodeship(row["latitude"], row["longitude"], regions) or UNASSIGNED
        c = counts.setdefault(name, [0, 0])
        c[0] += 1
        c[1] += _is_complete(row)

    def stat(name: str) -> RegionStat:
        total, complete = counts[name]
        return RegionStat(name=name, total=total, complete=complete,
                          pct_complete=round(complete / total * 100, 1))

    ranked = sorted((stat(n) for n in counts if n != UNASSIGNED),
                    key=lambda s: (-s.pct_complete, -s.total))
    if UNASSIGNED in counts:
        ranked.append(stat(UNASSIGNED))
    return ranked
