# Księga znaku: akcja „Otwórz AED”

> **Konkurs:** HackNation 2026 – wyzwanie Ministerstwa Cyfryzacji / dane.gov.pl „Misja AED – Dane na ratunek”
> **Projekt:** Pulsmap / platforma Otwórz AED
> **Wersja:** 1.1
> **Wersja do druku:** [Ksiega_Znaku_Otworz_AED.pdf](Ksiega_Znaku_Otworz_AED.pdf)

---

## 1. Koncepcja

**Otwórz AED** to ogólnopolska akcja, która zachęca dysponentów defibrylatorów do otwarcia danych o swoich urządzeniach w portalu dane.gov.pl. Sygnet łączy otwartą kłódkę z linią EKG: otwarta szafka i otwarte dane oznaczają w nagłym zatrzymaniu krążenia czas, który ratuje życie. Zieleń nawiązuje do międzynarodowego oznaczenia AED i znaków ratunkowych, a prosty, geometryczny kształt jest czytelny zarówno jako ikona aplikacji, jak i naklejka na szafce. Hasło „Poświęć minutę. Podaruj czas na przeżycie.” zamienia wysiłek dysponenta – minutę na uzupełnienie danych – na minuty zyskane przez świadka i ratowników.

### Skąd pomysł
Zadanie konkursowe opisuje zdarzenie z 3 marca w centrum Warszawy: świadkowie szukali defibrylatora, który był podobno w kilku miejscach, ale zamknięty na klucz. Dane o AED są dziś rozproszone, niepełne i często niezweryfikowane. Znak ma przypominać, że dostępność urządzenia zaczyna się od dostępności informacji o nim.

### Metafora wizualna
1. **Otwarta kłódka** – odblokowana szafka, przejrzystość otwartych danych publicznych i odwaga świadka, który sięga po sprzęt.
2. **Impuls EKG** – w korpusie kłódki; przypomina o celu: przywróceniu rytmu serca w nagłym zatrzymaniu krążenia (NZK).

---

## 2. Warianty znaku

| Wariant | Plik źródłowy (wektorowy) | Eksporty |
| :--- | :--- | :--- |
| Sygnet (ikona aplikacji, favicon, naklejka) | [logo_otworz_aed.svg](logo_otworz_aed.svg) | [PNG](logo/logo_otworz_aed.png) · [JPG](logo/logo_otworz_aed.jpg) · [PDF](logo/logo_otworz_aed.pdf) |
| Logotyp poziomy z hasłem | [logo_otworz_aed_horizontal.svg](logo_otworz_aed_horizontal.svg) | [PNG](logo/logo_otworz_aed_horizontal.png) · [JPG](logo/logo_otworz_aed_horizontal.jpg) · [PDF](logo/logo_otworz_aed_horizontal.pdf) |
| Logotyp poziomy na ciemne tło | [logo_otworz_aed_horizontal_dark.svg](logo_otworz_aed_horizontal_dark.svg) | [PNG](logo/logo_otworz_aed_horizontal_dark.png) · [PDF](logo/logo_otworz_aed_horizontal_dark.pdf) |

Napisy w logotypie poziomym są zamienione na krzywe, więc plik wygląda tak samo bez zainstalowanych czcionek. Pliki PNG mają przezroczyste tło, JPG – białe.

**Tła:** znak w wersji podstawowej stosujemy na bieli i jasnych szarościach (`#FFFFFF`, `#F5F7F6`). Na ciemnym tle (np. `#14201B`) sygnet zostaje bez zmian, a napis „Otwórz” zmienia kolor na biały. Na zdjęciach znak stawiamy na białej podkładce z zachowaniem pola ochronnego.

---

## 3. Pole ochronne

Moduł **X = ¼ wysokości sygnetu** (dla sygnetu 100 px: X = 25 px). Wokół znaku zostawiamy wolną przestrzeń o szerokości **co najmniej X** z każdej strony. W polu ochronnym nie umieszczamy innych grafik, tekstów ani krawędzi nośnika.

## 4. Minimalna wielkość

| Nośnik | Sygnet | Logotyp poziomy |
| :--- | :--- | :--- |
| Druk | 12 mm szerokości | 50 mm szerokości |
| Ekran | 32 px (favicon: 16 px) | 240 px szerokości |

