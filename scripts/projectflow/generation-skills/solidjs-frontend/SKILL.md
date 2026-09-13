---
name: solidjs-frontend
description: "Bygg och vidareutveckla SolidJS-frontends med TypeScript och Vite, enligt arbetssätt från Mattea: återanvändbara komponenter, reaktivitet, formulär och tester. Använd för SolidJS-appar och deras frontendintegration med API:er; inte för Phoenix-backend eller driftsättning."
---

# SolidJS-frontend för PicoClaw

Skapa och ändra frontendkod i användarens projekt. Mattea är en referens för struktur och arbetssätt, inte en app som ska kopieras. Följ befintlig produkt, design och paketstruktur när du arbetar i ett projekt.

## Börja i rätt projekt

- Läs projektets instruktioner, `package.json`, låsfil, TypeScript-, Vite- och testkonfiguration. Identifiera appens rot; den kan vara en undermapp i ett repo.
- Leta efter befintliga UI-primitiver, routes, teman och API-klienter innan du skapar motsvarigheter.
- Vid ny app: föredra SolidJS + TypeScript + Vite. Lägg till Tailwind, Kobalte, routing och ikoner efter appens behov. Mattea använder dessa, men de behöver inte alla ingå i en liten app.
- Behåll befintliga versioner och paketmanager. Vid ny installation: verifiera kompatibla Node- och paketversioner i officiell dokumentation och spara låsfilen; kopiera inte en gammal referensapps versionsnummer som om de vore aktuell standard.
- Läs [Matteas arbetssätt](references/mattea-patterns.md) när du behöver välja projektstruktur, komponentindelning eller testupplägg. Referensen sammanfattar relevanta delar; tillgång till Mattea-repot krävs inte.

## SolidJS-kod

- Använd `createSignal` för lokal state, `createMemo` för härledda värden och `createEffect` för synkronisering med sidoeffekter. Bevara signalernas accessorer i reaktiva uttryck.
- Läs ändringsbara props via `props.value`, eller använd `splitProps`/`mergeProps` där det behövs. Destrukturera inte sådana props vid komponentens toppnivå så att reaktiviteten försvinner. Destrukturering av vanliga optionsobjekt i rena funktioner är däremot normalt.
- Använd Solid-komponenter och bibliotek: `Show`, `For`, `Switch`/`Match`, Solid Router och Solid Testing Library. Importera inte React-hooks eller React-komponenter i Solid-kod.
- Lägg rensning av lyssnare, timers och prenumerationer i `onCleanup`. Undvik att läsa browserglobala objekt på modulnivå när de försvårar tester eller eventuell serverrendering.
- Behåll `jsx: "preserve"`, `jsxImportSource: "solid-js"` och strikt TypeScript. Om projektet använder `~/` ska aliaset stämma i TypeScript, Vite och testkonfigurationen.

## Komponenter och produktbeteende

- Återanvänd `components/ui` för knappar, fält, dialoger och andra primitiver. Kobalte kan ligga bakom dessa; använd dess semantik och tangentbordsbeteende genom hela wrappern.
- Håll domänlogik i vanliga TypeScript-moduler och komponera den med UI i sid-/featurekomponenter. Extrahera gemensamma komponenter när det finns faktisk återanvändning.
- Separera formulärets råa inmatning från det godkända domänvärdet när mellanlägen måste kunna representeras. Ett tomt numeriskt fält ska exempelvis inte omedelbart förvandlas till noll.
- Behåll synliga labels, kopplade felmeddelanden och fokustillstånd. Visa väntan, fel, tomt resultat och lyckat resultat där användaren annars inte vet vad som händer.
- Använd projektets färg-, typografi- och avståndstokens. Anpassa layouten för små skärmar och tangentbord. Kopiera inte Matteas skolämnen, texter eller varumärke till andra produkter.
- Svensk UI-text är ett rimligt utgångsläge i Marcus projekt när inget annat anges. Följ befintligt språk och i18n-system. Inför inte flerspråkighet, PWA eller mörkt tema enbart för att Mattea har det.

