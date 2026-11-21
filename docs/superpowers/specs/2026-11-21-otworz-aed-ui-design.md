# „Otwórz AED” – nowa identyfikacja UI (projekt)

## Po co
Aplikacja dziś udaje dane.gov.pl / gov.pl / mObywatel (godło, „Serwis
Rzeczypospolitej Polskiej”, niebiesko-szary styl). Chcemy, żeby niosła
**własną markę akcji** – logo i hasło to 25% oceny, a zrzuty UI trafią do
prezentacji. Akcja zachęca dysponentów AED do udostępniania danych w dane.gov.pl.

## Marka (ustalona)
- **Nazwa / logo:** Otwórz AED
- **Hasło główne:** „Poświęć minutę. Podaruj czas na przeżycie.”
- **Wersja krótka:** „Twoja minuta. Czyjeś życie.”
- **Sub-hasło:** „Ogólnopolska akcja otwierania danych o defibrylatorach w dane.gov.pl”
- **Długie wezwanie:** „Poświęć minutę, by otworzyć dane o swoim AED – podaruj komuś czas na przeżycie.”
- **Kolory:** zieleń AED `#00875A` (główny), grafit `#14201B`, biel, bursztyn do
  ostrzeżeń, czerwień tylko dla stanów krytycznych (zamknięte / niedostępne).
- **Znak:** linia EKG, która w jednym miejscu tworzy otwartą kłódkę / uchylone
  drzwiczki szafki z sercem. SVG inline w UI.

## Cele
- Usunąć imitację gov.pl / mObywatel ze wszystkich ekranów (godło, pasek
  „Serwis RP”, tytuły „dane.gov.pl …”, „mObywatel 2.0”). dane.gov.pl zostaje
  wymieniane jako **miejsce publikacji danych**, nie jako tożsamość aplikacji.
- Nowa zakładka **„Akcja”** jako ekran startowy (`/` → Akcja, mapa pod `/mapa`):
  hasło + sub-hasło, licznik „N AED na mapie”, 3 kroki dla dysponenta
  (pobierz szablon xlsx → uzupełnij → opublikuj w dane.gov.pl / zgłoś przez
  formularz), CTA do formularza i szablonu, **ranking województw** wg odsetka
  rekordów z pełnym opisem lokalizacji i godzinami (kompletność danych).
- Mapa i karta danych: jasne, spokojne. Czas dojścia w minutach przy AED.
- Konsola dyspozytora 112: **ciemny, wysokokontrastowy** motyw.
- Ekran świadka `/go/{token}`: marka Otwórz AED zamiast mObywatela, ogromne
  przyciski, kontrast AAA.
- WCAG: kontrast ≥ 4.5:1 dla tekstu, focus-visible, responsywność ≥ 360 px.

## Poza zakresem
- Przepisywanie frontu bez Babel/React-w-przeglądarce (droga C).
- Pliki logo do oddania (.png/.pdf/.svg) i księga znaku PDF – osobne zadanie,
  ale wykorzystają ten sam SVG i kolory.
- Zmiany logiki API poza tym, czego wymaga ranking.

## Anty-cele
- Wygląd „kolejnego dashboardu” – zakładka Akcja ma być plakatem kampanii, nie tabelką.
- Czerwień jako kolor przewodni (alarmowość, zmęczenie w konsoli).
- Zepsucie działających przepływów: dyspozytor → wysłanie trasy → ekran świadka → status.

## Podejścia
- **A.** Nowa skóra obecnego frontu – najszybsze, ale brak miejsca, gdzie żyje kampania.
- **B. (wybrane)** A + zakładka „Akcja” z rankingiem – pokazuje akcję, nie tylko narzędzie.
- **C.** B + przepisanie frontu – szybsze ładowanie, ale duże ryzyko przed oddaniem, niewidoczne dla jury.

## Jak (decyzje)
- `app/static/brand.css` z tokenami (`:root`) zamiast `govpl.css`; Tailwind
  config w `index.html` przestawiony na tokeny marki.
- Typografia z Google Fonts: nagłówki **Bricolage Grotesque**, tekst **Inter**,
  liczby/kody **JetBrains Mono** (już używany). *(moja decyzja)*
- Ranking województw: AED nie mają dziś województwa (99% bez miasta).
  Przypisujemy je punkt-w-wielokącie na podstawie uproszczonych granic
  województw (publiczny GeoJSON ~150–300 KB, zapisany w `data/`), liczone raz
  przy starcie i cache’owane; nowy endpoint `GET /api/v1/stats/regions`.
  Kolumna `voivodeship` przydatna też w zbiorze dla dane.gov.pl.
  *(wymaga pobrania pliku granic – do potwierdzenia)*
- Nieużywane szablony (`dispatcher.html`, `submit.html`, `opendata.html`,
  `base.html`) zostają nietknięte.

## Dla wykonawcy
- Dokładny kształt znaku, ilustracje, mikro-animacje, kolejność sekcji na Akcji.
- Weryfikacja: zrzuty desktop + mobile każdej zakładki i ekranu świadka,
  brak błędów konsoli, testy `pytest` zielone.