Poniżej tych rozmiarów hasło pod nazwą przestaje być czytelne – wtedy używamy samego sygnetu.

---

## 5. Kolorystyka

Te same wartości są w interfejsie aplikacji (`app/static/brand.css`). Kontrast podano względem bieli według WCAG 2.2.

| Rola | Nazwa | HEX | RGB | Kontrast na bieli | Zastosowanie |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Kolor główny | Zieleń ratunkowa | `#00875A` | 0, 135, 90 | 4,55:1 (AA) | sygnet, przyciski, statusy „otwarte” |
| Tekst zielony | Ciemna zieleń | `#006644` | 0, 102, 68 | 7,04:1 (AAA) | zielony tekst i linki na jasnym tle |
| Akcent | Zieleń sygnałowa | `#2BD98A` | 43, 217, 138 | 1,84:1 – tylko na ciemnym tle (9,1:1 na `#14201B`) | wskaźniki, animacje, tryb ciemny |
| Tekst | Atrament | `#14201B` | 20, 32, 27 | 16,77:1 (AAA) | nazwa „Otwórz”, nagłówki, tekst |
| Tekst pomocniczy | Szarozieleń | `#4B6358` | 75, 99, 88 | 6,51:1 (AA) | hasło w logotypie, opisy |
| Ostrzeżenie | Bursztyn | `#B54708` | 181, 71, 8 | 5,43:1 (AA) | godziny ograniczone, dane niepotwierdzone |
| Alarm | Czerwień alarmowa | `#C4262E` | 196, 38, 46 | 5,73:1 (AA) | AED zamknięte, RKO; **nigdy w znaku** |
| Tło | Biel / jasna szarość | `#FFFFFF` / `#F5F7F6` | – | – | tła, karty, certyfikaty |

---

## 6. Typografia

- **Logotyp:** Inter Tight ExtraBold (800) – nazwa „Otwórz AED”; Inter SemiBold (600), wersaliki, światło +8% – hasło pod nazwą.
- **Nagłówki w interfejsie i materiałach:** Bricolage Grotesque (600, 800).
- **Tekst:** Inter (400–700).
- **Dane techniczne** (współrzędne, kody szafek, identyfikatory): JetBrains Mono (500–700).

Wszystkie kroje są na otwartej licencji SIL Open Font License (Google Fonts).

---

## 7. Niedozwolone użycie znaku

1. **Nie zmieniaj proporcji** – nie rozciągaj i nie ściskaj znaku; skaluj tylko proporcjonalnie.
2. **Nie obracaj i nie pochylaj** znaku.
3. **Nie zmieniaj kolorów** – w szczególności nie barw sygnetu na czerwono (czerwień oznacza w systemie „AED zamknięte”) i nie używaj innych odcieni zieleni.
4. **Nie stawiaj znaku na tle o niskim kontraście** ani bezpośrednio na niespokojnym zdjęciu – użyj białej podkładki.
5. **Nie dodawaj efektów** – cieni, obrysów, gradientów, poświaty, efektów 3D.
6. **Nie zmieniaj układu i zapisu** – nie przestawiaj sygnetu i napisu, nie zmieniaj kroju, nie pisz „Otworz AED” (bez ogonka) ani „OTWÓRZ aed”.
7. **Nie modyfikuj sygnetu** – nie zamykaj kłódki, nie usuwaj ani nie zmieniaj linii EKG.
8. **Nie umieszczaj niczego w polu ochronnym.**

---

## 8. Hasła

| Wersja | Hasło | Zastosowanie |
| :--- | :--- | :--- |
| Główne | **„Poświęć minutę. Podaruj czas na przeżycie.”** | kampania, plakaty, strona główna |
| Krótkie | **„Twoja minuta. Czyjeś życie.”** | logotyp poziomy, social media, naklejki |
| Podtytuł akcji | „Ogólnopolska akcja otwierania danych o defibrylatorach w dane.gov.pl” | pod hasłem głównym, materiały informacyjne |
| Długie | „Poświęć minutę, by otworzyć dane o swoim AED – podaruj komuś czas na przeżycie.” | wezwanie do dysponentów, e-maile, formularz |
