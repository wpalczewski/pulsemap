# ❤️‍🩹 Pulsmap – Ogólnopolska Baza Defibrylatorów AED

> **HackNation 2026 · Misja AED – Dane na ratunek**
> Ministerstwo Cyfryzacji

## 🎯 Cel projektu

Pulsmap łączy rozproszone dane o defibrylatorach AED w jeden ogólnopolski, otwarty, odczytywalny maszynowo zbiór danych gotowy do publikacji w portalu **dane.gov.pl**, z modułem operacyjnym **Tryb Dyspozytora 112**.

## ✨ Kluczowe funkcje

| Moduł | Opis |
|-------|------|
| 🗺️ **Mapa AED** | Interaktywna mapa Leaflet z klastrowaniem, kolorowaniem i filtrami statusu |
| 🚨 **Dyspozytor 112** | Symulacja zgłoszenia → najbliższe *otwarte* AED z filtrowaniem po godzinach, QR code, SMS |
| 📱 **Ekran Świadka** | Ultralekki widok mobilny `/go/{token}` – Zero-Install, WCAG AAA, nawigacja do AED |
| 📋 **Portal Dysponenta** | Formularz zgłoszenia + import CSV/JSON z walidacją i raportem |
| 📊 **Otwarte Dane** | Export CSV/JSON/GeoJSON + plik wzorcowy `.xlsx` z definicją schematu |
| 🔄 **ETL** | Deduplikacja przestrzenna Haversine (≤30m), merge źródeł, quality_score |

## 🚀 Uruchomienie

### Lokalne (bez Dockera)

```bash
cd pulsemap
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Otwórz: **http://localhost:8000**

### Docker

```bash
docker compose up --build
```

### Demo na telefonie (kod QR)

Link w kodzie QR musi wskazywać adres, który telefon otworzy, nie `localhost`.
Uruchom serwer na wszystkich interfejsach i podaj adres komputera w sieci Wi-Fi:

```bash
PULSEMAP_PUBLIC_URL=http://192.168.1.20:8000 uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Klucz API dla importu

Endpointy zapisu (`/api/v1/ingest/json`, `/upload`, `/osm`) wymagają nagłówka
`X-API-Key`, jeśli ustawiono zmienną środowiskową `PULSEMAP_API_KEY`. Bez niej
aplikacja działa w trybie demo (import otwarty, ostrzeżenie w logach).

### Import i aktualizacja danych z OSM

```bash
python import_poland_geojson.py   # pełny zrzut z data/pl_aed.geojson
```

Rekordy są dopasowywane najpierw po `(źródło, source_id)` (ponowny import
aktualizuje ten sam rekord), dopiero potem przestrzennie (≤30 m) – ale tylko
między **różnymi** źródłami. Urządzenia, które zniknęły z pełnego zrzutu,
dostają status `unverified`.

### Testy

```bash
pip install pytest
pytest -q
```

## 🔒 Dane niepubliczne

Kod do szafki AED (`access_code`) **nie jest publikowany** w otwartym zbiorze
(`/api/v1/aeds`, eksporty CSV/JSON/GeoJSON) – zastępuje go pole
`has_access_code`. Kod widzi wyłącznie dyspozytor 112 i ekran świadka w trakcie
akcji ratunkowej.

## 📐 Stack technologiczny

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLite, openpyxl
- **Frontend:** HTML5, Tailwind CSS (CDN), Leaflet.js, Vanilla JS
- **Konteneryzacja:** Docker + docker-compose
- **Zero Node.js, zero CORS, zero tarcia**

## 📦 Struktura projektu

```
pulsemap/
├── app/
│   ├── main.py          # FastAPI – endpointy API + routing
│   ├── models.py         # Pydantic v2 modele + SQLite DDL
│   ├── database.py       # Baza SQLite + seed 28 AED (Bydgoszcz)
│   ├── etl.py            # Walidacja, Haversine, parser godzin, xlsx
│   ├── templates/        # Jinja2 szablony HTML
│   │   ├── index.html        # Akcja, Mapa, Dyspozytor 112, Zgłoś AED, Dane otwarte
│   │   └── witness_go.html   # Ekran Świadka
│   └── static/
├── data/                 # SQLite database (auto-created)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## 🔗 Endpointy API

| Endpoint | Opis |
|----------|------|
| `GET /api/v1/aeds` | Wszystkie AED (JSON) |
| `GET /api/v1/export/csv` | Export CSV (UTF-8 BOM) |
| `GET /api/v1/export/json` | Export JSON |
| `GET /api/v1/export/geojson` | Export GeoJSON |
| `GET /api/v1/export/schema-xlsx` | Wzorcowy zakres danych (.xlsx) |
| `GET /api/v1/stats` | Statystyki jakości |
| `GET /api/v1/stats/regions` | Ranking województw wg kompletności danych (opis + godziny + kontakt) |
| `GET /api/v1/dispatcher/nearest` | Dyspozytor: najbliższe otwarte AED |
| `GET /api/v1/dispatcher/presets` | Scenariusze demo (centrum / biuro wieczorem / obrzeża) |
| `GET /api/v1/dispatcher/scan` | AED w promieniu 200–800 m od zgłaszającego, ze stanem (otwarte/zamknięte/niedostępne/nieznane) |
| `POST /api/v1/dispatcher/session` | Sesja ratunkowa: `AED_FOUND` (trasa) albo `CPR_ONLY` (instrukcja RKO), SMS + link do QR |
| `POST /api/v1/ingest/json` | Import rekordów JSON |
| `POST /api/v1/ingest/upload` | Import pliku CSV/JSON |
| `POST /api/v1/ingest/single` | Formularz zgłoszenia AED |
| `GET /go/{token}` | Ekran Świadka (Zero-Install) |

## ♿ Dostępność (WCAG 2.1)

- Skip to content, aria-labels, role attributes
- Pełna obsługa klawiaturą (focus-visible)
- Ekran Świadka: WCAG AAA kontrast, duże przyciski (min 64px)
- Responsywność: desktop + mobile

## 🎨 Akcja „Otwórz AED”

UI niesie identyfikację akcji: **Otwórz AED** – „Poświęć minutę. Podaruj czas na
przeżycie.” Kolory i fonty są w `app/static/brand.css`. Strona startowa (`/`) to
zakładka **Akcja** dla dysponentów; mapa jest pod `/mapa`.

Granice województw (`data/wojewodztwa.geojson`) – uproszczone dane PRG (GUGiK),
z repozytorium ppatrzyk/polska-geojson.

## 📄 Licencja

Dane: CC0 1.0 (domena publiczna)
Kod: MIT
