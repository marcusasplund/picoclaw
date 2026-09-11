# Arbetssätt hämtade från Duchat

Referensgranskning: 2026-09-06. Observationerna bygger på Duchats källkod och konfiguration, inte på en ny körning av dess testsvit eller Dockerbygge. Sökvägarna är relativa till Duchat-repot; det behöver inte finnas på Picos maskin.

## Projektgränser

Phoenix ligger i `backend-phoenix/`, Solid-webben i `web-duchat/`, och det finns även en separat React Native-klient. Repo-rotens `docker-compose.yml` hör till backenddriften. Kör Mix-kommandon från backendroten och frontendkommandon från respektive frontendrot.

En ny app kan ha `backend/` och `frontend/`; det viktiga är entydiga arbetskataloger och tydliga kontrakt, inte att alla projekt har samma mappnamn.

## Contexts, schema och HTTP

- `lib/du_chat/repo.ex` är Ecto-repot och `lib/du_chat/application.ex` innehåller applikationens startstruktur.
- `lib/du_chat/accounts/`, `chat/` och `feedback/` innehåller domänmoduler och schemas. Denna uppdelning följer produktens domäner.
- `lib/du_chat_web/router.ex` har JSON-routes under `/api`, samt en separat adminpipeline med `RequireAdmin`.
- `controllers/default_controller.ex` svarar med enkel HTTP-hälsa och ett capability-svar. Den visade health-funktionen gör ingen databasfråga.

Överför uppdelningen mellan HTTP-lager och domänlogik. Routergruppen `/api` garanterar inte ensam att varje route har korrekt behörighetskontroll; granska controllers, plugs och contexts för respektive operation.

### Changeset-exemplet

`lib/du_chat/feedback/ticket.ex` definierar bland annat titel, text, status, skaparnamn och association till användare. Changesetet validerar obligatoriska fält, längder och tillåtna statusvärden.

Använd mönstret för tydliga domänregler, men kopiera inte attributlistan blint. Det är sammanhanget som avgör om exempelvis `user_id`, skaparnamn eller status ska få komma från klienten. I en ny privat resurs sätts ägarskap från den autentiserade aktören.

## Testupplägg

`test/support/data_case.ex` startar en SQL Sandbox-ägare för testet och stoppar den vid avslut. `ConnCase` återanvänder sandboxsetup och bygger en anslutning för controllertester. Projektet har separata controller-, domän-, policy- och channeltester.

I `mix.exs` finns:

- `verify` som alias för `compile --warnings-as-errors` och `test`.
- `preferred_envs` som placerar `verify` i testmiljön.
- `test/support` i kompileringssökvägarna för test.

Kopiera hela avsikten när en motsvarande verifieringsrutin skapas: rätt miljö, rätt testdatabas och felande exitkod vid problem. Dokumenterade testantal i Duchats `docs/testing.md` är en historisk observation; de är inte ett krav för andra projekt eller bevis på aktuell grön testsvit.

## Runtime och release

`config/runtime.exs` hanterar databas, Phoenix-host/port, nycklar och integrationsinställningar. Flera integrationsdelar är specifika för Duchat: SMS, SMTP, web push, JWT och nätverksprofiler. En ny antecknings- eller bokningsapp ska inte ärva dessa utan ett faktiskt behov.

`lib/du_chat/release.ex` innehåller `migrate/0` och `rollback/2`. De laddar applikationen, hämtar repos och anropar `Ecto.Migrator` via `with_repo`. Därmed finns en väg för databasändringar från en release. En rollbackfunktion bevisar däremot inte att varje migration är reversibel utan dataförlust.

`backend-phoenix/Dockerfile` bygger en release i ett steg och kopierar den till körimagen. Vid granskningen använder builder och runner olika Alpine-versioner. Återanvänd releaseprincipen; verifiera kompatibla imageversioner i den nya appen.

## Det som återstår för en generell deployskill

Duchats Compose-fil definierar en backendimage, ett fast containernamn och portbindningen `4000:4000`. Nätverket `duchat-net` är externt och någon databastjänst definieras inte i den filen. Det förutsätter alltså redan förberedd driftmiljö.

`scripts/deploy_backend.sh` bygger image och återskapar backendcontainern. Det anropar inte release-migreringen och gör inte automatiskt en hälsokontroll, även om deploydokumentationen beskriver manuella kontroller.

En framtida generell Docker-deployskill behöver egna projektnamn/nätverk/volymer, explicit hantering av databas och migreringar, valbara hostportar och verifiering efter deploy. Dessa driftändringar hör inte till ett vanligt backenduppdrag och ska inte utföras genom att kopiera Duchats scripts oförändrade.
