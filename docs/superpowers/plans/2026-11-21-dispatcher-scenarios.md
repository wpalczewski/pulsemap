# Scenariusz ratunkowy dyspozytor ↔ świadek – plan wdrożenia

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dyspozytor nanosi zgłaszającego, widzi AED w promieniu (otwarte / zamknięte), wysyła trasę (A) albo instrukcję RKO (B), a świadek dostaje odpowiedni widok z fallbackiem i metronomem.

**Architecture:** Nowy moduł `app/dispatch.py` z czystą logiką „skanu promienia” (bez FastAPI), dwa nowe endpointy (`/scan`, `/session`) i presety w `app/main.py`. `rescue_session` dostaje kolumny `scenario` i `radius_m`. Frontend: `DispatcherView` w `index.html` przechodzi z `/nearest` na `/scan` + `/session`; `witness_go.html` dostaje Widok B (RKO + metronom).

**Tech Stack:** FastAPI, SQLite, pytest, React 18 UMD + Babel, Leaflet 1.9, qrcodejs 1.0 (już załadowany), Web Audio API.

**Spec:** `docs/superpowers/specs/2026-11-21-dispatcher-scenarios-design.md`

## Global Constraints

- Promień: domyślnie `400`, zakres `200–800` m (poza zakresem → 422).
- Prędkość marszu `1.4` m/s (stała `WALK_SPEED_MS`); „w obie strony” = 2 × czas.
- Scenariusze dosłownie: `"AED_FOUND"`, `"CPR_ONLY"`.
- Teksty dosłownie (spec): przyciski „WYŚLIJ TRASĘ DO AED (SMS / QR)”, „WYŚLIJ INSTRUKCJĘ RKO / PIERWSZEJ POMOCY (SMS / QR)”, „OTWÓRZ NAWIGACJĘ PIESZĄ (Google Maps)”, „URZĄDZENIE ZAMKNIĘTE / BRAK AED NA MIEJSCU”, „URUCHOM RYTM UCISKÓW (110/min)”; komunikaty B dla dyspozytora i świadka jak w spec.
- Metronom: **110** BPM.
- Kolory: zielony `#00875A` (otwarte), szary `#5B6B64` + przekreślenie (zamknięte/niedostępne), bursztynowy `#B54708` (godziny nieznane), czerwony `#C4262E` (zgłaszający).
- W JSX w szablonach **nie wolno** używać `{{` (Jinja) – obiekty stylu przez zmienne.
- Animacje respektują `prefers-reduced-motion`.
- Bez commitów, dopóki użytkownik nie poprosi. Testy: `$PY -m pytest -q`.

## Review Focus

1. QR zeskanowany telefonem wskazuje `localhost` → panel pokazuje ostrzeżenie i podpowiedź `PULSEMAP_PUBLIC_URL` (test w Task 2).
2. Świadek klika „zamknięte” dwa razy lub po przejściu na RKO → brak błędu, widok B zostaje (test w Task 2).
3. Wygasła sesja (> 6 h) → zdarzenia 410, ekran świadka pokazuje „sesja wygasła” + 112 (test w Task 2).
4. Zmiana suwaka/czasu po wysłaniu → sesja trzyma swój `radius_m` i swoje AED; panel wymaga ponownego „Wyślij” (weryfikacja w Task 3).
5. Brak dźwięku (blokada autoodtwarzania, wyciszony telefon) → metronom nadal pulsuje wizualnie (weryfikacja w Task 4).

---

### Task 1: Logika skanu promienia + rekordy demo + presety

**Files:**
- Create: `app/dispatch.py`, `tests/test_dispatch.py`
- Modify: `app/database.py` (rekordy demo, startowe upserty), `app/main.py` (presety + `/scan`), `app/models.py`

