---
name: docker-deploy
description: "Förbered och genomför godkänd Docker Compose-driftsättning av exempelvis SolidJS/Phoenix/Postgres-appar på Lenovos Debian-server bakom Nginx och Certbot. Hanterar imageversioner, runtime-hemligheter, migreringar, preview, hälsokontroller och återställning. Använd för container- och deployarbete, inte för vanlig frontend- eller backendutveckling."
---

# Docker-deploy för PicoClaw

Gör en app reproducerbart körbar och publicera den genom det godkända deployflödet när det finns verktygsstöd. Läs [Lenovos miljö och gränser](references/lenovo-operations.md) före arbete mot servern. Den beskriver bekräftade fakta och vad som ännu inte är implementerat; kontrollera aktuellt tillstånd före mutationer.

## Fastställ vad som ska deployas

- Läs repo-instruktioner, Dockerfiler, Compose-filer, `.dockerignore`, runtimekrav och eventuella release-script. Identifiera tjänster, byggkontexter, migrationer och beständig data.
- Knyt releaseunderlaget till en bestämd kodversion och byggda images. Anteckna image-digests, app-/miljönamn, subdomän, portar, ändrade hemlighetsnamn och migrationsordning. Hemlighetsvärden hör inte hemma i planen eller Slack.
- Bevara befintlig infrastruktur och andra appar. En uppdatering av en app motiverar inte att ändra serverns standard-vhost, delade nätverk eller andra Compose-projekt.
- Återanvänd redan givna godkännanden inom deras scope. I Slack-flödet avser plan-OK byggarbete och preview; publik deploy kräver det separata godkännandet av den reviewade releasen. En ny kod-, image- eller migrationsversion ersätter inte tyst den godkända versionen.

## Gör containrarna reproducerbara

- Använd låsfiler och byggsteg som passar respektive app. Solid/Vite byggs till statiska filer; Phoenix byggs till en release. Vite-devservern är inte produktionsserver.
- Använd flerstegsbyggen när de håller kompilatorer och utvecklingsberoenden borta från runtime. Kontrollera kompatibla OS-/biblioteksversioner mellan Phoenix-build och runner, samt målserverns CPU-arkitektur.
- Kör appprocesser utan root när imagen stöder det. Ge dem de skrivbara kataloger och resurser de faktiskt behöver. Undvik privileged, hostnätverk, hostens rotfilsystem och Docker-socket i applikationscontainrar.
- Exkludera `.env`, privata nycklar, databasdumpningar, lokala beroenden och irrelevanta byggresultat från byggkontexten. Skicka inte hemligheter som vanliga build-args eller COPY-lager.
- Bygg en release en gång och använd samma app-images i review och publik deploy. Lås publiceringen till digests eller motsvarande verifierade lokala image-ID:n; `latest` är inte tillräcklig versionsbindning. Miljöspecifik runtime-konfiguration och data kan skilja sig.

## Compose per app och miljö

- Ange ett explicit, stabilt projektnamn i samtliga Compose-kommandon. Preview och produktion ska ha olika projekt och databasvolymer. Byt inte projektidentitet vid varje release så att appen råkar få en ny tom databas.
- Undvik fasta globala `container_name`, delade externa nätverk och hårdkodad hostport `4000` som standard för alla appar. Inventera och tilldela lediga portar utan att stoppa andra tjänster.
- Låt tjänster nå varandra via Compose-servicenamn och containerportar. Publicera inte Postgres på hosten när bara backend behöver den.
- Bakom hostens Nginx binds nödvändiga HTTP-portar till `127.0.0.1`. Välj uttryckligt om Nginx routar frontend och `/api` till två portar, eller om en intern frontend-proxy routar `/api` vidare till backend.
- Definiera databasens namngivna volym, restartbeteende, relevanta resursgränser och hälsokontroller. `depends_on` ensamt bevisar inte att databasen är redo; kombinera readiness-villkor med appens hantering av tillfälliga anslutningsfel.
- Lägg inte produktionsdata i preview. Seeddata eller uttryckligt godkända, sanerade data används vid review.

## Runtime-hemligheter

- Versionshantera variabelnamn och ofarliga exempel. Spara verkliga värden utanför repo och byggkontext med begränsade filrättigheter.
- Skilj Compose-interpolation via `.env`/`--env-file` från miljövariabler som faktiskt skickas till en container via `environment` eller `env_file`.
- Compose secrets monteras som filer till valda tjänster. Anta inte att appen automatiskt läser dem: Phoenix behöver stöd i runtime-konfigurationen för den valda filreferensen eller miljövariabeln. Vanlig filbaserad Compose-secrets är inte i sig ett krypterat hemlighetsvalv.
- Validera konfiguration med `docker compose ... config --quiet` när värden är inlästa. Undvik att lägga expanderad Compose-konfiguration, container-env eller nyckelfiler i Slack/loggutdrag.

