# Księga Znaku i Identyfikacja Wizualna: Akcja „Otwórz AED”

> **Konkurs**: HackNation 2026 – Wyzwanie Ministerstwa Cyfryzacji / dane.gov.pl: *„Misja AED – Dane na ratunek”*  
> **Projekt**: Pulsmap / Platforma Otwórz AED  
> **Wersja**: 1.0 (Koncepcja i System Identyfikacji)  

---

## 1. Idea i Geneza Znaku

Znak akcji **„Otwórz AED”** stanowi bezpośrednią odpowiedź na problem zdiagnozowany w treści zadania konkursowego:  
> *Tragedia z 3 marca w Warszawie pokazała, że defibrylator był w zasięgu ręki, ale zamknięty w szafce. Obywatel nie wiedział, jak go otworzyć, a dyspozytor 112 nie posiadał danych w systemie.*

### Metafora wizualna
Sygnet łączy w sobie dwa nierozerwalne elementy:
1. **Otwarta kłódka**: Złamany pałąk symbolizuje przełamanie bariery dostępności, odblokowanie szafki, przejrzystość otwartych danych publicznych oraz odwagę świadka zdarzenia do sięgnięcia po sprzęt ratujący życie.
2. **Impuls EKG (linia życia)**: Zarys fali tętna umieszczony w sercu korpusu przypomina o nadrzędnym celu – podtrzymaniu rytmu serca człowieka w nagłym zatrzymaniu krążenia (NZK).

---

## 2. Architektura Znaku

W ramach systemu zdefiniowano dwa podstawowe warianty:
- **Sygnet podstawowy (ikona aplikacji / piktogram)**: plik [docs/logo_otworz_aed.svg](file:///Users/wpalcz/Desktop/HackNation2026/hack2026/pulsemap/docs/logo_otworz_aed.svg)
- **Logotyp horyzontalny (z hasłem akcji)**: plik [docs/logo_otworz_aed_horizontal.svg](file:///Users/wpalcz/Desktop/HackNation2026/hack2026/pulsemap/docs/logo_otworz_aed_horizontal.svg)

### Pole ochronne (Clear Space)
Minimalne pole ochronne wokół znaku wynosi `X`, gdzie `X` równa się wysokości litery „O” w logotypie (lub 25% szerokości sygnetu). W obrębie pola ochronnego nie mogą znajdować się żadne obce elementy graficzne, teksty ani krawędzie nośnika.

### Minimalne rozmiary
- **Druk cyfrowy i offset**: szerokość minimalna 25 mm (wariant horyzontalny) / 12 mm (sygnet).
- **Ekrany cyfrowe (Web, Mobile)**: 120 px (wariant horyzontalny) / 32 px (sygnet, favicon / app icon).

---

## 3. Paleta Barw

Kolorystyka nawiązuje do oficjalnych standardów bezpieczeństwa, medycyny ratunkowej i rządowych serwisów informacyjnych (gov.pl / dane.gov.pl), zachowując najwyższe współczynniki kontrastu (WCAG AAA).

| Rola | Nazwa koloru | HEX | RGB | Zastosowanie |
| :--- | :--- | :--- | :--- | :--- |
| **Główny Brand** | Polish Rescue Green | `#00875A` | rgb(0, 135, 90) | Sygnet, kluczowe akcje CTA, statusy dostępności |
| **Akcent / Życie** | Signal Neon Green | `#2BD98A` | rgb(43, 217, 138) | Wskaźniki LED, pulsujące punkty na mapie, ciemne tła |
| **Alarm / Ograniczenie** | Locked Crimson | `#DC2626` | rgb(220, 38, 38) | Oznaczenia szafek zamkniętych na klucz/kod, błędy |
| **Uwaga / Dostępność** | Alert Amber | `#D97706` | rgb(217, 119, 6) | Ograniczone godziny (np. 8:00 - 16:00) |
| **Tekst / Ink** | Gov Ink Dark | `#14201B` | rgb(20, 32, 27) | Typografia nagłówkowa, korpusy tekstu |
| **Tło / Płótno** | Clean Shield White | `#FFFFFF` | rgb(255, 255, 255) | Tła kart, certyfikaty, interfejs jasny |

---

## 4. Typografia

- **Krój nagłówkowy i ekspresyjny**: `Inter Tight` (odmiany Extrabold 800 i Bold 700) – dynamiczny, czytelny z daleka, skondensowany rytm geometryczny.
- **Krój dziełowy / interfejsowy**: `Inter` (odmiany Regular 400, Medium 500, SemiBold 600) – bezszeryfowy standard czytelności ekranowej.
- **Krój danych technicznych i współrzędnych**: `JetBrains Mono` – współrzędne GPS, kody otwarcia szafki, identyfikatory PRM.

---

## 5. Hasła i Komunikacja Społeczna

1. **Hasło główne (Slogan akcji)**:  
   *„Twoja minuta. Czyjeś życie.”*
2. **Hasło wzywające do działania (CTA dla świadka i zarządcy)**:  
   *„Poświęć minutę. Podaruj czas na przeżycie.”*
3. **Hasło dla zarządców obiektów (Certyfikacja)**:  
   *„Otwórz szafkę AED – nie blokuj ratunku.”*
