# Static app workflow (first version)

Opt-in Slack workflow for the macmini2 → Lenovo setup. Ordinary PicoClaw installations are unaffected unless `channel_list.slack.settings.static_flow_command` is configured.

## User flow

Send `bygg app-raknare bygg en enkel räknare` in a DM to PicoClaw (or mention the bot). The response starts a job thread. **All subsequent commands must be replies in that same thread.**

1. The tool-free model helper produces a plan. Reply `plan-ok` in the job thread.
2. One model call produces three files. File names, size and JavaScript syntax are checked. A protected preview is published at `https://preview-app-raknare.marcusasplund.com`.
3. Review the app with the `marcus` preview login chosen on Lenovo. Reply `deploy` in the same job thread to publish exactly those bytes at `https://app-raknare.marcusasplund.com`.
4. `jobb <job-id>` shows durable status and relevant commands. `stoppa <job-id>` discards pending generation; it cannot undo remote publication already in progress.

5. `delete` asks to take down both the app and its preview. `delete-ok` confirms within ten minutes; `stoppa` cancels the pending deletion. The server checks the exact artifact version, retains immutable files, backs up the Nginx configuration and serves HTTP 410 with the original certificate. It restores the configurations if the withdrawal health checks fail. There is no permanent file/certificate purge or Slack restore command in this version.

Approval commands are intercepted from authenticated Slack events before the ordinary model receives them. The process verifies the owner, channel, thread, job state and full SHA-256 hash. Short approvals resolve exactly one job in the same authenticated thread and bind its immutable hash in a SQLite approval record. Events older than the current stage are rejected. Explicit job-ID/hash commands remain supported. Duplicate Slack events are recorded in SQLite. The generator has no tools or shell access. No generated code runs on the host; `node --check` only parses JavaScript. Slack's allowlist remains the first filter.

## Install

Review the scripts before installation. These steps require the previously configured systemd user service, .env launcher, wildcard DNS, working SSH key and Debian Nginx/Certbot.

On Lenovo, install `apache2-utils` if `htpasswd` is missing, then run `sudo bash install-lenovo.sh` from this directory. The configured Certbot email is rootfood@gmail.com. Choose the preview password when prompted. The installer creates a narrow sudo entry for `/usr/local/sbin/picoclaw-static-site` with **no arguments**, root-owned code and a separate root-owned webroot. It does not reload or replace existing Nginx sites during installation. Certbot uses webroot validation for new app/preview hosts and a renewal deploy hook reloads Nginx after renewal.

On macmini2, after applying the code patch in `~/code/picoclaw`, run `bash scripts/staticflow/install-macmini2.sh`. It builds both executables, runs workflow tests, backs up the existing Slack JSON config and executable, updates the opt-in command and restarts the Slack service. Existing .env credentials and the original config.json are not changed. The installer records the absolute Node executable path for the systemd service.

The remote helper writes only index.html, style.css and app.js under its own webroot. It validates the app prefix, file names, sizes and content hash; generates fixed Nginx templates; obtains certificates; and checks the served version over HTTPS. On ordinary command errors it restores the previous Nginx configuration. Generated files never become shell commands or Nginx configuration text.

## Limits and recovery

- New static apps only. App names begin with `app-`. No npm builds, backend, databases, Git/PR integration, existing-app updates or arbitrary deployment commands in this first version.
- Model generation and remote publishing are tested with fakes locally. Real model responses, DNS/ACME issuance, Debian sudo/Nginx integration and browser behavior require the first live acceptance test.
- Each phase has a timeout; only one expensive phase runs at a time. Two model requests per successful job; no automatic retry or repair loop. There is no provider billing-budget enforcement yet.
- On restart the database persists. A job interrupted mid-phase is marked interrupted when queried after ten minutes, and is not automatically resumed. On SSH timeout check the server before retrying: publishing might have finished despite a lost reply.
- The public and protected preview sites use the same immutable artifact. The HTTPS health check verifies routing/version, not app functionality. The user must review behavior and appearance.
- Preview authentication uses Nginx Basic Auth; credentials are entered on Lenovo and never sent to the model. The configured CSP blocks external API requests and third-party dependencies. Do not use real personal data in generated prototypes.
- The main agent keeps exec disabled. The SSH key and job database are outside its workspace. This is application-level separation under the same Linux user, not an OS sandbox against a compromised PicoClaw process.
- The remote sudo helper can publish static apps with possession of the deploy key. Slack approvals are enforced by the controller, not cryptographically verified on Lenovo. Do not expose the key or controller state to an unrestricted coding agent.
- The `picodeploy` account still permits ordinary SSH commands as that nonprivileged user; the installed helper is its only added root permission.
- To disable the workflow remove `static_flow_command` from config.slack.json and restart the service. To remove added root permission remove `/etc/sudoers.d/picoclaw-static` on Lenovo. Published sites remain until explicitly removed.

## Validation

`python3 -m unittest discover -s scripts/staticflow -v`

`TMPDIR=/private/tmp go test -tags goolm,stdjson ./pkg/channels/slack ./pkg/config ./cmd/staticflow-llm`

References: [Nginx Basic Auth](https://nginx.org/en/docs/http/ngx_http_auth_basic_module.html), [Certbot CLI](https://eff-certbot.readthedocs.io/en/stable/man/certbot.html).
