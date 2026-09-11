# Pico: fri byggbeskrivning → plan → appkod → Docker

Byggsteget har ersatts av en terminalbaserad kodagent. Se [CODEAGENT.md](CODEAGENT.md)
för aktuellt beteende, installation och loggar. Beskrivningen av den gamla
filgeneratorn längre ned är historisk och gäller inte genererade projekt längre.
Uppgiftsbaserat modellval och eskalering styrs av `model_policy.py`; se även
avsnittet om modellval och begränsningar i CODEAGENT.md.

Skriv `build a todo app with a database` i en ny Slack-tråd. Beskrivningen är indata till
Picos modell, inte ett val av en förbyggd todoapp. Plannern väljer en av två
låsta profiler: `static` använder endast **SolidJS/TypeScript** och browserlagring;
`fullstack` använder **SolidJS/TypeScript + Phoenix/Ecto + Postgres**. Externa
integrationer och andra stackar kräver fortsatt separat stöd.

## Flöde

1. Workern ber modellen skapa en konkret plan, API-kontrakt och testbara krav.
   Den använder Pico-skillsen i `generation-skills` och grundens beroenden.
2. Pico slackar planen. Ägaren svarar `approve` i samma tråd.
3. Modellen genererar frontend och funktionella tester. Endast fullstackprofilen
   genererar backend och migrationer.
   Den får skriva appfiler; paket, konfiguration, release/health, Docker och
   serverkommandon kommer från en fast grund i `templates/application`.
4. Workern kör alltid Solid-kontroller. Phoenix/Postgres-tester och
   release/starttest körs endast för fullstack. Vid bygg-/testfel får modellen
   högst två lokala rättningsförsök.
   Alla försök sparas separat. Inget byggfel orsakar deploy.
5. Efter godkända kontroller skapar host-processen ett nytt privat GitHub-repo
   `picoclaw-app-<jobb-id>`, committar exakt den verifierade källkoden
   och skickar repo- och commitlänk till Slack. Kodcontainern får aldrig GitHub-token.
6. Pico meddelar när kontrollerna passerat. `deploy` godkänner exakt dessa
   artefakter. Static får en egen Nginx-webroot utan container eller databas.
   Fullstack får en egen Compose-stack, Postgres-volym, lösenord och localhost-port.
   Båda får separat TLS-vhost.
7. Pico skickar URL efter verifierat serverkvitto. Använd befintlig
   preview-inloggning och granska appens verkliga beteende i webbläsaren.

Detta deployar först en **skyddad preview** på `app-<jobb-id>.marcusasplund.com`.
När previewn är granskad kan ägaren skriva `release <subdomän>`, till exempel
`release todo`. Då skapas `todo.marcusasplund.com` mot samma verifierade
frontend och, för fullstack, samma image, databas och app-port. Previewn ligger kvar. Vidareändring av samma app och
Docker-delete är ännu inte inkopplade. En ny byggbeskrivning skapar en ny
app. Högst tio genererade appar kan reserveras innan administratören behöver
se över kapaciteten. Namnet `Demo`/`:demo` inne i releasen är grundens interna
modulnamn; varje projekt kör isolerat och använder ingen Duchat-kod eller data.

`build demo` behåller det tidigare ombygget av den granskade räknardemon.
`build static app-name description` använder den äldre statiska generatorn.
Gamla statiska jobb kan fortsatt styras i sina trådar. Skriv kommandon som
vanlig text, utan kodformatering. Huvudkommandona är `build`, `approve`,
`status`, `stop`, `deploy`, `release <subdomain>`, `continue` och `details`. De äldre
svenska kommandona fungerar fortsatt som alias.

Om ett genererat bygge når modellens budget- eller anropstak kan ägaren skriva
`continue`. Varje manuellt godkännande ger högst 20 ytterligare modellanrop,
varav högst 10 eskalerade, och $5 extra konservativ budgetreserv. Historisk
användning och faktisk uppskattad kostnad nollställs inte. Högst tre sådana
fortsättningar tillåts per jobb.

## Installation

På Macen, från picoclaw-repot:

```sh
python3 scripts/projectflow/package.py
scp /private/tmp/picoclaw-projectflow.tar.gz marcus2@macmini2:
```

På macmini2:

```sh
tar -xzf ~/picoclaw-projectflow.tar.gz -C ~/
scp -i ~/.ssh/picoclaw_deploy -o IdentitiesOnly=yes -P 48039 \
  ~/picoclaw-projectflow.tar.gz picodeploy@100.74.148.93:
```

På Lenovo som `marcus`:

```sh
sudo install -d -m 0700 /root/picoclaw-projectflow-installer
sudo tar -xzf /home/picodeploy/picoclaw-projectflow.tar.gz \
  -C /root/picoclaw-projectflow-installer
sudo bash /root/picoclaw-projectflow-installer/projectflow/install-lenovo.sh
```

Installeraren installerar rootägd kod och två separata no-argument-hjälpare:
`picoclaw-demo-deploy` för den gamla demon och `picoclaw-app-deploy` för nya
appar. Den senare tillåts genom `/etc/sudoers.d/picoclaw-app-deploy`. Den
accepterar endast validerat jobb-ID och hashbundna artefakter, aldrig inkommande
Compose, Nginx, shell-kommandon eller fritt valda domäner. Installationen
skapar ingen app och ändrar inga befintliga produktionsstackar.

