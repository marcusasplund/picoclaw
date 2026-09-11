# Underlag till Claude: återanvänd idéer från Pico-pipelinen

## Uppdrag

Vi bygger en liknande agentdriven pipeline på jobbet. Detta PicoClaw-repo ligger bredvid jobbrepot och ska användas som konkret referens, framför allt för Slack-presentation, statusuppdateringar och beständig jobbhantering.

Börja med att läsa jobbrepots instruktioner och identifiera dess befintliga pipeline. Jämför sedan med filerna nedan och föreslå små, konkreta förbättringar. Den här filen är ett granskningsunderlag; genomför de ändringar som användaren ber om i jobbrepot. Pico-repot är referensmaterial.

Alla sökvägar nedan är relativa till Pico-repots rot. Hitta repot bland grannkatalogerna om dess namn eller placering skiljer sig. Anpassa idéerna till jobbets språk, ramverk, autentisering och driftmiljö.

## Läs i denna ordning

### 1. Slack-presentation — högst prioritet

Läs `scripts/projectflow/dispatch.py`, särskilt:

- `duration()`, `slack_link()` och `model_name()`: små presentationshjälpare.
- `footer()` och `append_footer()`: tid, uppskattad kostnad, modellanrop och jobb-ID.
- `build_status()`: byggsteg med väntar/pågår/klart/fel, tidsåtgång och aktuell aktivitet.
- `describe()`: meddelanden för plan, kö, bygge, granskning, preview, release och fel, med nästa möjliga kommando.
- `details()`: tekniska detaljer som kan visas separat från normal status.

Detta är direkt formaterad Slack-text, inte en Block Kit-implementation. Funktionerna delar fil med kommandorouting och är därför lämpliga att extrahera och anpassa, snarare än att kopiera hela filen.

Önskvärd struktur i jobbpipelinen: rena funktioner som tar strukturerad jobbstatus och returnerar meddelanden. Håll Slack-anrop och affärslogik utanför formateringen. Anpassa tekniknamn, domäner, kommandon och budgettexter. Hantera escaping av dynamisk text och länkar; referensens enkla `slack_link()` är ingen komplett validering.

### 2. Uppdatera status utan att fylla tråden med meddelanden

Läs `notify()` i `scripts/projectflow/worker.py` tillsammans med tabellerna `notifications` och `slack_status` i `scripts/projectflow/jobs.py`.

Mönster att undersöka:

- Spara kanal, tråd och meddelandets timestamp för senare uppdatering.
- Använd `chat.update` för pågående status när ett statusmeddelande finns.
- Begränsa uppdateringsfrekvensen; Pico har en spärr på tre sekunder.
- Spara notifieringar beständigt och försök igen med ökande väntetid vid leveransfel.
- Hoppa över notifieringar vars jobbstatus redan har passerats, så att gamla godkännandefrågor inte skickas senare.

Återanvänd principerna med jobbets befintliga Slack-klient och lagring. Leveransen ska inte antas vara exakt en gång: granska bland annat fallet där Slack tar emot meddelandet men processen avbryts innan kvittot sparas. Anpassa hantering av rate limits och fel till er klient.

### 3. Beständiga jobb och godkännanden

Läs `scripts/projectflow/jobs.py` och `scripts/projectflow/test_jobs.py`.

Viktiga delar:

- `once()`: deduplicering av inkommande event med ett sparat resultat.
- `scoped()` och `authorize()`: koppling till användare, kanal och tråd.
- `approve()` och `digest()`: godkännanden knutna till en viss plan eller artefakt.
- `claim()` och `finish()`: ta ett jobb och knyt resultatet till rätt körning.
- `cancel()` och `recover()`: avbrott och återhämtning efter omstart.

Pico använder SQLite och en personlig ägarpolicy. På jobbet ska dessa anpassas till befintlig databas, användar-/teambehörighet och eventuell parallell körning. Kontroll av användar-ID här ersätter inte verifiering av inkommande Slack-trafik i transportlagret.

### 4. Agentkörning, kostnad och verifiering — om relevant

- `scripts/projectflow/CODEAGENT.md`: läs först för en överblick över kodagentflödet.
- `scripts/projectflow/codeagent.py`: agentens arbetsloop, terminalkörning i Docker, avbrottskontroll, progress och export av projektfiler.
- `scripts/projectflow/worker.py`, särskilt `build_with_agent()`: hur kodarbete kopplas till kontroller och byggartefakter.
- `scripts/projectflow/model_policy.py`: bokföring av tokens/kostnad, anropstak, eskalering och begränsad fortsatt budget.

Återanvänd strukturen där den hjälper. Modell-ID:n, priser, providerspecifik konfiguration och eskaleringsregler i referensen är inte rekommendationer för jobbpipelinen. Dockerupplägget behöver bedömas mot jobbets egen körmiljö och tillitsmodell.

### 5. Markdown till Slack — valfri separat del

Om modellen returnerar vanlig Markdown, läs:

- `pkg/channels/slack_webhook/convert.go`
- `pkg/channels/slack_webhook/convert_test.go`

Här finns Go-kod för konvertering av bland annat fetstil, länkar, rubriker och tabeller till Slack-format, med skydd av kodblock och inline-kod under konverteringen. Använd testerna som exempel om jobbpipelinen har ett annat språk. Betrakta detta som en begränsad konverterare, inte en fullständig Markdown-parser.

## Tester att använda som inspiration

- `scripts/projectflow/test_dispatch.py`: kommandorouting och separation mellan godkännande och körning.
- `scripts/projectflow/test_jobs.py`: jobbtillstånd, event, godkännanden och återhämtning.
- `scripts/projectflow/test_worker.py`: workerbeteende och felhantering.
- `pkg/channels/slack_webhook/convert_test.go`: exempel på textkonvertering.

Välj relevanta beteenden att testa i jobbets implementation. Prioritera dubbla event, omstart mitt i ett jobb, avbrutet jobb, inaktuellt godkännande, Slack-leveransfel och att statusen motsvarar verkligt utförda steg.

## Delar som kräver större anpassning

- `install-macmini2.py`, `install-lenovo.sh`, `remote.py` och `remote_apps.py` är tätt kopplade till personliga servrar, SSH, domäner och deploykonventioner.
- `common.py` innehåller miljökopplingar som importerande filer kan vara beroende av.
- `generate.py` och delar av `README.md` beskriver även ett äldre generatorflöde. Använd `CODEAGENT.md` och aktuella anrop i koden för att förstå vad som körs.
- `generation-skills/` och `workspace/skills/` innehåller frontend-/backendinstruktioner under omprövning: långa texter, referenser till personliga projekt och historiska flödesbegränsningar. Använd dem inte som färdiga riktlinjer för jobbet.
- `templates/application/` är en befintlig Solid/Phoenix-grund, inte ett beslut om jobbets stack. Diskussionen om React, lokala frontendmallar och Phoenix-generatorn är ännu inget genomfört stackbyte.

## Förväntad första återkoppling

Efter granskningen, återkom kort med:

1. Vad jobbpipelinen redan har som motsvarar referensen.
2. De tre mest värdefulla förbättringarna, med konkreta mål- och referensfiler.
3. Vad som kan extraheras direkt och vad som behöver anpassas.
4. En liten första ändring och hur dess beteende kan verifieras.

Om användaren redan bett om implementation, fortsätt inom den omfattningen. Föredra att först förbättra Slack-presentation och statusleverans framför att byta ut hela pipelinen.
