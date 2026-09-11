# Fristående Solid/Phoenix-demo på Lenovo

Manuellt installationspaket för den verifierade `demo`-imagen, inte Duchat.
Fasta egna resurser:

- Host `preview-demo.marcusasplund.com`, backend `127.0.0.1:4188`.
- Compose-projekt `picoclaw-demo-preview` med egen Postgres och namngiven datavolym.
- Rootägd konfiguration `/opt/picoclaw-demo-preview`, envfiler mode 0600.
- Frontend `/var/www/picoclaw-demo-preview/<artifact-sha256>`.
- Nginx-filer `sites-available/picoclaw-demo-preview` och motsvarande symlink.
- Logg `/var/log/picoclaw-demo-preview.log`, kvitto `receipt.json` i konfigurationskatalogen.

## Export på macmini2

```sh
python3 ~/demo-preview/export.py \
  ~/picoclaw-builds/demo-release-001/report.json \
  ~/picoclaw-builds/demo-solid-001/report.json \
  ~/demo-image.tar.gz
```

Exporterar exakt verifierat image-ID och skapar `~/demo-frontend.json` från
Solid-byggets `dist`. Kontrollerar passed-rapporter och frontens faktiska filhash.
Ingen ombyggnad. Överför imagearkiv, frontend-JSON och installationspaket till
Lenovo via befintliga `picodeploy`-nyckeln. Dessa rapportkontroller är lokala,
inte signerade Slack-godkännanden.

## Installation på Lenovo

```sh
sudo install -d -m 0700 /root/demo-preview-installer
sudo tar -xzf /home/picodeploy/demo-preview.tar.gz -C /root/demo-preview-installer
sudo python3 /root/demo-preview-installer/demo-preview/install.py \
  /home/picodeploy/demo-image.tar.gz /home/picodeploy/demo-frontend.json
```

Kräver Docker Compose v2, Nginx, Certbot, curl, wildcard-DNS och befintlig
`/etc/nginx/picoclaw-preview.htpasswd`. Använder samma preview-inloggning.
Befintlig Certbot-renewal-hook ska fortsätta ladda om Nginx efter förnyelse.
Ingen sudoers-regel, Dockergrupp eller agentbehörighet ändras.

Appen ansluter till ett eget vanligt bridge-nätverk för portpublicering och ett
internt nätverk för databasen. DB och migrationstjänst har endast internt
nätverk. Appen får därmed utgående nätverksåtkomst; detta är inte en sandbox för
obetrodd kod. Endast localhost-porten publiceras. Detta undviker felet med
utebliven portpublicering på enbart internt nätverk i förra teststacken.

Installeraren kontrollerar kollisioner, image-ID och arkitektur. Den skapar egna
nycklar och kör `Demo.Release.migrate()`, startar appen, kontrollerar HTTP-status
samt räknarvärde från databasen, och aktiverar därefter Nginx/Certbot.
Både fronten och `/api/` skyddas av Basic Auth. Headern tas bort före backend,
som i den här demoappen inte använder Bearer-auth. Appen saknar egen auth och
är endast avsedd som skyddad demo med testdata.

Kontrollera i webbläsaren: logga in, klicka **Öka med ett**, ladda om sidan och
kontrollera samma värde. Verifiera därefter beständighet genom att starta om
bara demoappen och ladda om sidan:

```sh
sudo docker compose -f /opt/picoclaw-demo-preview/compose.json restart app
```

## Fel/återstart

Nginx-konfigurationen för denna host återställs vid HTTPS-fel. DB/data och
localhost-app kan finnas kvar efter fel. Migrationer återställs inte automatiskt.
Installationen kan återköras för samma image och frontendhash när dess
konfigurationsfiler är färdigskapade; nycklar och data återanvänds. Avbruten första
konfigurationsskrivning kräver granskning. Ingen generell update/deletion finns.
Inga backups är konfigurerade: använd bara testdata.

Stoppa endast demon utan att radera datavolymen:

```sh
sudo docker compose --project-name picoclaw-demo-preview \
  -f /opt/picoclaw-demo-preview/compose.json down
```

Nginx står då kvar och API:t svarar med gatewayfel efter inloggning. Kör inte
`down -v` eller generell prune. Gamla `picoclaw-phoenix-preview` städas inte av
installationen, och detta är ännu inte kopplat till Slack-deploy eller delete.

Lokala tester: `python3 -m unittest discover -s scripts/demo-preview -v`.
Docker/Nginx/Certbot och autentiserat browserflöde återstår att verifiera på Lenovo.
