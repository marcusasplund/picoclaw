# Projektbyggen: Solid och Phoenix

Manuell byggare för Solid + TypeScript + Vite med npm och Vitest. Körs på
macmini2. Phoenix-verifieraren beskrivs nedan. Koppling till Slack återstår.
Det befintliga staticflow-kommandot ändras inte av installationen.

## Körning på macmini2

Kontrollera att `docker info` fungerar som vanlig användare. Kör inte byggaren
med sudo. Python 3 och Docker med Linux-containrar krävs.

```sh
python3 ~/code/picoclaw/scripts/projectbuild/solid.py \
  ~/code/min-solid-app \
  --output ~/picoclaw-builds/solid-test-001
```

Outputmappen måste vara ny och ligga utanför projektet. Projektet måste ha
`package-lock.json` samt scripts `test:types`, `lint`, `test` och `build`.
`test` ska stödja `--run` (Vitest) och `build` ska producera `dist/index.html`.
Mattea har dessa scriptnamn. Källprojektet ändras inte.

Byggaren hämtar `node:22-bookworm-slim` och låser körningen till det lokalt
upplösta image-ID:t som sparas i rapporten. Den kör `npm ci --ignore-scripts`,
kopplar bort containerns nätverk, kör `npm rebuild`, typkontroll, lint,
tester och build i ordning. Första felet stoppar körningen. Paket som behöver
ladda ner extra filer i installationsscripts stöds inte i denna version.
Privata npm-register, egna `.npmrc` och bygghemligheter stöds inte heller.

Resultatet finns i `report.json`, `build.log` och, vid godkänt bygge, `dist/`.
Rapporten innehåller källsnapshotens hash, image-ID, genomförda kontroller och
artefaktens hash. Behåll artefakten för kommande granskning/deploy; bygg inte om
den mellan godkännande och publicering. Ingen publicering görs här.

## Avgränsning

Containern kör som UID 1000 med skrivskyddat rootfilsystem, temporära
arbetsytor, resursgränser, inga capabilities, inga värdmonteringar och ingen
Docker-socket. Inga SSH-nycklar eller PicoClaw-miljövariabler skickas in.
Containern tas bort efter körningen; om städningen misslyckas anges dess
unika namn i rapporten. En avbruten värdprocess kan lämna kvar containern;
dess huvudprocess avslutas efter 30 minuter.

Detta är en första manuell byggverifierare, inte en säkerhetsgräns för fientlig
kod. Använd granskade projekt tills hårdare isolering och kontroller för
autonom körning finns. Dependencyfasen har vanligt Docker-nätverk, inklusive
möjlig åtkomst till lokala nätet. Rootless Docker eller en separat bygg-VM
är lämpligt inför autonom körning. Projektkod får inte automatiskt få tillgång
till Docker-klienten. Dockerbehörighet kan ge omfattande värdåtkomst.

Kända hemlighetsfiler och byggcache utesluts, symlänkar avvisas. Det är ingen
hemlighetsskanner: hårdkodade nycklar i vanlig källkod måste tas bort först.
Källkod och exporterad dist begränsas vardera till 20 MiB och 5000 filer.
Byggloggar och processutdata saknar ännu separata storleksgränser; detta måste
åtgärdas innan körning av obetrodd, autonomt genererad kod.

## Verifiering

```sh
python3 -m unittest discover -s scripts/projectbuild -v
```

Lokala tester täcker snapshot, uteslutning av hemlighetsfiler, symlänkar,
artefaktsökvägar, hash och containerflaggor. Riktig Docker-körning med ett
Solid-projekt måste verifieras på macmini2 innan Slack kopplas in.

## Phoenix med tillfällig Postgres

```sh
python3 ~/code/picoclaw/scripts/projectbuild/phoenix.py \
  ~/picoclaw-build-inputs/duchat-backend \
  --output ~/picoclaw-builds/phoenix-001
```

Kräver `mix.exs`, `mix.lock`, `config/test.exs` och ett Ecto/Postgres-projekt.
Körningen använder Elixir 1.18.4 / OTP 27 och Postgres 16, med faktiska image-ID:n
sparade i rapporten. Inga Dockerfiles eller compose-filer från projektet körs.

1. Starta en ny Postgres med data i tmpfs, utan publicerade portar.
2. Kopiera källkod inklusive tester och migrationer; uteslut `deps` och `_build`.
3. Installera Hex/Rebar och hämta beroenden med `mix deps.get --check-locked`.
4. Koppla bort Docker-bridge från det delade nätverksutrymmet.
5. Kör `mix deps.compile`, `mix compile --warnings-as-errors`, `mix ecto.create`,
   `mix ecto.migrate` och `mix test`, allt med `MIX_ENV=test`.
6. Spara rapport/logg och ta bort båda containrarna, inklusive testdatabasen.

Databasen lyssnar bara på delad loopback, port 5432, med testanvändare/lösenord
`postgres`/`postgres`. Det matchar Duchats befintliga testkonfiguration.
Projekt som läser `DATABASE_URL` får en fast test-URL till `picoclaw_test` på
127.0.0.1. Andra projekt måste konfigurera sin test-Repo för denna lokala
testdatabas. Byggaren skriver inte om projektets konfiguration. Externa
databaser och API:er är otillgängliga efter frånkopplingen; använd testadaptrar.