## Migrering och driftsättning

Förbered först konfiguration och kommandon så att releasen går att granska. Anpassa ordningen till appen:

1. Verifiera images, Compose-konfiguration, målprojekt och tidigare release. Säkra relevant databasbackup och en genomförbar återställningsväg före riskfyllda schemaändringar.
2. Starta nödvändiga beroenden och invänta deras readiness med en tidsgräns.
3. Kör release-migreringen som ett uttryckligt, enkelkört steg med rätt image, nätverk och databas. Använd Phoenix-release-script/modul; förutsätt inte att Mix finns i runtime-imagen.
4. Starta appen och kontrollera process, databasberedskap och den centrala API-funktionen. Flytta trafik först när avsedda kontroller fungerar.
5. Validera Nginx-konfigurationen före reload och verifiera sedan den avsedda subdomänen över HTTPS. Vänta begränsat på nya workers; ett lyckat reloadkommando är inte samma sak som ett verifierat HTTP-svar.

Kör inte automatiskt destruktiva migrationer igen efter timeout. Kontrollera först vad som hann genomföras. Om deployverktyget inte kan visa tillståndet: stoppa återförsök och redovisa vad som är osäkert. Undvik obegränsade retry-loopar.

## Nginx, HTTPS och preview

- Använd en separat, namngiven konfiguration per app och miljö. Bevara ACME-challenge-routing när Certbot använder webroot. Lägg till WebSocket-proxy endast när appen faktiskt behöver den.
- Skydda preview inklusive API och eventuella sockets genom den avsedda authlösningen. Ett lösenordsskydd enbart framför HTML lämnar inte automatiskt backend skyddad.
- Kontrollera att host, certifikatets namn och aktiv vhost stämmer. Att en certifikatfil finns på disk bevisar inte att Nginx serverar den.
- Bevara fungerande Certbot-förnyelse och deploy-hook för Nginx. Begär inte nya certifikat i varje byggförsök.
- Kontrollera frontend, ett riktigt API-anrop och relevant databasfunktion. En konstant `/health` eller versionssträng kan verifiera routing men ersätter inte funktionstest.

## Återställning och nedtagning

- Spara tidigare imageversioner och konfiguration före bytet. Återställ appversion/trafik när verifieringen misslyckas och databasschemat är kompatibelt.
- En image-rollback återställer inte databasen. Beskriv separat hur schema/data hanteras; återläs inte backup eller kör destruktiv rollback utan att det ingår i godkänt scope.
- Nedtagning och permanent dataradering är olika operationer. Bevara databasvolymer och byggartefakter vid vanlig nedtagning. Kör inte `down -v`, global prune eller volymradering som städning av ett deployfel.
- För en nedtagen host kan en tydlig 410-respons med rätt certifikat undvika att Nginx faller tillbaka till en annan sajt. Hantera permanent borttagning av data och certifikat separat när det uttryckligen efterfrågas.
- Rapportera slutlig URL, exakt releaseversion, migrationsresultat, utförda kontroller och eventuell återställning. Påstå inte lyckad deploy utifrån enbart containerstatusen `running`.

## Befintliga verktygsgränser

Denna skill tilldelar inte Docker- eller rootbehörighet. Den befintliga hjälparen `/usr/local/sbin/picoclaw-static-site` hanterar enbart statiska filer; använd den inte för Compose och ändra inte dess sudo-policy som en genväg.

Det nuvarande `staticflow`-bygget läser inte automatiskt skills och kan inte bygga Solid/Phoenix-projekt. Ett separat projektbyggsteg och en granskad Docker-deployfunktion återstår. Fram till dess kan du förbereda Dockerfiler, Compose, runtimekrav och verifieringsplan i det godkända projektet; kör och rapportera bara det som tillgängliga verktyg och gällande godkännande medger.

## Officiella referenser

- [Compose i produktion](https://docs.docker.com/compose/how-tos/production/)
- [Projektnamn](https://docs.docker.com/compose/how-tos/project-name/)
- [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/)
- [Tjänster, beroenden och healthchecks](https://docs.docker.com/reference/compose-file/services/)
- [Certbot och förnyelse](https://eff-certbot.readthedocs.io/en/stable/using.html)
