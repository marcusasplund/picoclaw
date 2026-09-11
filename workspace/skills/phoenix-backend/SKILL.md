---
name: phoenix-backend
description: "Bygg och vidareutveckla Phoenix-backends i Elixir med JSON-API, Ecto, PostgreSQL, ExUnit och release-migreringar, med Duchat som referens. Använd för backendfunktioner och API-kontrakt mot exempelvis SolidJS; inte för frontenddesign eller driftsättning på server."
---

# Phoenix-backend för PicoClaw

Arbeta i användarens Phoenix-projekt. Duchat är en referens för arbetssätt, inte ett obligatoriskt paket av chatt, SMS och autentisering. Skillen ska också fungera utan att Duchat finns på Picos maskin.

## Identifiera projektet

- Läs projektinstruktioner, `mix.exs`, `mix.lock`, `config/`, router, application/supervision tree och testsetup. Backend kan ligga i exempelvis `backend-phoenix/` i ett större repo.
- Följ befintliga modulnamn, contexts och JSON-konventioner. Byt inte ett fungerande projekts arkitektur bara för att referensen ser annorlunda ut.
- För ny backend till en separat Solid-app: utgå från ett Phoenix JSON-API med Ecto/Postgres. Kontrollera den installerade Phoenix-generatorns flaggor och kompatibla Elixir/OTP-versioner innan scaffolding. LiveView, mail, WebSockets och autentisering läggs till när produkten behöver dem.
- Bevara befintlig låsfil och versionsval. Duchats versionsnummer och Dockerbaser är observationer, inte en aktuell standard för alla nya appar.
- Läs [Duchats arbetssätt](references/duchat-patterns.md) när du väljer contextstruktur, tester eller releaseupplägg.

## Från funktion till API

1. Beskriv den aktuella resursen, indata, svar och relevanta fel. Följ frontendens avtalade kontrakt; välj ett konsekvent format när det saknas.
2. Placera affärsregler och databasfrågor i contexts. Låt controllers hantera HTTP, autentiserad aktör, anrop till context och serialisering.
3. Använd Ecto-schemas för lagrad data, changesets för tillåtna attribut/validering och migrationsfiler för schemat. Returnera hanterbara resultat, exempelvis `{:ok, resource}` eller `{:error, changeset}`, i förväntade felvägar.
4. Koppla routes, behörigheter och tester för den konkreta funktionen. Ett CRUD-exempel behöver inte bli ett generellt ramverk.

Håll JSON-svar explicita så att interna schemafält inte exponeras av misstag. Använd projektets JSON-moduler eller motsvarande etablerade serialisering. Avtala statuskoder och fältnamn med klienten: exempelvis valideringsfel som klienten kan koppla till formulärfält, samt tydlig hantering av saknad resurs och nekad åtkomst.

## Data och behörighet

- Whitelista klientens ändringsbara fält i changesets. Sätt ägare, roller och andra serverstyrda attribut från verifierad kontext i stället för att lita på användarens JSON.
- Avgränsa frågor och mutationer till rätt aktör/organisation när data är privat. Kontrollera åtkomst även när klienten skickar ett giltigt resurs-ID; ett autentiserat anrop innebär inte åtkomst till alla rader.
- Kombinera databasconstraints med changeset-hantering för regler som måste hålla även vid samtidiga anrop. Unikhet får exempelvis inte enbart bero på en föregående SELECT.
- Använd transaktioner, exempelvis `Ecto.Multi`, när flera databasändringar måste lyckas tillsammans. Lägg inte långsamma externa nätverksanrop i en transaktion utan ett motiverat behov och en felstrategi.
- Preloada medvetet och undvik en extra databasfråga per rad. Lägg gränser/paginering på listor som kan växa.
- Följ befintligt authkontrakt. Kopiera inte Duchats OTP/JWT eller inför ett nytt authsystem som bieffekt av en vanlig endpoint. Cookiebaserad browserauth behöver korrekt CSRF-hantering; CORS är inte en behörighetskontroll.
- Lägg inte utvecklingslogin, testmail eller andra dev-endpoints i produktionsrouting. Returfel och loggar ska inte innehålla hemligheter eller autentiseringsuppgifter.

## Testa i avsedd miljö