**Interfaces:**
- Produces:
  - `AedState = Literal["open", "closed", "unavailable", "unknown"]`
  - `scan_radius(db, lat: float, lon: float, radius_m: int, dt: datetime) -> ScanResult`
  - `ScanResult(BaseModel)`:
    - `in_radius: list[ScannedAED]` – posortowane po odległości;
    - `candidates: list[ScannedAED]` – maks. 2: najpierw `open`, potem `unknown`, każda grupa po odległości;
    - `nearest_open_outside_m: float | None` – najbliższe `open` poza promieniem, szukane do 5 km;
    - `scenario: Literal["AED_FOUND", "CPR_ONLY"]`.
  - `ScannedAED(BaseModel)`:
    - `aed_id`, `latitude`, `longitude`, `distance_m`, `walk_time_s`, `round_trip_s`;
    - `state: AedState`, `reason: str`;
    - `address_street`, `address_city`, `location_description`, `opening_hours`;
    - `has_access_code: bool`, `access_code: str | None`, `google_maps_url`.
  - `ensure_demo_records(db) -> None` – upsert po `aed_id` (prefiks `aed-demo-`), źródło `Demo_OSM`, wywoływane w `lifespan` po `seed_database`.
  - `DISPATCH_PRESETS: list[dict]` (`id`, `label`, `lat`, `lon`, `timestamp`) i `GET /api/v1/dispatcher/presets`.
  - `GET /api/v1/dispatcher/scan?lat&lon&radius_m=400&timestamp=` → `ScanResult`, bez tworzenia sesji.

- [ ] **Step 1: Napisz testy** w `tests/test_dispatch.py` na bazie `:memory:` z rekordami z `ensure_demo_records`:
  - `test_scan_classifies_states`:
    - AED `Mo-Fr 08:00-18:00` w promieniu, środa 20:30 → `state == "closed"`, `reason` zawiera `Mo-Fr 08:00-18:00`;
    - `status="temporarily_unavailable"` → `"unavailable"`;
    - `24/7` → `"open"`;
    - wszystkie `distance_m <= radius_m`.
  - `test_scan_scenario_b_when_nothing_open` – `scenario == "CPR_ONLY"`, `candidates == []`, `nearest_open_outside_m` > `radius_m`.
  - `test_candidates_prefer_open_over_unknown` – `unknown` bliżej niż `open` → `candidates[0].state == "open"`.
  - `test_round_trip` – `round_trip_s == 2 * walk_time_s`.
  - `test_demo_records_idempotent`:
    - dwa wywołania `ensure_demo_records` dają tę samą liczbę rekordów `aed-demo-%`;
    - jeden ma `access_code == "1912"`, jeden `opening_hours == "Mo-Fr 08:00-18:00"`;
    - ≥ 2 mają `location_description` dłuższy niż 40 znaków.
  - `test_presets_produce_expected_scenarios` (przez `/scan` na bazie testowej z seedem i demo):
    - „Centrum” → `AED_FOUND`, a `candidates[0].opening_hours == "24/7"`;
    - „Biuro wieczorem” → w `in_radius` jest AED `closed` z `Mo-Fr 08:00-18:00`;
    - „Obrzeża” → `CPR_ONLY` przy 800 m.
  - `test_scan_radius_bounds` – `radius_m=150` i `900` → 422.
- [ ] **Step 2: Uruchom** `$PY -m pytest -q tests/test_dispatch.py` → FAIL (brak modułu).
- [ ] **Step 3: Zaimplementuj `app/dispatch.py`.** Prefiltr bbox (jak w `/nearest`), stan z `availability()`, a `status != "active"` daje `unavailable` przed sprawdzeniem godzin. Wynik ma zawierać `access_code`, bo endpoint jest dla dyspozytora.
- [ ] **Step 4: Rekordy demo w `app/database.py`.** 3–4 rekordy w Bydgoszczy:
  - centrum 24/7 z `access_code "1912"` i opisem „Parter, na ścianie przy głównej klatce schodowej obok windy”;
  - biuro `Mo-Fr 08:00-18:00` z opisem „Hol przy recepcji, prawa ściana, za bramkami wejściowymi”.

  Presety w `app/main.py` z `timestamp`: Centrum `null` (teraz), Biuro `2026-11-25T20:30:00` (środa), Obrzeża `2026-11-25T20:30:00`.
- [ ] **Step 5: Dobierz współrzędne presetów na prawdziwych danych.** Skryptem na kopii bazy (`$SP/copy.db`) sprawdź, że:
  - „Biuro” nie ma innego otwartego AED w 400 m o tej porze;
  - „Obrzeża” (w granicach Bydgoszczy) nie ma otwartego AED w 800 m.

  Jeśli warunek nie jest spełniony, przesuń punkt i zapisz w ledgerze nowe współrzędne.
