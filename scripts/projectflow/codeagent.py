"""Pico coding agent: a terminal in a disposable Docker workspace, no host tools."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import time
import uuid

from common import clean_env
from generate import model
from jobs import digest
from phoenix import IMAGE as ELIXIR, POSTGRES, database_args
from solid import IMAGE as NODE, snapshot
from model_policy import ModelPolicy

FULLSTACK_SYSTEM = '''Du är Picos kodagent och arbetar med ett riktigt projekt i /work.
Du har ett terminalverktyg. Returnera ett JSON-objekt per tur:
{"command":"bash-kommandon"} för att läsa/skriva filer, installera paket och köra tester.
{"done":true,"summary":"kort beskrivning"} när ändringarna är klara för byggkontroller.
Du ska ALDRIG returnera ett JSON-objekt med filinnehåll/files. Använd terminalen,
t.ex. cat med en citerad heredoc, för filändringar. Kommandots output och exitkod
kommer tillbaka nästa tur. Ett kommando får ta upp till tio minuter.

Bygg den godkända planen. Börja med att läsa projektet och /work/skills.
Grunden får ändras: filnamn, komponenter, tester, konfiguration och beroenden.
Installera de npm- och Mix-paket som behövs, även riktig Solid Testing Library
och DOM-testmiljö. Läs faktiska fel och dokumentation i paket när det behövs.
Behåll meningsfulla tester för användarens beteenden; ta inte bort eller ersätt
felande tester med triviala tester för att få grönt. Fixa miljön eller koden.
Skills beskriver även tidigare miljöer; följ detta projekts faktiska möjligheter.

Miljö: Node 22, Elixir/OTP, git, curl, python3, byggverktyg. Internet finns för
publika beroenden. /work är beständig mellan dina kommandon, men varje kommando
startar i /work. HOME=/tmp. Tillfällig Postgres på 127.0.0.1:5432, användare/lösen
postgres/postgres. DATABASE_URL pekar på picoclaw_test, MIX_ENV=test.
Värddatorns filer, Docker-socket, SSH-nycklar och LLM/Slack-hemligheter är otillgängliga.

Deploykontrakt: frontend/ byggs med npm och skriver dist/index.html. Behåll
package-lock.json och scripts test:types, lint, test (stöder --run), build.
backend/ är Phoenix med release demo och Demo.Release.migrate(). Behåll mix.lock.
Release läser DATABASE_URL, SECRET_KEY_BASE, PHX_HOST och PORT; GET /api/ ger
HTTP 200 och exakt {"status":"ok"}, och kontrollerar databasen. Resterande routes
och moduler får organiseras fritt. Frontend använder relativa /api/-URL:er.
Login använder säkra sessionscookies, hashar lösenord och kontrollerar rättigheter
i backend. Previewens Basic auth ersätter inte appens egen login.
Installera dependencies och uppdatera låsfiler. Byggkontrollerna hämtar paket innan
kompilering/test körs offline; tester får inte bero på externa tjänster.
Kör relevanta tester när kod är klar. Vid återkoppling från releasebyggaren:
rätta felet i samma projekt och lämna sedan done igen. Ändra inte deploykontraktet.
'''

STATIC_SYSTEM = '''You are Pico's coding agent working in /work. Return one JSON
object per turn: {"command":"bash commands"} to use the terminal, or
{"done":true,"summary":"short summary"} when ready. Edit files through terminal
commands and never return a files object.

Build only the approved SolidJS frontend in frontend/. This is a browser-only
profile: there is no backend/, Elixir, API, database, Docker service, or server
secret. The frontend template is a working application shell, not disposable
scaffolding. First read its README.md, PRODUCT.md, DESIGN.md, App.tsx, Layout.tsx,
AppSidebar.tsx, Header.tsx, ModeToggle.tsx, and routes. Extend the existing shell:
keep Layout as the router root, keep the sidebar and topbar, add pages under
src/routes, and add reusable UI under src/components. Keep App.tsx focused on
route composition; do not put the whole app there or replace the shell with a new
header/sidebar. A user's explicit creative direction may replace the shell only
when the brief says so; record that decision in DESIGN.md. Preserve the theme
switcher and responsive navigation unless the brief explicitly changes them.
Use localStorage only when persistence is requested. Keep package-lock.json and
scripts test:types, lint, test (supporting --run), and build. Production must
create dist/index.html and must not use absolute external API URLs.

Node 22, npm, git, curl, python3, and build tools are available. Public dependency
downloads are allowed. Host files and credentials are unavailable. Work efficiently:
inspect the shell and relevant files together, implement pages as route components,
share data and UI through focused modules, then run all frontend checks together.
Keep meaningful behavior tests. Do not create backend/ or services outside the
approved plan.
'''

# Runs with the image's read-only Node executable. No untrusted tar is extracted.
EXPORT = r'''
const fs = require('node:fs'); const path = require('node:path');
const excluded = new Set(['node_modules','deps','_build','.git','.ssh','.aws',
  '.npmrc','.netrc','.codex','.agents','dist','coverage','.elixir_ls','erl_crash.dump']);
const files = {}; let total = 0;
function walk(dir) {
  for (const name of fs.readdirSync(dir).sort()) {
    if (excluded.has(name) || name.startsWith('.env')) continue;
    const p = path.join(dir,name); const s = fs.lstatSync(p);
    if (s.isSymbolicLink()) throw Error('Source symlink: '+p);
    if (s.isDirectory()) walk(p);
    else if (s.isFile()) {
      total += s.size;
      if (total > 40*1024*1024 || Object.keys(files).length >= 10000) throw Error('Source too large');
      if (/\.(pem|key|p12|pfx)$/.test(name)) throw Error('Credential-like source: '+p);
      files[path.relative('/work',p)] = fs.readFileSync(p).toString('base64');
    } else throw Error('Special source file: '+p);
  }
}
for (const name of __SIDES__) {
  const s = fs.lstatSync('/work/'+name);
  if (!s.isDirectory() || s.isSymbolicLink()) throw Error('Expected project directory');
  walk('/work/'+name);
}
process.stdout.write(JSON.stringify(files));
'''


class CodeAgent:
    def __init__(self, cfg, plan, materials, directory, log, progress, active):
        if digest(materials) != plan['bundle_hash']:
            raise ValueError('Approved scaffold/skills hash mismatch')
        self.routing = ModelPolicy(cfg, plan, directory.parent)
        self.cfg, self.plan, self.materials = {**cfg, '_model_policy': self.routing}, plan, materials
        self.directory, self.log = directory, log
        self.progress, self.active = progress, active
        suffix = uuid.uuid4().hex
        self.container, self.database = 'pico-agent-' + suffix, 'pico-agent-db-' + suffix
        self.started, self.history, self.steps = [], [], 0
        self.command_failures = 0
        self.format_failures = 0
        self.deadline = time.monotonic() + 10800
        self.profile = plan.get('profile', 'fullstack')
        self.sides = ['frontend'] if self.profile == 'static' else ['frontend', 'backend']
        self.system = STATIC_SYSTEM if self.profile == 'static' else FULLSTACK_SYSTEM

    def check(self):
        if not self.active():
            raise ValueError('Jobbet har stoppats; kodagenten avslutas.')
        if time.monotonic() > self.deadline:
            raise ValueError('Kodagentens tidsgräns på tre timmar nåddes.')

    def docker(self, *args, data=None, capture=False, timeout=600):
        self.check()
        result = subprocess.run(['docker', *args], input=data, check=True, timeout=timeout,
                                env=clean_env(), stderr=self.log,
                                stdout=subprocess.PIPE if capture else self.log)
        return result.stdout

    def __enter__(self):
        try:
            self.progress(('Preparing an isolated Node build environment.' if self.profile == 'static' else
                           'Preparing Docker, Node, Elixir and an isolated PostgreSQL database.'), 'environment')
            # System packages are installed only while building this fixed image.
            if self.profile == 'static':
                dockerfile = ('FROM ' + NODE + '\nUSER root\n'
                              'RUN apt-get update && apt-get install -y --no-install-recommends '
                              'bash git curl python3 build-essential ca-certificates '
                              '&& rm -rf /var/lib/apt/lists/*\n')
            else:
                dockerfile = ('FROM ' + NODE + ' AS node\nFROM ' + ELIXIR + '\n'
                              'USER root\nRUN apt-get update && apt-get install -y --no-install-recommends '
                              'bash git curl python3 build-essential ca-certificates && rm -rf /var/lib/apt/lists/*\n'
                              'COPY --from=node /usr/local/bin/node /usr/local/bin/node\n'
                              'COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules\n'
                              'RUN ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm '
                              '&& ln -sf ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx\n')
            tag = 'picoclaw-local/codeagent:' + hashlib.sha256(dockerfile.encode()).hexdigest()[:16]
            context = io.BytesIO()
            with tarfile.open(fileobj=context, mode='w', format=tarfile.USTAR_FORMAT) as tar:
                info = tarfile.TarInfo('Dockerfile')
                info.size = len(dockerfile.encode())
                tar.addfile(info, io.BytesIO(dockerfile.encode()))
            self.docker('build', '--tag', tag, '--label', 'picoclaw.projectbuild=true',
                        '-', data=context.getvalue(), timeout=1800)
            if self.profile == 'fullstack':
                self.docker('pull', POSTGRES)
                self.started.append(self.database)
                self.docker(*database_args(self.database, POSTGRES))
                for attempt in range(30):
                    try:
                        self.docker('exec', self.database, 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres', timeout=5)
                        break
                    except subprocess.CalledProcessError:
                        if attempt == 29:
                            raise
                        time.sleep(2)
            self.started.append(self.container)
            self.docker('run', '--detach', '--name', self.container, '--label', 'picoclaw.projectbuild=true',
                        '--user', '1000:1000', '--read-only', '--cap-drop=ALL',
                        '--security-opt=no-new-privileges', '--pids-limit=512',
                        '--memory=4g', '--memory-swap=4g', '--cpus=2',
                        '--tmpfs', '/work:rw,exec,nosuid,nodev,size=2g,uid=1000,gid=1000',
                        '--tmpfs', '/tmp:rw,exec,nosuid,nodev,size=512m,uid=1000,gid=1000',
                        '--workdir', '/work', '--env', 'HOME=/tmp', '--env', 'CI=true',
                        '--env', 'MIX_ENV=test', '--env', 'ERL_FLAGS=+S 2:2',
                        '--env', 'DATABASE_URL=ecto://postgres:postgres@127.0.0.1/picoclaw_test',
                        *(('--network', 'container:' + self.database) if self.profile == 'fullstack' else ()),
                        tag, 'sleep', '10800')
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as tar:
                for name, content in self.materials.items():
                    if name.startswith('templates/application/'):
                        name = name.removeprefix('templates/application/')
                        if self.profile == 'static' and name.startswith('backend/'):
                            continue
                    elif name.startswith('generation-skills/'):
                        name = 'skills/' + name.removeprefix('generation-skills/')
                    else:
                        continue
                    path = PurePosixPath(name)
                    if path.is_absolute() or '..' in path.parts:
                        raise ValueError('Unsafe scaffold path')
                    value = content.encode()
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = len(value), 0o644
                    tar.addfile(info, io.BytesIO(value))
            self.docker('exec', '-i', self.container, 'tar', '-xf', '-', '-C', '/work', data=buffer.getvalue())
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        for name in reversed(self.started):
            try:
                subprocess.run(['docker', 'rm', '--force', '--volumes', name], timeout=30,
                               stdout=self.log, stderr=self.log, env=clean_env(), check=True)
            except (OSError, subprocess.SubprocessError):
                print('Kontrollera kvarvarande byggcontainer: ' + name, flush=True)

    def shell(self, command):
        lowered = command.lower()
        if 'npm install' in lowered or 'npm ci' in lowered:
            detail = 'Installing npm modules.'
            stage = 'dependencies'
        elif 'mix deps' in lowered:
            detail = 'Installing Elixir dependencies.'
            stage = 'dependencies'
        elif 'npm test' in lowered or 'vitest' in lowered or 'npm run' in lowered:
            detail = 'Running frontend checks inside the coding workspace.'
            stage = 'coding'
        elif 'mix test' in lowered or 'mix compile' in lowered:
            detail = 'Running backend checks inside the coding workspace.'
            stage = 'coding'
        else:
            detail = 'Implementing and inspecting the application.'
            stage = 'coding'
        self.progress(detail, stage)
        path = self.directory / ('terminal-' + str(self.steps) + '.log')
        with path.open('wb') as output:
            process = subprocess.Popen(['docker', 'exec', self.container, 'bash', '--noprofile', '--norc', '-c', command],
                                       stdout=output, stderr=subprocess.STDOUT, env=clean_env())
            expires = time.monotonic() + 600
            try:
                while process.poll() is None:
                    self.check()
                    if time.monotonic() > expires or path.stat().st_size > 8 * 1024**2:
                        raise ValueError('Terminalkommandot överskred tid eller loggstorlek; körningen stoppades.')
                    time.sleep(1)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
        with path.open('rb') as source:
            source.seek(max(0, path.stat().st_size - 12000))
            tail = source.read(12000).decode(errors='replace')
        return {'exit_code': process.returncode, 'output': tail}

    def escalate(self, reason):
        if self.routing.escalate(reason):
            self.progress('Escalated to ' + self.routing.label + '. The workspace and error history are preserved.',
                          'coding')

    def work(self, task, status=None):
        self.progress((status or 'The coding agent is inspecting the project and preparing dependencies.') +
                      ' Model: ' + self.routing.label, 'dependencies')
        self.history.append({'request': task})
        while self.steps < 80:
            self.check()
            self.steps += 1
            # The transcript is bounded. The project itself remains in the container.
            while len(json.dumps(self.history).encode()) > 65000 and len(self.history) > 1:
                self.history.pop(0)
            prompt = json.dumps({'approved_plan': self.plan, 'current_task': task,
                                 'history': self.history}, ensure_ascii=False)
            try:
                action = model(self.cfg, prompt, system=self.system)
                if not isinstance(action, dict):
                    raise ValueError('Expected a tool action object')
            except ValueError:
                self.format_failures += 1
                if self.format_failures >= 2:
                    self.escalate('Upprepade ogiltiga verktygssvar')
                self.history.append({'tool_error': 'Returnera {"command":"bash"} eller {"done":true,"summary":"..."}.'})
                continue
            if isinstance(action.get('command'), str) and 0 < len(action['command']) <= 48000:
                self.format_failures = 0
                (self.directory / ('command-' + str(self.steps) + '.json')).write_text(json.dumps(action))
                result = self.shell(action['command'])
                self.history.append({'command': action['command'], 'result': result})
                self.command_failures = self.command_failures + 1 if result['exit_code'] != 0 else 0
                if self.command_failures >= 2:
                    self.escalate('Två terminalkommandon i följd misslyckades')
            elif action.get('done') is True:
                self.history.append(action)
                return
            else:
                self.format_failures += 1
                if self.format_failures >= 2:
                    self.escalate('Upprepade ogiltiga verktygssvar')
                self.history.append({'tool_error': 'Använd terminalverktyget med fältet command.'})
        raise ValueError('Kodagenten nådde 80 terminal/modellsteg. Se agentens kommandon och loggar.')

    def export(self, destination):
        script = EXPORT.replace('__SIDES__', json.dumps(self.sides))
        payload = self.docker('exec', self.container, '/usr/local/bin/node', '-e', script, capture=True)
        if len(payload) > 60 * 1024**2:
            raise ValueError('Source export too large')
        files = json.loads(payload)
        if not isinstance(files, dict) or len(files) > 10000:
            raise ValueError('Invalid source export')
        total = 0
        for name, value in files.items():
            path = PurePosixPath(name)
            if (path.is_absolute() or '..' in path.parts or str(path) != name or '\\' in name
                    or path.parts[0] not in ('frontend', 'backend')):
                raise ValueError('Unsafe source export path')
            data = base64.b64decode(value, validate=True)
            total += len(data)
            if total > 40 * 1024**2:
                raise ValueError('Source export exceeds limit')
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        hashes = {}
        sides = ([('frontend', 'solid')] if self.profile == 'static' else
                 [('frontend', 'solid'), ('backend', 'phoenix')])
        for name, kind in sides:
            archive = snapshot(destination / name, kind=kind)
            (destination / (name + '.tar')).write_bytes(archive)
            hashes[name] = hashlib.sha256(archive).hexdigest()
        return hashes