Därefter på macmini2:

```sh
python3 ~/projectflow/install-macmini2.py
```

Kräver befintlig fungerande demo, dess manuella godkända byggrapporter,
`~/.local/bin/staticflow-llm`, Docker och Python 3.11+. Kontrollerar fjärrhjälparna,
kopierar kod, skills och tom grund, tar konfigurationsbackup och startar om
`picoclaw-slack` samt `picoclaw-projectflow`. Den vanliga agentens `tools.exec`
ska fortsatt vara avstängd. LLM-hjälparen använder befintligt modellval i den
temporära Slack-konfigurationen; nycklar skickas aldrig till byggcontainrarna.

## Beständighet och isolering

SQLite binder jobb och godkännanden till ägare, kanal, tråd och aktuella hashvärden.
Planen inkluderar den frysta grunden/skillsens hash. Byggmanifestet inkluderar
genererad källhash, image-ID och frontend-/arkivhashar. Dubbla Slack-event
skapar inte dubbelt arbete. En worker kör en fas i taget under processlås.
Avbruten planering/byggning får inte publicera ett sent resultat.

Omstart markerar pågående arbete `interrupted`. Deploy upprepas aldrig
automatiskt. Ett failed deploy-jobb med artefakter kan efter felsökning få ett
nytt manuellt `deploy`-godkännande. Servern returnerar befintligt kvitto för
samma lyckade jobb eller blockerar på sin pending-journal. Ta inte bort en
journal utan att kontrollera stack, databas, vhost och kvitto.

Apphjälparen vägrar adoptera befintliga filer, Nginx-hosts eller Compose-resurser.
Den reserverar en egen port 4200–4299, bunden endast på localhost. Postgres har
ingen publicerad port och kör på projektets interna nät. Appen har också en
web-brygga för Docker-portpublicering; den har därmed utgående nätåtkomst.
App/migration kör som uid 1000 med readonly-root, borttagna capabilities och
minnes-/CPU-/processgränser. Databasen använder en egen volym och egna nycklar.

Vid misslyckad nydeploy tas endast den nya routen bort och appcontainern
stoppas. Databas, artefakter, portreservation och journal behålls för granskning.
Den gamla demohjälparen behåller sin backup-/återställningslogik för demo-uppdateringar.

Det här är en personlig kodgenerator för ägarens instruktioner. Dockergränserna
är inte en VM-säkerhetsgräns för fientlig kod. Dependencies hämtas med nätverk;
genererad appkod kompileras/testas efter nätfrånkoppling och release-steget
använder `RUN --network=none`. BuildKit har fortfarande inga explicita
CPU-/minnesgränser i dessa byggare. Byggloggar, caches, källarkiv och images
saknar automatisk gallring. Workern har användarens Docker-klientbehörighet.
Lenovo verifierar controller-godkännandets hash, inte en egen Slack-signatur;
SSH-nyckelns innehavare kan använda den begränsade hjälparen direkt.

Tester som modellen själv skriver visar att testfallen passerar, inte att
alla mänskliga krav är uppfyllda. Release-starttestet verifierar dessutom
fast DB-health, och servern kontrollerar image-ID, TLS och preview-auth.
Webbläsargranskning efter deploy återstår alltid.

## Felsökning

```sh
journalctl --user -u picoclaw-projectflow -n 80 --no-pager
```

Macmini2: `~/.picoclaw/projectflow/state/<jobb-id>/worker.log`, fryst
`generation-bundle.json`, genererad `frontend/` och `backend/`, källarkiv,
`generated-sources.json` och `build-run-N/attempt-1` … `attempt-3` med
byggloggar/rapporter. Varje manuellt omförsök behåller tidigare körning separat.

Lenovo: `/var/lib/picoclaw-app-deploy/deploy.log` och `<jobb-id>/pending.json`,
`reservation.json`, `receipt.json`. Runtimekonfiguration och env ligger rootägt
i `/opt/picoclaw-generated/<jobb-id>`; frontend i `/var/www/picoclaw-generated`.
Den gamla demofelsökningen ligger kvar under `/var/lib/picoclaw-demo-deploy`.

Stoppa workern med `systemctl --user disable --now picoclaw-projectflow`.
Ta bort respektive sudoers-fil för att stänga deployvägen. Detta raderar inga
publicerade appar eller databaser.

## Lokal verifiering

```sh
python3 -m unittest discover -s scripts/projectflow -p 'test_*.py'
python3 -m unittest discover -s scripts/projectbuild -p 'test_*.py'
```

Tester täcker approvals, fria beskrivningar, frysta instruktioner, otillåtna
filändringar, begränsade rättningsförsök, separata appresurser, feljournal,
certifikatfel, idempotenta kvitton och det gamla demoflödet. Externa
LLM-/Docker-/Slack-/Lenovo-anrop är simulerade i dessa tester. Första riktiga
acceptanstestet efter installation är `bygg en todoapp med db`.
