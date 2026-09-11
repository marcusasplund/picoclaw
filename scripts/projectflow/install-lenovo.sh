#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ "$(id -u)" != 0 ]; then echo 'Kör med sudo bash install-lenovo.sh'; exit 1; fi
for command in python3 docker nginx certbot curl visudo; do command -v "$command" >/dev/null; done
test -f /opt/picoclaw-demo-preview/compose.json
test -f /opt/picoclaw-demo-preview/frontend-hash
test -f /etc/nginx/sites-enabled/picoclaw-demo-preview
python3 -m unittest discover -s . -p 'test_remote.py'
install -d -o root -g root -m 755 /usr/local/lib/picoclaw-projectflow /usr/local/lib/picoclaw-projectflow/demo-preview
install -o root -g root -m 644 remote.py remote_apps.py jobs.py /usr/local/lib/picoclaw-projectflow/
install -o root -g root -m 644 demo-preview/install.py demo-preview/frontend.py /usr/local/lib/picoclaw-projectflow/demo-preview/
install -d -o root -g root -m 700 /var/lib/picoclaw-demo-deploy
install -d -o picodeploy -g picodeploy -m 700 /home/picodeploy/projectflow-incoming
cat > /usr/local/sbin/picoclaw-demo-deploy <<'EOF'
#!/bin/sh
exec /usr/bin/python3 -I /usr/local/lib/picoclaw-projectflow/remote.py
EOF
chown root:root /usr/local/sbin/picoclaw-demo-deploy
chmod 755 /usr/local/sbin/picoclaw-demo-deploy
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
printf '%s\n' 'picodeploy ALL=(root) NOPASSWD: /usr/local/sbin/picoclaw-demo-deploy ""' > "$tmp"
visudo -cf "$tmp"
install -o root -g root -m 440 "$tmp" /etc/sudoers.d/picoclaw-demo-deploy
printf '%s\n' '{"mode":"status"}' | sudo -u picodeploy sudo -n /usr/local/sbin/picoclaw-demo-deploy

python3 -m unittest discover -s . -p 'test_remote_apps.py'
install -d -o root -g root -m 700 /var/lib/picoclaw-app-deploy /opt/picoclaw-generated
install -d -o root -g root -m 755 /var/www/picoclaw-generated
cat > /usr/local/sbin/picoclaw-app-deploy <<'EOF'
#!/bin/sh
exec /usr/bin/python3 -I /usr/local/lib/picoclaw-projectflow/remote_apps.py
EOF
chown root:root /usr/local/sbin/picoclaw-app-deploy
chmod 755 /usr/local/sbin/picoclaw-app-deploy
printf '%s\n' 'picodeploy ALL=(root) NOPASSWD: /usr/local/sbin/picoclaw-app-deploy ""' > "$tmp"
visudo -cf "$tmp"
install -o root -g root -m 440 "$tmp" /etc/sudoers.d/picoclaw-app-deploy
printf '%s\n' '{"mode":"status","app":"000000000000"}' | sudo -u picodeploy sudo -n /usr/local/sbin/picoclaw-app-deploy
