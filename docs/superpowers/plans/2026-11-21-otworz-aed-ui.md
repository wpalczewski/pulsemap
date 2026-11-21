# „Otwórz AED” – nowa identyfikacja UI – plan wdrożenia

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zastąpić imitację gov.pl/mObywatel własną marką akcji „Otwórz AED”, dodać zakładkę „Akcja” z rankingiem województw, ciemną konsolę dyspozytora i nowy ekran świadka.

**Architecture:** Backend: nowy moduł `app/regions.py` (punkt-w-wielokącie na uproszczonych granicach województw, wynik cache’owany) + endpoint `GET /api/v1/stats/regions`. Frontend zostaje w `app/templates/index.html` (React + Babel w przeglądarce) i `witness_go.html`; kolory przechodzą na tokeny w nowym `app/static/brand.css`, a paleta Tailwind `gov` w configu jest przemapowana na markę.

**Tech Stack:** FastAPI, SQLite, pytest, React 18 UMD + Babel standalone, Tailwind CDN, Leaflet.

**Spec:** `docs/superpowers/specs/2026-11-21-otworz-aed-ui-design.md`

## Global Constraints

- Teksty marki dosłownie:
  - nazwa: `Otwórz AED`
  - hasło: `Poświęć minutę. Podaruj czas na przeżycie.`
  - krótkie: `Twoja minuta. Czyjeś życie.`
  - sub-hasło: `Ogólnopolska akcja otwierania danych o defibrylatorach w dane.gov.pl`
- Tokeny (`:root` w `brand.css`): `--brand #00875A`, `--brand-dark #006644`, `--brand-tint #E6F4EE`, `--ink #14201B`, `--ink-muted #4A5A53`, `--bg #F5F7F6`, `--warn #B54708`, `--warn-bg #FFFAEB`, `--critical #C4262E`, `--console-bg #0E1512`, `--console-card #17211C`, `--console-text #E8F0EC`.
- Mapowanie starych kolorów w `index.html` i `witness_go.html`: `#0052a5→#00875A`, `#003d7a→#006644`, `#e8f0fe`/`#f0f7ff→#E6F4EE`, `#f4f6f9→#F5F7F6`, `#1d2939→#14201B`; `#d60424→#C4262E` **tylko** dla stanów krytycznych (zamknięte, niedostępne, przycisk alarmowy 112).
- Fonty (Google Fonts): nagłówki `Bricolage Grotesque` 600/800, tekst `Inter` 400–700, liczby/kody `JetBrains Mono`.
- Zakazane w UI: `Serwis Rzeczypospolitej Polskiej`, `PolishEagleCrest`, `mObywatel`, tytuł strony zaczynający się od `dane.gov.pl`. „dane.gov.pl” wolno tylko jako miejsce publikacji danych.
- Kontrast tekstu ≥ 4.5:1 (ekran świadka ≥ 7:1), widoczny `:focus-visible`, brak poziomego scrolla strony przy 360 px.
- Trasy: `/` → Akcja, `/mapa` → mapa, `/dispatcher`, `/submit`, `/opendata` bez zmian.
- Bez commitów, dopóki użytkownik o nie nie poprosi. Nieużywane szablony (`dispatcher.html`, `submit.html`, `opendata.html`, `base.html`) zostają nietknięte.
- Testy uruchamiać przez venv: `$PY -m pytest -q` (`PY` = python z venv w scratchpadzie).

## Review Focus

1. Brak pliku granic → `/api/v1/stats/regions` zwraca `503` z komunikatem, a zakładka Akcja renderuje się bez rankingu (test w Task 1).
2. AED poza wielokątami (morze, szpary w uproszczonych granicach) liczone jako `nieprzypisane`; suma `total` po regionach = liczba AED (test w Task 1).
3. Stare linki `/dispatcher`, `/submit`, `/opendata` i nowe `/mapa` otwierają właściwą zakładkę (test w Task 2).
4. 360 px: pięć zakładek mieści się w poziomo przewijanym pasku, strona nie scrolluje się w poziomie (weryfikacja w Task 6).
5. Ciemna konsola: pola formularzy i tekst czytelne – bez białego tekstu na białym tle (weryfikacja w Task 4).

