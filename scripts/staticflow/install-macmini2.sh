#!/bin/bash
set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/go/bin:/usr/local/go/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
for command in go make python3 node ssh; do
 command -v "$command" >/dev/null || { echo "Missing command: $command"; exit 1; }
done
cd "$HOME/code/picoclaw"
make build GOTOOLCHAIN=auto
GOTOOLCHAIN=auto go build -tags goolm,stdjson -o build/staticflow-llm ./cmd/staticflow-llm
python3 -m unittest discover -s scripts/staticflow
install -d -m 700 "$HOME/.picoclaw/staticflow" "$HOME/.local/bin"
cp scripts/staticflow/flow.py "$HOME/.picoclaw/staticflow/flow.py"
install -m 755 build/staticflow-llm "$HOME/.local/bin/staticflow-llm"
python3 - <<'PY'
import json,shutil,time
from pathlib import Path
home=Path.home();root=home/'.picoclaw'
p=root/'config.slack.json'
c=json.loads(p.read_text())
shutil.copy2(p,p.with_name(p.name+'.backup-'+str(time.time_ns())))
c['channel_list']['slack']['settings']['static_flow_command']=['/usr/bin/python3',str(root/'staticflow/flow.py'),str(root/'staticflow/settings.json')]
# The ordinary LLM remains a planner; workflow commands invoke a separate tool-free generator.
c['tools']['exec']={'enabled':False}
c['tools']['web']={'enabled':False,'prefer_native':False}
p.write_text(json.dumps(c,indent=2)+'\n')
s={'owner':'U0ALTHQSWSV','state_dir':str(root/'staticflow/state'),
   'llm_command':[str(home/'.local/bin/staticflow-llm')], 'node_binary':shutil.which('node'),
   'ssh_key':str(home/'.ssh/picoclaw_deploy'),'ssh_port':48039,
   'ssh_target':'picodeploy@100.74.148.93','domain':'marcusasplund.com'}
(root/'staticflow/settings.json').write_text(json.dumps(s,indent=2)+'\n')
PY
if [ -f "$HOME/.local/bin/picoclaw" ]; then
 cp -p "$HOME/.local/bin/picoclaw" "$HOME/.local/bin/picoclaw.backup-$(date +%Y%m%d-%H%M%S)"
fi
install -m 755 build/picoclaw "$HOME/.local/bin/picoclaw.next"
mv "$HOME/.local/bin/picoclaw.next" "$HOME/.local/bin/picoclaw"
systemctl --user restart picoclaw-slack
systemctl --user is-active picoclaw-slack
