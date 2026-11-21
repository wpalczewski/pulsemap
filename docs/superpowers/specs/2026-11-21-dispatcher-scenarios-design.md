# Scenariusz ratunkowy: dyspozytor 112 ↔ ekran świadka (projekt)

Źródło: zadanie użytkownika z 2026-11-21 („Rozbudowa trybu dyspozytora 112 oraz
ekranu świadka”). Poniżej wymagania w skrócie + decyzje, które doprecyzowują
miejsca niejasne lub sprzeczne z obecnym kodem.

## Wymagania (z zadania)

**Dyspozytor (`/dispatcher`, `DispatcherView` w `index.html`)**
- Zgłaszający nanoszony kliknięciem w mapę albo jednym z 3 presetów:
  „Centrum – AED dostępne 24/7”, „Biuro wieczorem – AED zamknięte”,
  „Obrzeża – brak AED w zasięgu”. Czerwony, pulsujący marker „Zgłaszający 112”.
- Okrąg `L.circle` wokół zgłaszającego, domyślnie **400 m**, suwak **200–800 m**.
- W okręgu: **zielone** markery = aktywne i otwarte w czasie symulacji;
  **wyszarzone/przekreślone** = zamknięte lub niedostępne, z powodem.
- Selektor czasu: „Teraz” / „Niedziela 22:00” (+ istniejący własny ISO).
- **Scenariusz A** (jest otwarte AED w promieniu): przerywana linia do
  najbliższego; karta: odległość (m), czas dojścia **w obie strony**, adres,
  opis w budynku, kod szafki. Przycisk **„WYŚLIJ TRASĘ DO AED (SMS / QR)”** →
  sesja `scenario = "AED_FOUND"`, treść SMS, **kod QR**, przycisk otwarcia `/go/{token}`.
- **Scenariusz B** (brak): komunikat „Brak dostępnego AED w promieniu {radius} m
  (najbliższe otwarte urządzenie jest za daleko, aby opuścić poszkodowanego)”.
  Przycisk **„WYŚLIJ INSTRUKCJĘ RKO / PIERWSZEJ POMOCY (SMS / QR)”** → sesja
  `scenario = "CPR_ONLY"`, QR / link.

**Świadek (`/go/{token}`)**
- Widok A: `140 m • ok. 2 min drogi` + `OTWARTE TERAZ`; duży adres; ramka
  „Lokalizacja: …”; blok `KOD DO SZAFKI: 1234`; przycisk
  `OTWÓRZ NAWIGACJĘ PIESZĄ (Google Maps)`; czerwony
  `URZĄDZENIE ZAMKNIĘTE / BRAK AED NA MIEJSCU` → AED `temporarily_unavailable`,
  przełączenie na drugie AED **z promienia** albo na Widok B.
- Widok B: komunikat „Nie opuszczaj poszkodowanego — w pobliżu brak dostępnego
  AED. Rozpocznij resuscytację (RKO) do przyjazdu karetki.”; 3 kroki (treść
  z zadania); przycisk `URUCHOM RYTM UCISKÓW (110/min)` – puls wizualny +
  opcjonalny dźwięk Web Audio; stoper.

**Seed**
- ≥ 2 AED z bardzo szczegółowym opisem lokalizacji; jedno z `access_code: "1912"`.
- ≥ 1 AED `Mo-Fr 08:00-18:00`.

## Decyzje (doprecyzowania)

1. **Plik.** `dispatcher.html` nie istnieje (usunięty) – dyspozytor to
   `DispatcherView` w `app/templates/index.html`.
2. **Bez wpisywania adresu.** Geokodowanie wymaga zewnętrznej usługi (Nominatim:
   limity, wysyłanie danych na zewnątrz, brak sieci na demo). Wystarczą klik + presety.
3. **Sesja powstaje dopiero po „Wyślij”**, nie przy wyszukiwaniu (dziś
   `/nearest` tworzy sesję przy każdym wyszukaniu). Serwer sam ponownie liczy
   AED w promieniu – nie ufa liście z przeglądarki.
4. **Drugie AED tylko z promienia.** Przełączenie z Widoku A jest na drugie
   *otwarte AED w promieniu sesji*; brak → Widok B.
5. **AED o nierozpoznanych godzinach** w promieniu: **bursztynowy** marker,
   traktowane jak kandydat z ostrzeżeniem (spójnie z obecnym parserem), ale
   po potwierdzonych otwartych.
6. **QR na telefon.** Link w QR budowany z `PULSEMAP_PUBLIC_URL` (np.
   `http://192.168.1.20:8000`), w przeciwnym razie z adresu żądania. Gdy wynik
   to `localhost`/`127.0.0.1`, panel ostrzega, że telefon tego nie otworzy.
7. **Czas dojścia** = odległość / 1,4 m/s; „w obie strony” = ×2.
8. **Seed na istniejącej bazie.** Seed wstawia się tylko do pustej bazy, a demo
   działa na bazie z 18 tys. AED. Rekordy demo dla presetów są więc
   **dopisywane/aktualizowane idempotentnie przy każdym starcie**
   (`aed-demo-*`, źródło `Demo_OSM`).
9. **Presety w backendzie** (`GET /api/v1/dispatcher/presets`) z ustalonymi
   współrzędnymi i czasem symulacji, żeby dało się je przetestować. Preset
   „Obrzeża” musi dawać brak AED w 800 m także na **prawdziwych** danych –
   współrzędne dobierane skryptem na kopii bazy.
10. **Dostępność.** Puls markerów i metronomu respektuje
    `prefers-reduced-motion` (wtedy zmiana koloru zamiast animacji skali);
    dźwięk tylko po kliknięciu (wymóg przeglądarek).
11. **`/api/v1/dispatcher/nearest` zostaje** (opisany w README, używany w testach).
