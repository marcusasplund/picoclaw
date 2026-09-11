# Manuell Phoenix-preview på Lenovo

Fast testmål: `preview-phoenix.marcusasplund.com`, Compose-projekt
`picoclaw-phoenix-preview`, konfiguration under `/opt/picoclaw-phoenix-preview`,
backend på `127.0.0.1:4187`, egen Postgres och beständig Docker-volym.
Installeraren accepterar bara det image-ID som användaren verifierade i
`phoenix-release-002`. Det är ingen generell deploybehörighet för agenten.

## Överföring

På Macen: kopiera paketet `phoenix-preview.tar.gz` till macmini2.
På macmini2, packa upp och kör:

```sh
python3 ~/phoenix-preview/export.py \
  ~/picoclaw-builds/phoenix-release-002/report.json \
  ~/phoenix-preview-image.tar.gz
scp -i ~/.ssh/picoclaw_deploy -o IdentitiesOnly=yes -P 48039 \
  ~/phoenix-preview-image.tar.gz ~/phoenix-preview.tar.gz \
  picodeploy@100.74.148.93:
```

Exporten kontrollerar godkänd rapport och release-/migrations-/HTTP-kontroller.
Imagen byggs inte om. Den är stor; export och överföring kan ta flera minuter
och kräver ledigt diskutrymme på båda maskinerna.

På Lenovo som administratören `marcus`:

```sh
sudo install -d -m 0700 /root/phoenix-preview-installer
sudo tar -xzf /home/picodeploy/phoenix-preview.tar.gz -C /root/phoenix-preview-installer
sudo python3 /root/phoenix-preview-installer/phoenix-preview/install.py \
  /home/picodeploy/phoenix-preview-image.tar.gz
```

Detta kräver befintlig Docker Compose v2, Nginx, Certbot, curl, wildcard-DNS och
`/etc/nginx/picoclaw-preview.htpasswd` från tidigare staticflow-installation.
Befintlig Certbot-renewal-hook måste fortsätta ladda om Nginx efter förnyelse.
Inga nya sudoers-regler eller Dockergruppsmedlemskap skapas.

## Resultat och kontroll

Installeraren kontrollerar kollisioner, image-ID och arkitektur. Den låser även
Postgres till det lokalt hämtade image-ID:t, genererar nya nycklar i rootägda
0600-envfiler och kör release-migrationer mot den egna databasen. Testdata ligger
kvar vid omstart och omskapande av containrar. Ingen automatisk backup finns än;
använd endast testdata i denna preview.

Appen och databasen har ett eget internt nätverk. Appen exponeras endast på
localhost. Databasen har ingen publicerad port. Appen kör som UID 1000 med
skrivskyddat rootfilsystem, resursgränser och utan capabilities. Databasen använder
standardimagets init/privilegienedtrappning och en egen namngiven volym.
Containerloggar roteras; installationsloggen finns i
`/var/log/picoclaw-phoenix-preview.log`.

Nginx använder befintlig preview-inloggning. HTTP visar ingen app; HTTPS kräver
Basic Auth. Basic Auth-headern tas bort innan anropet når backend. Detta första
API-previewtest stödjer därför inte backendens Bearer-auth via samma header.
HTTP-kontrollen testar `/api/`; Duchat har ingen frontend på `/`.

Efter lyckad installation finns `/opt/picoclaw-phoenix-preview/receipt.json` med
image-ID och URL. Öppna `https://preview-phoenix.marcusasplund.com/api/`, logga in
med befintliga preview-uppgifter och kontrollera `{"status":"ok"}`. Installeraren
verifierar backend direkt och att rätt TLS-host ger 401 utan inloggning. Det
autentiserade browseranropet återstår för användaren.

## Fel och återupptagning

Vid Nginx/Certbot-fel återställs bara denna hosts tidigare konfiguration. App och
databas kan då finnas kvar på localhost. Vid migrationsfel stoppas installationen;
redan genomförda migrationer rullas inte tillbaka. Inspectera installationsloggen.
Samma installationskommando kan köras igen för samma image och färdigskapade
konfigurationsfiler; det behåller nycklar och data. Om första körningen avbröts
mitt i skapandet av konfigurationen måste de filerna granskas före fortsatt körning.

För att stoppa endast denna stack utan att radera dess datavolym:

```sh
sudo docker compose --project-name picoclaw-phoenix-preview \
  -f /opt/picoclaw-phoenix-preview/compose.json down
```

Nginx-host och certifikat finns då kvar, och inloggade besökare får gatewayfel.
Kör inte `down -v` eller generell Docker-prune. Detta är inte kopplat till Slacks
`delete`, som fortfarande bara hanterar statiska appar.

Lokalt verifierat med `python3 -m unittest discover -s scripts/phoenix-preview -v`.
Riktig Docker/Nginx/Certbot-installation måste verifieras på Lenovo.

Referenser: https://docs.docker.com/reference/compose-file/services/ och
https://nginx.org/en/docs/http/ngx_http_auth_basic_module.html
