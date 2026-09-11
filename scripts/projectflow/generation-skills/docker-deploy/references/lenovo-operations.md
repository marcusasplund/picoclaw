# Lenovo: miljö och gränser

Sammanställning från användarens uppgifter och lokalt granskad kod, 2026-09-06. Kontrollera aktuellt tillstånd innan arbete på en server. Detta dokument innehåller inga hemligheter och skapar inga behörigheter.

## Bekräftad miljö

- macmini2 kör Omarchy/Linux. PicoClaw ligger i `~/code/picoclaw`; installerad binär finns i `~/.local/bin/picoclaw`.
- Slack-gatewayen kör som systemd-användartjänsten `picoclaw-slack` för `marcus2`. Den separata arbetsytan är `~/.picoclaw/slack-workspace`.
- Lenovo kör Debian Server, Docker och hostinstallerad Nginx. Flera andra sajter kör där; behandla deras vhosts, portar, nätverk och data som befintliga resurser.
- Den verifierade SSH-vägen är port `48039` på `100.74.148.93`. Från macmini2 finns en separat deploynyckel `~/.ssh/picoclaw_deploy` för användaren `picodeploy`. Den publika adressen på port 22 var inte den fungerande vägen.
- Administratörskontot är `marcus`; sudo kräver lösenord. `picodeploy` har en begränsad lösenordsfri sudo-regel för den statiska hjälparen, utan kommandoradsargument. Ingen Docker-behörighet för kontot har verifierats.
- Simply hanterar DNS. Wildcard-A för `*.marcusasplund.com` lades till mot `90.231.3.121` och verifierades från Lenovo. Separata poster finns för domänroten, `www` och `folkminnen`.
- Certbot-timern är aktiv enligt användarens kontroll. Den statiska installationen använder `rootfood@gmail.com` som certifikatkontakt.

Adresser och användarnamn är befintliga mål i denna miljö, inte standardvärden att skriva in i varje ny apps källkod eller image.

## Vad den statiska lösningen gör

Projektets `scripts/staticflow/` och `pkg/channels/slack/staticflow.go` implementerar ett första, separat flöde:

- Slack-ägare, tråd, status och versionshash kontrolleras i kod.
- `plan-ok` godkänner planen; `deploy` godkänner den reviewade statiska artefakten.
- Bygget genererar endast `index.html`, `style.css` och `app.js`, utan hostverktyg.
- `preview-app-…` får skyddad preview; `app-…` är den publika hosten.
- Rootägd `/usr/local/sbin/picoclaw-static-site` skriver statiska releaser under `/var/www/picoclaw-static`, skapar egna Nginx-konfigurationer och använder `/var/www/picoclaw-acme` för webroot-verifiering.
- Previewlösenord ligger i `/etc/nginx/picoclaw-preview.htpasswd`; de ska inte hämtas eller återges av agenten.
- `delete`/`delete-ok` är implementerat för att ta ned statiska app-/previewhosts med HTTP 410 och bevara artefakter/certifikat. Det är inte ett kommando för att radera Docker-volymer.

Dessa egenskaper är inte bevis på att någon Dockerbyggare, Compose-runner eller containerbaserad preview redan finns. Skills måste kopplas till den framtida projektbyggaren; att installera SKILL.md ändrar inte verktygsstödet.

## Referensen Duchat

Duchats backend kör som en Phoenix-release i Docker. Den granskade Compose-filen har fast containernamn, port `4000:4000` och det externa nätverket `duchat-net`. Den deklarerar inte databasen, även om användarens containerlista visar en separat `duchat-db`.

Kopiera därför inte Compose-filen som en fristående mall för nya appar. En ny stack behöver eget projektnamn, definierade beroenden och beständig datavolym. Duchats befintliga containrar eller nätverk ska inte kopplas om för att starta ett annat projekt.

Dess release-modul kan köra migreringar, men det granskade deployscriptet bygger och återskapar backend utan att anropa migrering eller automatisk hälsokontroll. Den framtida deployfunktionen behöver göra dessa steg explicita.

## Viktiga lärdomar från previewfelet

Ett previewcertifikat utfärdades, men ett misslyckat publiceringsförsök återställde Nginx-konfigurationen. Ett efterföljande SNI-test mot previewhosten visade certifikatet för `duchat.se`.

Lärdomen är att verifiera vad rätt host faktiskt serverar efter reload och återställning. Den statiska hjälparen fick begränsade återförsök för hälsokontrollen, explicit lokal adress för HTTPS-test och egen fellogg. Certifikatvarningar ska utredas genom aktiv vhost/SNI, inte döljas genom att stänga av TLS-verifiering.

## Framtida Docker-runner: krav före aktivering

Detta är designkrav, inte installerade funktioner:

- Håll byggmiljön för modellgenererad kod skild från hostens Docker-socket, deploynycklar och andra appars data.
- En rootägd wrapper som accepterar godtycklig Compose från agenten ger inte i sig en begränsad behörighet: Compose kan begära hostmounts, privileged-läge och annan hoståtkomst. Begränsa och granska tjänstedefinitioner och deployparametrar i den framtida implementationen.
- Registrera appägarskap, Compose-projekt, subdomän, tilldelade portar, datavolymer och releaseversion. Använd den registreringen vid uppdatering och nedtagning.
- Knyt godkännandet till images och deployspecifikation; ett kort Slack-kommando ska inte ge rätt att ändra godtyckliga serverresurser.
- Välj först ett litet, fungerande Solid/Phoenix/Postgres-projekt och verifiera installation, migrering, preview, uppdatering och återställning innan bredare autonom användning.
