# Arbetssätt hämtade från Mattea

Referensgranskning: 2026-09-06. Dessa observationer kommer från Matteas källkod och konfiguration. De är inte ett påstående om att dess nuvarande bygge eller tester har körts vid skillens skapande. Källsökvägarna nedan är relativa till Mattea-repot och behövs inte på Picos maskin.

## Struktur att anpassa

Mattea använder SolidJS, TypeScript, Vite, Tailwind, Kobalte, Solid Router, lucide-solid, Vitest och Solid Testing Library. Dess matematikgeneratorer, KaTeX, utskriftslägen, PWA och översättningar är produktspecifika tillägg.

En motsvarande struktur för ett annat projekt kan vara:

```text
src/
  components/ui/         återanvändbara interaktionsprimitiver
  components/            gemensamma appkomponenter
  routes/                sidkomposition
  features/<feature>/    typad domänlogik, feature-UI och tester
  lib/api.ts             API-anrop när en backend finns
  Layout.tsx             gemensam layout och providers
  setupTests.ts          gemensam testsetup
```

Detta är ett förslag för nya projekt, inte skäl att byta namn på en fungerande befintlig struktur. Mattea använder själv bland annat `tasksheets/<ämne>/` för sina featureområden.

## Konkret referens: rena generatorer

I `src/tasksheets/addition/generator.ts` ligger typer, indataalternativ och beräkningar utanför UI. Slumpen får en seed. `addition.test.tsx` testar bland annat att svar är korrekta och att begränsningar för uppgifterna respekteras.

Överför principen: beräkningar, filtrering, validering och transformationer ska kunna testas utan att rendera en sida. Använd deterministiska tester när funktionen innehåller slump. Testernas filändelse är mindre viktig än vad som faktiskt testas.

## Konkret referens: numeriska fält

`src/components/worksheet/WorksheetNumberField.tsx` håller rå text och numeriskt värde separat. Tom eller ogiltig inmatning kan visas och valideras; ett giltigt domänvärde skickas vidare genom callback. Vid commit hanteras gränsvärden och återgång till ett giltigt värde. En effekt synkroniserar ändrade props med fältets lokala state.

Överför principen till andra formulär där användaren behöver kunna skriva ofärdiga värden. Anpassa reglerna till domänen; trunkering till heltal är exempelvis rätt för vissa uppgifter men inte för belopp eller mätvärden med decimaler.

## Konkret referens: UI och layout

`src/Layout.tsx` samlar layout, routerkoppling, temaprovider och notifieringar. `components/ui` innehåller primitiver som featurekomponenter komponerar. `components/worksheet` samlar återkommande mönster för just arbetsblad.

Överför uppdelningen mellan generell primitive, produktkomponent och sida. En ny produkt ska få egna ord, informationsstruktur och visuell karaktär; arbetsbladsfunktioner och navigationsskal kopieras bara om uppgiften behöver dem.

## Konfigurationsdetaljer

- `tsconfig.json` har strikt TypeScript, Solid JSX-inställningar och `~/*` som alias till `src/*`.
- `vite.config.ts` har `vite-plugin-solid` och `@tailwindcss/vite`. Det finns även en PWA-plugin för appens service worker, vilket inte är ett generellt baskrav.
- `vitest.config.ts` använder Solid-pluginen, `happy-dom`, `src/setupTests.ts` och alias som motsvarar appen. Testsetup importerar `@testing-library/jest-dom/vitest`.
- Det finns också en `test`-sektion i Vite-konfigurationen som nämner `jsdom`. Kopiera inte två olika testmiljöer av misstag: välj ett tydligt testupplägg i en ny app och verifiera vilken konfiguration kommandot använder.
- `package.json` innehåller både Solid- och React-testbibliotek. En ny Solid-app behöver Solid Testing Library; ärv inte React-beroendet enbart för att det finns i referensfilen.
- Mattea har separat `test:types` och ett `build` som kör Vite. Behåll separationen mellan typkontroll och paketering.
- Mattea använder Tailwinds Vite-plugin och har även en `tailwind.config.js`. Vid en ny Tailwind-installation ska integrationen följa den valda majorversionens dokumentation; anta inte att äldre JS-konfiguration automatiskt laddas.

## Framtida Phoenix-koppling

Mattea är frontendreferensen. En Solid-klient mot Phoenix behöver ett eget API-kontrakt, felhantering och lokal/produktionsrouting. Duchat kan ge backendexempel, men dess chatt, SMS, autentisering och externa Docker-nätverk är inte beroenden för denna skill.

Den här skillen lämnar frontendens källkod, verifieringsresultat och API-behov som underlag till kommande backend- och deployarbete. Den skapar inga serverbehörigheter eller databasinställningar.