---

### Task 1: Województwa i ranking kompletności

**Files:**
- Create: `data/wojewodztwa.geojson` (pobrany z `https://raw.githubusercontent.com/ppatrzyk/polska-geojson/master/wojewodztwa/wojewodztwa-min.geojson`; źródło granic: PRG/GUGiK – atrybucja w README)
- Create: `app/regions.py`
- Modify: `app/main.py` (nowy endpoint), `app/models.py` (modele odpowiedzi), `README.md` (endpoint + atrybucja)
- Test: `tests/test_regions.py`

**Interfaces:**
- Produces:
  - `load_voivodeships(path: str | Path = "data/wojewodztwa.geojson") -> list[Voivodeship]`; `Voivodeship` = dataclass z `name: str`, `polygons` i `bbox`.
  - `assign_voivodeship(lat: float, lon: float, regions: list[Voivodeship]) -> str | None`.
  - `region_stats(db: sqlite3.Connection, regions: list[Voivodeship]) -> list[RegionStat]`.
  - `RegionStat(BaseModel)`: `name: str`, `total: int`, `complete: int`, `pct_complete: float`, posortowane malejąco po `pct_complete`, `nieprzypisane` zawsze na końcu.
  - `GET /api/v1/stats/regions` → `list[RegionStat]`, cache w pamięci procesu na 10 min.
- „Kompletny” rekord = niepusty `location_description` i `opening_hours.is_valid(opening_hours)`.

- [ ] **Step 1: Pobierz plik granic i sprawdź klucz z nazwą województwa** (`properties` → spodziewane `nazwa`). Jeśli plik ma inną strukturę, dostosuj loader, nie plik.
- [ ] **Step 2: Napisz testy** w `tests/test_regions.py`:
  - `assign_voivodeship(52.2297, 21.0122) == "mazowieckie"`, `(50.0614, 19.9366) == "małopolskie"`, `(54.6, 18.8)` (Zatoka Gdańska) `is None`;
  - `region_stats` na bazie `:memory:` z 3 AED (Warszawa kompletny, Kraków bez opisu, punkt na morzu) → mazowieckie `pct_complete == 100.0`, małopolskie `0.0`, ostatni wpis `name == "nieprzypisane"` z `total == 1`, suma `total == 3`;
  - endpoint z podmienioną ścieżką do nieistniejącego pliku → `status_code == 503`.
- [ ] **Step 3: Uruchom** `$PY -m pytest tests/test_regions.py -q` → FAIL (brak modułu).
- [ ] **Step 4: Zaimplementuj `app/regions.py`.** Ray casting po pierścieniach (Polygon i MultiPolygon, dziury odejmowane), wstępny test bbox. Bez nowych zależności.
- [ ] **Step 5: Dodaj endpoint** w `app/main.py`; ścieżka pliku w stałej modułowej `REGIONS_PATH`, żeby test mógł ją podmienić.
- [ ] **Step 6: Uruchom** `$PY -m pytest -q` → wszystko PASS. Sprawdź czas na kopii prawdziwej bazy: pierwsze wywołanie < 3 s.

### Task 2: Marka – tokeny, logo, nagłówek, nawigacja, trasy

**Files:**
- Create: `app/static/brand.css`
- Modify: `app/templates/index.html` (head, config Tailwind, `App()`, ikony), `app/main.py` (trasa `/mapa`)
- Test: `tests/test_ui_routes.py`

**Interfaces:**
- Produces:
  - `<OtworzAedLogo className />` – SVG inline: linia EKG tworząca otwartą kłódkę z sercem, w kolorze `--brand`;
  - `<OtworzAedWordmark />` – logo + napis „Otwórz AED”;
  - klucze zakładek w `App()`: `'action' | 'map' | 'dispatch' | 'register' | 'opendata'`;
  - `switchTab(tab, path)` bez zmian.

- [ ] **Step 1: Napisz testy** w `tests/test_ui_routes.py`:
  - `GET /`, `/mapa`, `/dispatcher`, `/submit`, `/opendata` → 200;
  - `GET /` nie zawiera `Serwis Rzeczypospolitej Polskiej` ani `PolishEagleCrest`, zawiera `Otwórz AED`;
  - `<title>` zaczyna się od `Otwórz AED`.