## API-integration

- Bekräfta endpoint, datatyper, felstruktur och autentiseringssätt med befintlig backend eller avtalad API-specifikation.
- Samla HTTP-anrop i en liten typad klient; kontrollera `response.ok`. TypeScript-typer validerar inte nätverksdata vid körning: validera de fält som appens funktion förlitar sig på.
- Använd exempelvis `createResource` för hämtningar och explicita pending-/felstatusar för mutationer. Förhindra dubbel submit och uppdatera/refetcha data först efter rätt svar.
- Föredra relativa `/api/...`-URL:er när frontend och backend ska ligga bakom samma domän. En lokal Vite-proxy är utvecklingskonfiguration; den ersätter inte produktionsrouting.
- Browserkonfiguration och `VITE_*`-variabler är publika. Lägg aldrig API-hemligheter, databaslösenord eller deploynycklar där. Följ backendens cookie-/CSRF- eller tokenkontrakt i stället för att hitta på ett nytt authflöde.
- Om backend saknas: håll mockdata tydligt avgränsad och beskriv vad som återstår. Rapportera inte en mockad koppling som verifierad integration.

## Verifiera ändringen

Utgå från projektets scripts och kör relevanta kontroller i appens rot. För ett npm-projekt med Matteas scriptnamn:

```sh
npm ci
npm run test:types
npm run lint
npm run test -- --run
npm run build
```

`npm ci` kräver en befintlig, synkroniserad npm-låsfil. Kör det när beroenden behöver installeras, inte som krav inför varje liten ändring. I ett nytt projekt skapas låsfilen med projektets valda paketmanager. Använd motsvarande befintliga scripts om namnen skiljer sig.

- Vite-bygget ersätter inte TypeScript-kontrollen. Kör Vitest utan watch i automatiska jobb.
- Testa domänregler och relevanta gränsfall med rena tester. Testa formulär och interaktioner med `@solidjs/testing-library`, genom roller/labels och observerbart beteende.
- Verifiera relevanta laddnings-, fel- och tomlägen vid API-ändringar. Använd seedad slump eller injicerade beroenden när logiken annars blir svår att testa reproducerbart.
- Bevara projektets coveragekrav. Kopiera inte Matteas 100-procentskrav till varje nytt projekt utan beslut om omfattning.
- Om browserverktyg finns: kontrollera det ändrade användarflödet, en smal viewport, tangentbordsnavigation och konsolfel. Om de saknas, ange att visuell och browserbaserad verifiering återstår.
- Rapportera vilka kontroller som faktiskt kördes, deras resultat och kvarvarande problem. Skilj byggbar frontend, mockat API och fungerande integration åt.

## Gränsen mot PicoClaws jobbflöde

Denna skill är instruktioner, inte behörigheter eller en build-runner. Använd tillgängliga, godkända verktyg och befintliga jobb-godkännanden. Ändra inte `exec`-inställningar, SSH-nycklar, sudo, Nginx eller Docker för att göra skillen körbar.

Det befintliga `staticflow`-bygget gör ett verktygslöst modellanrop och accepterar endast `index.html`, `style.css` och `app.js`. Det läser inte automatiskt denna skill och kan inte bygga ett Vite-projekt. En separat projektbyggare måste anslutas innan Slack-kommandot `bygg` kan använda dessa instruktioner för en full Solid-app. Ge en korrekt plan eller källkodsändring inom tillgänglig miljö; påstå inte att npm, tester eller deploy körts när verktygsstödet saknas.

## Officiella referenser

Kontrollera versionsspecifika detaljer vid behov:

- [Solid: reaktivitet och props](https://github.com/solidjs-community/eslint-plugin-solid/blob/main/packages/eslint-plugin-solid/docs/reactivity.md)
- [Solid: datahämtning](https://docs.solidjs.com/guides/fetching-data)
- [Solid: tester](https://docs.solidjs.com/guides/testing)
- [Tailwind med Vite](https://tailwindcss.com/docs/installation/using-vite)