- [ ] **Step 6: Uruchom** `$PY -m pytest -q` → wszystko PASS.

### Task 2: Sesja ze scenariuszem, fallback i link publiczny

**Files:**
- Modify: `app/models.py` (DDL + modele), `app/database.py` (migracja kolumn), `app/main.py` (`POST /api/v1/dispatcher/session`, fallback w `report-unavailable` i `rescue/{token}/event`, `/go/{token}`)
- Test: `tests/test_dispatch.py` (dopisz)

**Interfaces:**
- Consumes: `scan_radius` (Task 1).
- Produces:
  - nowe kolumny `rescue_session.scenario TEXT DEFAULT 'AED_FOUND'` oraz `radius_m INTEGER DEFAULT 400`;
  - `POST /api/v1/dispatcher/session`:
    - wejście: `{lat, lon, radius_m, timestamp?, caller_phone?, dispatch_channel?}`;
    - serwer sam robi `scan_radius` i wybiera `scenario`;
    - wyjście `SessionCreated`: `token`, `scenario`, `rescue_url`, `sms_text`, `call_ref`, `public_url_warning: str | None`, `aed: ScannedAED | None`.
  - `public_base_url(request) -> str` – zwraca `PULSEMAP_PUBLIC_URL` albo `request.base_url`; ostrzeżenie, gdy host to `localhost`/`127.0.0.1`.
  - Fallback „AED niedostępny”:
    - przy `slot == 1` i istniejącym `aed_id_2` → slot 2;
    - w przeciwnym razie `scenario = "CPR_ONLY"`;
    - odpowiedź `{"scenario": ..., "switched": bool}`.
  - `/go/{token}` przekazuje do szablonu `scenario`.

- [ ] **Step 1: Napisz testy:**
  - `test_session_aed_found` – preset Centrum → `scenario == "AED_FOUND"`, `sms_text` zawiera `rescue_url` i kod `1912`, w bazie `radius_m == 400`.
  - `test_session_cpr_only` – preset Obrzeża → `CPR_ONLY`, `aed is None`, `sms_text` zawiera „RKO”.
  - `test_fallback_to_second_then_cpr`:
    - pierwsze zgłoszenie niedostępności → `switched True`, slot 2;
    - drugie → `scenario == "CPR_ONLY"`;
    - trzecie → 200 i nadal `CPR_ONLY` (Review Focus 2).
  - `test_public_url_warning` – bez zmiennej, host `testserver`/`localhost` → `public_url_warning` niepusty; z `PULSEMAP_PUBLIC_URL=http://192.168.1.20:8000` → `rescue_url` zaczyna się od niego, ostrzeżenie `None`.
  - `test_expired_session_events_410` – `created_at` sprzed 7 h → `POST /go/{token}/report-unavailable` → 410 (Review Focus 3).
  - `test_witness_renders_cpr_view` – sesja `CPR_ONLY` → HTML `/go/{token}` zawiera „Nie opuszczaj poszkodowanego”.
- [ ] **Step 2: Uruchom** → FAIL.
- [ ] **Step 3: Zaimplementuj** migrację kolumn (wzorem `_run_migrations`), endpoint, `public_base_url` i fallback. Używaj `now_pl()` zamiast `datetime.now()` dla czasu symulacji.
- [ ] **Step 4: Uruchom** `$PY -m pytest -q` → wszystko PASS.

### Task 3: Panel dyspozytora – mapa, okrąg, scenariusze A/B, QR

**Files:**
- Modify: `app/templates/index.html` (`DispatcherView`), `app/static/brand.css` (pulsujący marker, przekreślone markery)

**Interfaces:**
- Consumes: `/api/v1/dispatcher/presets`, `/scan`, `/session` (Task 1–2); istniejące `/send-route` i `/rescue/{token}/status` do telemetrii.

- [ ] **Step 1: Mapa.**
  - Marker zgłaszającego: klasa `.caller-pulse` (czerwony `#C4262E`, animacja skali, w `prefers-reduced-motion` bez animacji).
  - `L.circle` z promieniem ze stanu `radiusM` i suwakiem `input type=range min=200 max=800 step=50`.
  - Każda zmiana punktu, promienia albo czasu woła `/scan` (debounce 250 ms).
  - Markery według `state` w kolorach z Global Constraints; zamknięte i niedostępne przekreślone (`✕`), z `bindTooltip(reason)`.