Kontrollera att testkonfigurationen pekar på en separat, avsedd testdatabas innan databas-kommandon körs. Ett `MIX_ENV=test` ersätter inte granskning av en överstyrande `DATABASE_URL`.

För ett projekt med Duchats upplägg körs följande från backendroten när beroenden och testdatabas behöver förberedas:

```sh
mix deps.get
MIX_ENV=test mix ecto.create
MIX_ENV=test mix ecto.migrate
mix format --check-formatted
mix verify
```

Duchats `mix verify` väljer testmiljön och kör kompilering med warnings-as-errors följt av tester. Kontrollera att motsvarande alias faktiskt finns i målprojektet. Annars använd:

```sh
MIX_ENV=test mix compile --warnings-as-errors
mix test
```

- Testa contextregler och databasbeteende med `DataCase`; använd `ConnCase` för routing, JSON-kontrakt, autentisering och HTTP-fel.
- Använd SQL Sandbox och projektets fixtures. Vid tester med separata processer måste sandboxägande/delning hanteras uttryckligt; lägg inte bara till `async: true` för att göra tester snabbare.
- För en privat resurs: verifiera lyckat flöde, ogiltig indata och att en annan användare inte kan läsa eller ändra resursen. Testa relevanta DB-constraints och samtidighetsregler.
- Mocka externa tjänster vid enhetstester. SMS, mail och push ska inte skickas på riktigt för att testa en vanlig backendändring.
- Vid ny migration: verifiera den på en avsedd lokal/testdatabas. Ändra inte redan körda migrationsfiler för att dölja ett schemaproblem; lägg till en ny migration.
- Rapportera verkliga kommandoresultat. Saknad Postgres eller Elixir är en kvarvarande verifieringspunkt, inte ett godkänt testresultat.

## Runtime och release

- Läs produktionshemligheter och miljöspecifika värden från runtime-konfiguration. Obligatoriska värden ska ge ett begripligt startfel när de saknas, utan att värdet loggas. Låt dem inte hamna i källkod, bygglager eller frontendens publika konfiguration.
- Följ projektets inställningar för databasanslutning, pool, host, port och proxy. Ange vilka runtimevariabler funktionen behöver; kopiera inte en verklig `.env` från referensprojektet.
- Skilj en enkel liveness-respons från readiness som kontrollerar nödvändiga beroenden. Duchats `{status: "ok"}` bevisar att HTTP-processen svarar, inte att databasen fungerar.
- Förbered release-migreringar genom projektets release-modul eller Phoenix-genererade migrationsscript. En produktionsrelease behöver kunna migrera utan installerat Mix på målservern.
- Beskriv migrationsordning och kompatibilitet mellan gamla/nya appversioner. En återställning av en container återställer inte automatiskt databasschemat. Destruktiva schemaändringar behöver en separat plan för data och återställning.
- Kontrollera att releasebyggets och körmiljöns OS/bibliotek är kompatibla när Dockerfiler ändras. Överlämna image, runtimekrav, migrationskommando och hälsokontroll till deployflödet; att skriva backendkod är inte i sig ett godkännande av produktionsmigrering eller deploy.

## Gränsen mot PicoClaws jobbflöde

Skillen ger instruktioner, inte nya verktygsbehörigheter. Använd tillgänglig byggmiljö och befintliga godkännanden. Aktivera inte exec, Docker, SSH eller sudo genom att ändra agentkonfigurationen för att kringgå ett saknat verktyg.

Det nuvarande `staticflow`-bygget genererar tre statiska filer i ett verktygslöst modellanrop. Det läser inte automatiskt denna skill, kör inte Mix/Postgres och deployar inte Phoenix. En projektbyggare och ett separat Docker-deployflöde måste anslutas för detta. Skilj därför en färdig backendplan eller källkodsändring från ett byggt, testat och driftsatt system.

## Officiella referenser

Kontrollera detaljer mot projektets faktiska versioner:

- [Phoenix contexts](https://hexdocs.pm/phoenix/contexts.html)
- [Phoenix contexttester](https://phoenix.hexdocs.pm/testing_contexts.html)
- [Ecto SQL Sandbox](https://hexdocs.pm/ecto_sql/Ecto.Adapters.SQL.Sandbox.html)
- [Phoenix release-generering](https://phoenix.hexdocs.pm/Mix.Tasks.Phx.Gen.Release.html)
