---
name: phoenix-backend
description: "Skapa och vidareutveckla Phoenix-backends med Elixir, JSON-API, Ecto och PostgreSQL. Använd för backendfunktioner och API-kontrakt; inte för frontenddesign eller serverdrift."
---

# Phoenix-backend

## Starta eller öppna projektet

- För en ny app: använd Phoenix egen generator. Kontrollera `mix help phx.new` och välj JSON-API med Ecto/Postgres när frontend är separat. Lägg till autentisering, mail och WebSockets efter produktens behov.
- Om byggflödet redan har skapat en projektgrund, arbeta vidare i den.
- I befintliga projekt: läs projektinstruktioner, `mix.exs`, router och testkonfiguration. Följ modulnamn, contexts, versioner och låsfil.

## Implementera funktionen

- Avtala endpoints, indata, JSON-svar och fel med frontend. Placera affärsregler och databasfrågor i contexts, HTTP-hantering i controllers.
- Använd Ecto-schemas, changesets och migrationer. Tillåt bara klientstyrda fält; sätt ägare och roller från verifierad serverkontext. Serialisera JSON-fält explicit.
- Avgränsa privata resurser till rätt användare/organisation vid både läsning och ändring. Följ projektets authkontrakt och CSRF-hantering.
- Använd databasconstraints för samtidighetssäkra regler och transaktioner för ändringar som måste lyckas tillsammans. Begränsa växande listor och undvik databasfrågor per rad.
- Läs hemligheter och miljöspecifika värden i runtime-konfiguration. Förbered release-migreringar om appen ska köras som release.

## Verifiera

Kör från backendroten och följ projektets verifieringsalias om ett sådant finns. Annars:

```sh
mix format --check-formatted
MIX_ENV=test mix compile --warnings-as-errors
mix test
```

- Installera beroenden och förbered testdatabasen vid behov. Kontrollera att även en överstyrande `DATABASE_URL` pekar på avsedd testdatabas.
- Testa domänregler med `DataCase` och HTTP-kontrakt med `ConnCase`, med SQL Sandbox. För privata resurser, testa även nekad åtkomst för annan användare. Mocka externa tjänster.
- Verifiera nya migrationer lokalt eller i testmiljön. Lägg till nya migrationer för redan driftsatta schemaändringar.
- Rapportera körda kontroller och kvarvarande fel. Följ byggflödets tillgängliga verktyg och godkännanden för deploy.

## Dokumentation vid behov

- [Phoenix-generatorn](https://phoenix.hexdocs.pm/Mix.Tasks.Phx.New.html)
- [Contexts](https://hexdocs.pm/phoenix/contexts.html)
- [SQL Sandbox](https://hexdocs.pm/ecto_sql/Ecto.Adapters.SQL.Sandbox.html)
- [Release-generering](https://phoenix.hexdocs.pm/Mix.Tasks.Phx.Gen.Release.html)
