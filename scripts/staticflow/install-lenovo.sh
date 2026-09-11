#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ "$(id -u)" != 0 ]; then echo 'Run with sudo bash install-lenovo.sh'; exit 1; fi
for command in python3 nginx certbot curl htpasswd visudo; do
 command -v "$command" >/dev/null || { echo "Missing command: $command"; exit 1; }
done
cert_email='rootfood@gmail.com'
python3 - "$cert_email" <<'PY'
import json,sys
from pathlib import Path
email=sys.argv[1]
if '@' not in email or any(c.isspace() for c in email): raise SystemExit('Invalid email')
Path('/etc/picoclaw-static.json').write_text(json.dumps({'domain':'marcusasplund.com','email':email}))
PY
chmod 600 /etc/picoclaw-static.json
install -d -o root -g root -m 755 /var/www/picoclaw-static /var/www/picoclaw-acme
install -o root -g root -m 755 remote.py /usr/local/sbin/picoclaw-static-site
if [ ! -f /etc/nginx/picoclaw-preview.htpasswd ]; then
 htpasswd -B -c /etc/nginx/picoclaw-preview.htpasswd marcus
fi
chown root:www-data /etc/nginx/picoclaw-preview.htpasswd
chmod 640 /etc/nginx/picoclaw-preview.htpasswd
install -d -o root -g root -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/picoclaw-nginx <<'EOF'
#!/bin/sh
/usr/sbin/nginx -t && /usr/bin/systemctl reload nginx
EOF
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/picoclaw-nginx
sudoers_tmp=$(mktemp)
trap 'rm -f "$sudoers_tmp"' EXIT
printf '%s\n' 'picodeploy ALL=(root) NOPASSWD: /usr/local/sbin/picoclaw-static-site ""' > "$sudoers_tmp"
visudo -cf "$sudoers_tmp"
install -o root -g root -m 440 "$sudoers_tmp" /etc/sudoers.d/picoclaw-static
printf '%s\n' 'Installed. Existing Nginx sites were not modified. Preview login: marcus / your chosen password.'
