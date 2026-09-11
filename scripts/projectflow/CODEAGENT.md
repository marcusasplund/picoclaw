# Terminalbaserad kodagent

`worker.py` använder `codeagent.py` för genererade projekt. Den tidigare
filgeneratorns `generate()`, `repair()` och filfilter används inte i byggsteget.
Planering använder fortfarande samma modellhjälpare och sparade godkännanden.

Agenten använder Picos befintliga `staticflow-llm` för beslut och ett terminalverktyg
i Docker för arbete. Ingen separat Codex-inloggning behövs. Den kan läsa och skriva
projektfiler, installera npm/Mix-paket, ändra testmiljö och köra kommandon. Inga tester
filtreras bort av controllern. Skills läses inne i arbetsmiljön och är vägledning.

Deploygränssnittet är fortfarande Solid/Vite i `frontend`, Phoenix-release `demo`
med `Demo.Release.migrate()` i `backend`, PostgreSQL och `/api/` för DB-health.
Det interna releasenamnet kommer från den fristående grunden, inte från Duchat.
Login byggs i appen med sessionscookies; Nginx-previewens Basic auth är separat.

Varje manuellt omförsök börjar i en ny Docker-arbetsmiljö från den godkända grunden.
Agentens egna kommandon och två eventuella rättningsomgångar arbetar däremot vidare
i samma miljö. Frontend-/Phoenix-/releasebyggarnas felutskrifter skickas tillbaka
till agenten. Efter tre misslyckade kontrollomgångar stoppas jobbet utan deploy.

Containern kör utan host-mounts, SSH-/modellnycklar eller Docker-socket, som uid 1000
med readonly-root och skrivbara temporära arbetsytor. Den har publik nätåtkomst för
paket och en egen tillfällig Postgres. Agenten kan inte ändra rootägda deployhelpers.
Containern har 4 GiB minnesgräns, två CPU, 512 processer och 2 GiB arbetsyta.
Hela sessionen begränsas till 80 modell/terminalsteg och tre timmar. Ett kommando
begränsas till tio minuter och 8 MiB logg. Ingen publik port öppnas under byggandet.
Dockerisolering är inte en VM-gräns; använd endast för ägarens projektinstruktioner.

Worker skickar Slack-status vid förberedelse, kodarbete och releasekontroller.
Vid `stoppa` kontrolleras jobbets claim under terminalkörning och mellan steg;
ett redan startat fristående releasekontrollkommando kan hinna slutföras.
Resultatet får ändå inte gå vidare till deploy om jobbet stoppats.

Loggar: `state/<jobb>/build-run-N/command-K.json` och `terminal-K.log`.
Varje kontrollomgång har `attempt-M/source/`, byggloggar, rapporter och vid fel
`feedback.json`. Där finns riktiga källsnapshots även om en senare rättning misslyckas.
Ingen automatisk gallring av sparade loggar, images eller snapshots görs.

## Uppdatering av den befintliga installationen

För denna ändring behövs `model_policy.py`, `codeagent.py`, `generate.py`, `worker.py`
och `dispatch.py` på macmini2. Vänta tills pågående jobb avslutats, stoppa workern
innan filerna kopieras och starta därefter.
Ingen ny Go-binär eller Lenovo-installation behövs. Befintligt failed byggjobb
kan få nytt `plan-ok`; godkänd plan och separata deploygodkännanden behålls.

Första Slack-bygget bygger den fasta terminalimagen med Node/Elixir och hämtar
Postgres. Det kan ta flera minuter. Därefter används Docker-cachen.

Ingen lokal testkörning eller exempelapp har körts för denna ombyggnad på användarens
begäran. Nästa verifiering sker genom ett riktigt Slack-jobb. Den äldre
filgeneratorns enhetstester utgör inte verifiering av terminalagenten.

## Modellval och begränsningar

`model_policy.py` väljer GPT-5.6 Luna med låg reasoning för planering och vanligt
kodarbete. Planer som nämner login/autentisering/behörigheter börjar kodarbetet med
GPT-5.6 Terra, medium reasoning. Urvalet är en enkel textheuristik, ingen klassificerare
eller säkerhetskontroll. Första misslyckade fristående byggkontrollen, två
terminalfel i följd eller två ogiltiga modellsvar växlar också upp till GPT-5.6 Terra.
Arbetsmiljö och historik behålls. Ingen automatisk nedväxling sker inom jobbet.

API-anslutningen hämtas från aliaset `openai-fast` i Slack-runtimekonfigurationen.
Luna och Terra anropas genom OpenAI Responses API; Picos äldre
Chat Completions-hjälpare används därför inte för dessa projektanrop.
Varje modellanrop får en privat temporär konfigurationsfil bredvid runtimefilen,
utanför appens arbetsmiljö. Vanlig Slack-chatt behåller sitt modellval. Saknad
modellåtkomst stoppar jobbet; workern faller inte tyst tillbaka till GPT-4o-mini.

Kör `python3 ~/.picoclaw/projectflow/model_policy.py` för att skapa
`model-routing.json` med standardvärden om filen saknas. Där kan modellval,
prisunderlag och gränser ändras. Standard: högst 60 anrop per jobb, varav 20 med
den starkare modellen, och en uppskattad budgetreserv på 10 USD. Varje anrop
reserverar för promptens UTF-8-byteantal plus marginal och 8192 outputtokens.
Detta är en konservativ uppskattning, inte uppmätt fakturering eller ett garanterat
kostnadstak hos leverantören. Prisunderlag måste uppdateras vid modell/prisbyte.

`state/<jobb>/model-usage.json` sparar anrop, reserv och modellbyten även över
manuella omförsök. Gränserna nollställs inte av `plan-ok`. Slack visar modell och
anropsantal. Modellåtkomst och beteende behöver verifieras genom nästa Slack-jobb.
