"""Script to fetch all AEDs in Poland from OSM (Overpass API) and ingest into database."""

import asyncio
import logging
import sys
from app.database import get_db
from app.etl import fetch_osm_aeds, ingest_records

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("import_poland")

async def main():
    logger.info("Rozpoczynam pobieranie wszystkich AED z terenu Polski (OSM Overpass)...")
    records = await fetch_osm_aeds()
    logger.info(f"Pobrano {len(records)} rekordów AED z Polski.")
    
    if not records:
        logger.error("Brak rekordów z Overpass API. Sprawdź połączenie.")
        sys.exit(1)
        
    db = get_db()
    # Ensure index exists
    db.execute("CREATE INDEX IF NOT EXISTS idx_aed_lat_lon ON aed(latitude, longitude);")
    db.commit()
    
    logger.info("Wprowadzanie do bazy z deduplikacją przestrzenną...")
    report = ingest_records(db, records)
    logger.info(f"Zakończono import! Zgłoszono: {report.total_submitted}, Poprawnych: {report.valid}, "
                f"Zdeduplikowano: {report.duplicates_merged}, Błędów: {len(report.errors)}")
    
    # Check total AEDs in DB
    total = db.execute("SELECT count(*) FROM aed").fetchone()[0]
    logger.info(f"Łączna liczba AED w bazie po złączeniu: {total}")

if __name__ == "__main__":
    asyncio.run(main())