Varje steg visas i terminalen, detaljer finns i `build.log`. Första felet
stoppar bygget. Detta verifierar testmiljön och migrationer mot en tom databas;
det skapar ännu ingen produktionsrelease eller deploybar Docker-image och
testar inte uppgradering av befintliga produktionsdata.

Samma begränsning till granskad källkod som ovan gäller. Mix kan exekvera
projektkod redan vid beroendehämtning, när nätverk fortfarande finns.
Inga produktionsnycklar skickas in. Vid Ctrl-C körs städningen; vid SIGKILL,
maskinkrasch eller Dockerfel kan containrar finnas kvar. Namnen visas som
`pico-phx-*` och `pico-db-*` i `docker ps -a`; ta endast bort det aktuella jobbets
containrar. Kör aldrig generell prune för detta flöde.

Tester med simulerad Docker verifierar fasordning, stopp vid migrations- eller
nätverksfel, cleanup samt källsnapshot. Phoenix har klarat en manuell Duchat-körning
på macmini2 (`phoenix-002`). Solid har klarat en manuell Mattea-körning där.

Referenser: [Mix låsfilskontroll](https://mix.hexdocs.pm/1.18.4/Mix.Tasks.Deps.Get.html),
[Docker nätverksutrymme](https://docs.docker.com/engine/network/),
[Elixir-image](https://hub.docker.com/_/elixir).

## Produktionsrelease och starttest

Efter ett godkänt Phoenix-testbygge:

```sh
python3 ~/code/picoclaw/scripts/projectbuild/phoenix_release.py \
  ~/picoclaw-build-inputs/duchat-backend \
  --verified-report ~/picoclaw-builds/phoenix-002/report.json \
  --output ~/picoclaw-builds/phoenix-release-001
```

Byggaren kräver exakt samma källsnapshot som i den godkända rapporten, inklusive
att `mix test` har passerat. Ändrad kod kräver ett nytt testbygge. Rapportfilen
är en lokal kontroll, inte ett signerat godkännande för autonom deploy.

En genererad Dockerfile bygger med `MIX_ENV=prod`: låsta produktionsberoenden,
kompilering med warnings-as-errors och `mix release`. Projektets egna
Dockerfile och `.dockerignore` styr inte bygget. Kompilering och release körs
utan nätverk; beroendehämtning har nätverk och kan exekvera Mix-projektkod.
Docker BuildKit krävs för `RUN --network=none`.

Bygg- och runtime-stegen använder samma Elixir/OTP-bas låst till repository
digest, vilket undviker skillnader i systembibliotek. Runtime-stegen kopierar
bara releasen från byggsteget. Basimagen innehåller fortfarande byggverktyg;
detta är en större första image, inte en minimerad produktionsimage.
Inga produktionsnycklar används under bygget.

Starttestet använder exakt det byggda image-ID:t och:

1. Startar en ny Postgres med `--network none` och data i tmpfs.
2. Kör `bin/du_chat eval 'DuChat.Release.migrate()'` i en separat container.
3. Startar releasen i ytterligare en container på samma loopback-nätverk.
4. Kontrollerar HTTP 200 med JSON-kroppen `{"status":"ok"}` på `/api/`.
5. Sparar loggar och tar bort containrar, testdatabas och tillfällig envfil.

Tillfälliga SECRET_KEY_BASE, JWT_SECRET och RELEASE_COOKIE skapas efter
imagebygget. Envfilen har mode 0600 och tas bort efter testet. Databas-URL pekar
på den tomma `postgres`-databasen i testcontainern. Inga värdportar publiceras.
Runtime kör som UID 1000, med skrivskyddat rootfilsystem och skrivbar `/tmp`.

`report.json` sparar image-ID, lokal unik tagg, plattform, källhash, basdigest
och utförda kontroller. Imagen behålls lokalt i Docker även vid ett misslyckat
starttest för felsökning; endast `status: passed` betyder godkänt resultat.
Behåll det testade image-ID:t inför kommande deploy. Ingen push, export eller
installation på Lenovo sker. BuildKit-cache behålls också lokalt.

Detta verifierar migrationer mot tom databas samt HTTP-liveness. Duchats
`/api/` gör ingen DB-fråga: testet verifierar inte databasberedskap via HTTP,
autentisering, e-post, SMS, frontendintegration eller uppgradering av befintlig
data. Dessa kräver separata kontroller inför produktionsdrift.

Andra Phoenix-projekt kan ange `--release`, `--migration-module` (en modul med
`migrate/0`) och `--health-path`. `--release` anger förväntat namn på projektets
standardrelease; byggaren kör `mix release` utan namn och kontrollerar att rätt
startfil skapats. Projekt med flera releases måste ange `default_release` i
`mix.exs`. Extra externa tjänster, hemligheter och asset-
byggsteg stöds inte i denna version. Byggsteget använder BuildKits resurser och
har ännu inga egna CPU-/minnesgränser. Samma begränsning till granskad källkod
och samma logg-/avbrottsbegränsningar som övriga byggare gäller.

Lokala tester täcker källhashkontrollen, Dockerfile-isolering, image-ID,
migrationsfel, HTTP-fel och städning. Docker-starttestet behöver köras på macmini2.
Se [Mix release: körning och plattformskrav](https://mix.hexdocs.pm/1.18.4/Mix.Tasks.Release.html).