- [ ] **Step 2: Uruchom** → FAIL.
- [ ] **Step 3: Utwórz `brand.css`** z tokenami z Global Constraints oraz bazą: `body`, `:focus-visible` (2 px `--brand`, offset 2 px), klasy `.brand-nav-btn` (aktywna: dolna krawędź 3 px `--brand`), `.brand-badge-*`. Podmień `<link>` z `govpl.css` na `brand.css` w obu szablonach.
- [ ] **Step 4: Przemapuj paletę `gov` w `tailwind.config`** na tokeny marki (te same klucze, żeby istniejące klasy działały) i wykonaj mapowanie hexów z Global Constraints w `index.html`.
- [ ] **Step 5: Przebuduj nagłówek w `App()`:**
  - usuń pasek „Serwis RP” i `PolishEagleCrest`;
  - wstaw wordmark i krótkie hasło;
  - zostaw pigułkę z liczbą AED (fallback `—` zamiast `17 835`);
  - zakładki w kolejności: Akcja, Mapa AED, Dyspozytor 112, Zgłoś AED, Dane otwarte (dane.gov.pl);
  - `getInitialTab`: `/` → `action`, `/mapa` → `map`.
- [ ] **Step 6: Dodaj `@app.get("/mapa")`** do listy tras w `page_index`.
- [ ] **Step 7: Uruchom** `$PY -m pytest -q` → PASS. Sprawdź w przeglądarce, że konsola nie ma błędów.

### Task 3: Zakładka „Akcja” (`CampaignView`)

**Files:**
- Modify: `app/templates/index.html` (nowy `function CampaignView({ stats, onNavigate })`)

**Interfaces:**
- Consumes: `GET /api/v1/stats` (`total_aed`, `avg_quality_score`), `GET /api/v1/stats/regions` (Task 1), `switchTab` (Task 2) jako `onNavigate(tab, path)`.

- [ ] **Step 1: Hero.** Wordmark, hasło główne jako `h1` (Bricolage, duże), sub-hasło, licznik `N AED na mapie`, dwa przyciski CTA:
  - „Pobierz szablon danych (.xlsx)” → `/api/v1/export/schema-xlsx`;
  - „Zgłoś swój AED” → `onNavigate('register','/submit')`.
- [ ] **Step 2: Sekcja „3 kroki dla dysponenta”** z dosłownym tekstem kroków:
  1. „Pobierz szablon – jeden arkusz, 20 pól, opis każdego z nich.”
  2. „Uzupełnij dane o swoich AED – lokalizację, godziny dostępu, kontakt.”
  3. „Opublikuj w dane.gov.pl albo prześlij przez formularz – trafią na mapę i do dyspozytorów 112.”
- [ ] **Step 3: Ranking województw.** Lista z paskiem postępu (`pct_complete`), liczbą AED, wierszem „nieprzypisane” na końcu i podpisem metodologii („Kompletny = opis lokalizacji + poprawne godziny dostępności”). Gdy endpoint zwróci błąd: komunikat „Ranking chwilowo niedostępny” zamiast sekcji.
- [ ] **Step 4: Sprawdź w przeglądarce** (desktop i 375 px): brak błędów konsoli, ranking widoczny; po podmianie `REGIONS_PATH` na zły plik reszta zakładki dalej się renderuje.

### Task 4: Ciemna konsola dyspozytora

**Files:**
- Modify: `app/templates/index.html` (`DispatcherView` – klasa korzenia), `app/static/brand.css` (zakres `.theme-console`)

- [ ] **Step 1: Ustaw `theme-console` na kontenerze `DispatcherView`.** W `brand.css`, w zakresie `.theme-console`, nadpisz:
  - tła `bg-white`, `bg-gray-50`, `bg-[#F5F7F6]` → `--console-bg` / `--console-card`;
  - teksty `text-gray-*` → `--console-text` lub jego wersję przygaszoną;
  - obramowania;
  - `input`/`select`: ciemne tło, jasny tekst, jasny placeholder.

  Kafelki Leaflet zostają jasne.
