"""Import all 18,303 AEDs in Poland from openaedmap GeoJSON into SQLite."""

from __future__ import annotations
import json
import logging
import time
import uuid

from app.database import get_db
from app.etl import compute_quality_score, ingest_records

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("import_poland")

GEOJSON_PATH = "data/pl_aed.geojson"

def parse_feature(f: dict) -> dict | None:
    geom = f.get("geometry") or {}
    coords = geom.get("coordinates")
    if not coords or len(coords) < 2:
        return None
    lon, lat = coords[0], coords[1]
    
    # Boundary check Poland WGS84
    if not (49.0 <= lat <= 54.9 and 14.1 <= lon <= 24.2):
        return None

    props = f.get("properties") or {}
    
    osm_type = props.get("@osm_type", "node")
    osm_id = props.get("@osm_id", "")
    source_id = f"{osm_type}/{osm_id}" if osm_id else ""

    # Address
    city = props.get("addr:city") or props.get("addr:place") or ""
    street = props.get("addr:street") or ""
    housenumber = props.get("addr:housenumber") or ""
    if street and housenumber:
        address_street = f"{street} {housenumber}"
    else:
        address_street = street or housenumber

    postcode = props.get("addr:postcode") or ""

    # Description
    desc_candidates = [
        props.get("defibrillator:location"),
        props.get("defibrillator:location:pl"),
        props.get("description"),
        props.get("note"),
        props.get("level") and f"Poziom/Piętro: {props.get('level')}",
    ]
    location_desc = "; ".join([c.strip() for c in desc_candidates if c and c.strip()])

    # Access
    access_raw = str(props.get("access", "public")).lower()
    access_map = {
        "yes": "public", "public": "public", "designated": "public",
        "customers": "customers", "customer": "customers",
        "private": "private", "no": "private",
        "permissive": "permissive", "restricted": "permissive"
    }
    access_type = access_map.get(access_raw, "public")

    access_code = props.get("defibrillator:access:code") or props.get("access:code") or None
    opening_hours = props.get("opening_hours") or "24/7"
    indoor = props.get("indoor") in ("yes", "1", True, "true") or props.get("location") == "indoor"

    operator = props.get("operator") or props.get("operator:short") or ""
    phone = props.get("phone") or props.get("contact:phone") or props.get("emergency:phone") or ""
    email = props.get("email") or props.get("contact:email") or ""
    last_verified = props.get("survey:date") or props.get("check_date") or None

    rec = {
        "aed_id": str(uuid.uuid4()),
        "source_name": "OSM",
        "source_id": source_id,
        "latitude": round(lat, 6),
        "longitude": round(lon, 6),
        "address_city": city,
        "address_street": address_street,
        "address_postal_code": postcode,
        "location_description": location_desc,
        "indoor": int(indoor),
        "access_type": access_type,
        "access_code": access_code,
        "opening_hours": opening_hours,
        "status": "active",
        "operator_name": operator,
        "operator_phone": phone,
        "operator_email": email,
        "last_verified_at": last_verified,
    }
    rec["quality_score"] = compute_quality_score(rec)
    return rec


def main():
    logger.info(f"Wczytywanie pliku {GEOJSON_PATH}...")
    t0 = time.time()
    with open(GEOJSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    logger.info(f"Wczytano {len(features)} obiektów w {time.time() - t0:.2f}s.")

    records = [r for r in (parse_feature(f) for f in features) if r]
    for r in records:
        r.pop("aed_id", None)  # ID nadaje ingest; istniejące rekordy dopasowuje po source_id

    db = get_db()
    db.execute("PRAGMA synchronous = OFF")
    db.execute("PRAGMA cache_size = 100000")

    logger.info("Import z dopasowaniem po source_id i deduplikacją przestrzenną...")
    # Plik to pełny zrzut OSM → urządzenia, które z niego zniknęły, oznaczamy jako niezweryfikowane
    report = ingest_records(db, records, sync_source="OSM")

    total_in_db = db.execute("SELECT count(*) FROM aed").fetchone()[0]
    logger.info(f"✅ IMPORT ZAKOŃCZONY W {time.time() - t0:.1f}s")
    logger.info(
        f"Nowe: {report.inserted}, zaktualizowane: {report.updated}, scalone z innym źródłem: "
        f"{report.duplicates_merged}, oznaczone jako zniknięte: {report.marked_missing}, "
        f"błędy: {len(report.errors)}"
    )
    for err in report.errors[:10]:
        logger.warning(err)
    logger.info(f"Łącznie AED w bazie: {total_in_db}")


if __name__ == "__main__":
    main()
