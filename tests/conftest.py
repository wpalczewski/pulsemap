import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# Baza testowa poza data/, zanim app.database odczyta PULSEMAP_DB
os.environ["PULSEMAP_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import CREATE_TABLE_SQL  # noqa: E402


@pytest.fixture
def db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(CREATE_TABLE_SQL)
    yield con
    con.close()


@pytest.fixture(autouse=True)
def _reset_regions_cache():
    """Cache rankingu jest globalny – każdy test zaczyna od pustego."""
    import app.main as main
    main._regions_cache = None
    yield
    main._regions_cache = None