- [ ] **Step 2: Pokaż czas dojścia jako główną liczbę** w kartach wyników (`walk_time_s` → „N min”), metry jako drugą linię. Dla `hours_confirmed === false` dodaj plakietkę `--warn` z `availability_note`.
- [ ] **Step 3: Sprawdź w przeglądarce** pełny przepływ: wyszukanie (Warszawa) → wysłanie trasy → podgląd statusu. Każdy tekst i pole formularza musi być czytelne (Review Focus 5), a w konsoli nie może być błędów.

### Task 5: Mapa i karta danych – nowa skóra

**Files:**
- Modify: `app/templates/index.html` (`MapView`, `RegisterView`, `OpenDataView`), `app/main.py` (`_public_aed`)
- Test: `tests/test_api.py` (dopisz przypadek)

**Interfaces:**
- Produces: pole `hours_status: "open" | "closed" | "unknown"` w każdym rekordzie `/api/v1/aeds`, liczone przez `availability(opening_hours, datetime.now())`. Tylko `/api/v1/aeds`: eksporty CSV/JSON/GeoJSON go nie dostają, bo to stan chwilowy, a nie dana zbioru.

- [ ] **Step 0: Test i implementacja `hours_status`.**
  - Test: każdy rekord z `/api/v1/aeds` ma `hours_status` z tych trzech wartości.
  - Rekord seed `aed-byd-001` (24/7) ma `open`.
  - Nagłówek CSV nie zawiera `hours_status`.
- [ ] **Step 1: Mapa.**
  - Klastry i markery w kolorze `--brand`, AED nieaktywne w `--critical`.
  - Panel szczegółów: plakietki `brand-badge-*`, nagłówki Bricolage.
  - Pod godzinami plakietka stanu z `hours_status`: „Dostępny teraz” (`--brand`), „Zamknięty teraz” (`--critical`), „Godziny niepotwierdzone” (`--warn`).
- [ ] **Step 2: Karta danych.**
  - Usuń okruszki udające dane.gov.pl („dane.gov.pl › Zbiory danych › …”).
  - Nagłówek: „Dane otwarte akcji Otwórz AED”.
  - Linia „Publikacja docelowa: dane.gov.pl”.
  - Licencja `CC0 1.0` bez zmian.
- [ ] **Step 3: Formularz zgłoszenia.** Kolory marki; nad formularzem krótkie hasło.
- [ ] **Step 4: Sprawdź w przeglądarce** wszystkie trzy zakładki na desktopie: brak błędów konsoli, brak pozostałości `#0052a5` (`grep -c 0052a5 app/templates/index.html` → `0`).

### Task 6: Ekran świadka i weryfikacja końcowa

**Files:**
- Modify: `app/templates/witness_go.html`
- Test: `tests/test_ui_routes.py` (dopisz przypadek)

- [ ] **Step 1: Dopisz test.** `GET /go/{token}` dla sesji utworzonej przez `/api/v1/dispatcher/nearest` → 200, treść nie zawiera `mObywatel`, zawiera `Otwórz AED`.
- [ ] **Step 2: Uruchom** → FAIL.
- [ ] **Step 3: Przebuduj ekran świadka.**
  - Tytuł `Otwórz AED · Trasa do defibrylatora`; zamiast godła mały wordmark.
  - Kolory tylko z tokenów, kontrast ≥ 7:1.
  - Przyciski min. 64 px wysokości; „Pobrałem AED” w `--brand`, „AED niedostępny” w `--critical`.
  - Czas dojścia jako największa liczba.
  - Usuń `maximum-scale=1.0, user-scalable=no` z meta viewport (WCAG 1.4.4).
- [ ] **Step 4: Uruchom** `$PY -m pytest -q` → wszystko PASS.
- [ ] **Step 5: Zrób zrzuty** każdej zakładki i ekranu świadka na desktopie oraz przy 360 px. Sprawdź:
  - brak poziomego scrolla strony (`document.documentElement.scrollWidth <= innerWidth`);
  - brak błędów konsoli;
  - `grep -E "Serwis Rzeczypospolitej|PolishEagleCrest|mObywatel" app/templates/index.html app/templates/witness_go.html` → brak wyników.