- [ ] **Step 2: Presety i czas.**
  - Presety z endpointu zastępują dzisiejsze miasta.
  - Selektor czasu: „Teraz”, „Niedziela 22:00”, własny ISO.
- [ ] **Step 3: Scenariusz A.**
  - Przerywana `L.polyline` (`dashArray: '8 8'`) do `candidates[0]`.
  - Karta: metry, „w obie strony ~N min”, adres, opis, kod.
  - Przycisk „WYŚLIJ TRASĘ DO AED (SMS / QR)” → `/session` → QR (`qrcodejs`) z `rescue_url`, treść SMS z przyciskiem „Kopiuj”, przycisk „Otwórz widok dzwoniącego” (`target=_blank`).
  - Ostrzeżenie `public_url_warning`, jeśli jest.
- [ ] **Step 4: Scenariusz B.**
  - Bursztynowo-czerwony panel z dosłownym komunikatem ze spec (z `{radius}`) oraz „najbliższe otwarte: X m”, jeśli `nearest_open_outside_m`.
  - Przycisk „WYŚLIJ INSTRUKCJĘ RKO / PIERWSZEJ POMOCY (SMS / QR)” → `/session` → QR i link.
- [ ] **Step 5: Po wysłaniu** zmiana promienia, czasu albo punktu chowa QR i pokazuje „Zmieniono parametry – wyślij ponownie” (Review Focus 4). Telemetria jak dziś przez `/status`.
- [ ] **Step 6: Weryfikacja w przeglądarce** (desktop i 375 px), każdy preset na **kopii prawdziwej bazy**:
  - Centrum → linia + karta z kodem 1912;
  - Biuro wieczorem → przekreślony marker z powodem;
  - Obrzeża → panel B.

  QR się renderuje, w konsoli nie ma błędów, `$PY -m pytest -q` PASS.

### Task 4: Ekran świadka – Widok A i Widok B z metronomem

**Files:**
- Modify: `app/templates/witness_go.html`

**Interfaces:**
- Consumes: `scenario` z szablonu (Task 2), odpowiedź fallbacku `{scenario, switched}`.

- [ ] **Step 1: Widok A** według spec:
  - nagłówek `{m} m • ok. {min} min drogi` + plakietka `OTWARTE TERAZ` (albo „Godziny niepotwierdzone” dla `unknown`);
  - „Lokalizacja: …” w ramce; `KOD DO SZAFKI: {kod}`;
  - przyciski: „OTWÓRZ NAWIGACJĘ PIESZĄ (Google Maps)” i czerwony „URZĄDZENIE ZAMKNIĘTE / BRAK AED NA MIEJSCU”.

  Po odpowiedzi z `scenario == "CPR_ONLY"` widok przełącza się na B bez przeładowania. Przyciski min. 64 px, tekst ≥ 18 px bold.
- [ ] **Step 2: Widok B.** Dosłowny komunikat ze spec i 3 kroki z dużymi numerami (treść ze spec).
- [ ] **Step 3: Metronom 110/min.**
  - Przycisk „URUCHOM RYTM UCISKÓW (110/min)” / „ZATRZYMAJ”.
  - Rytm planowany na zegarze `AudioContext.currentTime` (krótki ton 880 Hz, 40 ms); wizualny puls zsynchronizowany przez `requestAnimationFrame` z tym samym zegarem. Bez `AudioContext` → `performance.now()`.
  - `navigator.vibrate(30)` przy uderzeniu, jeśli dostępne.
  - Stoper mm:ss od pierwszego uruchomienia; nie zeruje się po pauzie.
  - Przy `prefers-reduced-motion` zmiana koloru zamiast skali.
- [ ] **Step 4: Weryfikacja w przeglądarce** (375 i 360 px):
  - sesja A → klik „zamknięte” → drugie AED → klik → Widok B;
  - metronom: odstęp między uderzeniami 545 ± 15 ms, zmierzony w JS przez 20 uderzeń;
  - przy zawieszonym `AudioContext` puls nadal działa (Review Focus 5);
  - brak poziomego scrolla i błędów konsoli; `$PY -m pytest -q` PASS.
