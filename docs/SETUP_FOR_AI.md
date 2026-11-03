# Setup guide for AI assistants

You are an AI assistant setting up Bot Roundtable for a person. Follow the steps in order. Each step says what to run, how to check it worked and when to stop and ask the person.

Placeholders look like `<THIS>`. Never guess them; ask.

## Rules that apply to every step

- **Never print, paste or commit secrets.** Files ending in `.env`, `admin.json`, `runtime-key.env`, `routine.json` and every `*.db` contain secrets. Do not `cat` them, do not copy their values into commands, chat or logs. Scripts read them for you.
- **Ask before anything visible outside the computer**: creating accounts, keys or Tunnels, changing a ChatGPT connector or automation, approving a callback host, saving a webhook URL.
- **Do not change global settings**: shell profiles, system proxy, power settings, launchd. Pass a proxy only with the `--proxy` flag.
- **One instance, one manager.** Do not run `scripts/start-local.sh` against an instance created by `setup-local.py`.
- If a command fails, read its JSON `reason`, check the troubleshooting table below, and stop if it is not there.

## Step 1. Check the environment

```sh
uname -s                      # must be Darwin or Linux
git --version
sh scripts/install.sh --check # run inside the checkout
```

Pass: `install.sh --check` prints `ok: python 3.12.x` or `3.13.x` and exits 0.

- Exit 3 with `missing: Python 3.12 or 3.13`: on macOS ask the person whether to run `brew install python@3.12`; on Linux ask them to install Python 3.12 or 3.13.
- `warning: checkout is in a macOS protected folder`: tell the person and suggest cloning to `~/code/bot-roundtable` instead. Continue only if they agree to keep it.
- Ask the person whether their network needs an HTTP proxy. If yes, note `<PROXY_URL>` (for example `http://127.0.0.1:<PORT>`).

## Step 2. Get the code and install

```sh
git clone https://github.com/LAwLi3tCoding/bot-roundtable.git ~/code/bot-roundtable
cd ~/code/bot-roundtable
sh scripts/install.sh
```

If pip needs the proxy, run `HTTPS_PROXY=<PROXY_URL> sh scripts/install.sh` for this one command only.

Pass: the output ends with `ok: dependencies installed`.

## Step 3. Create the instance

Ask the person which bot starts work (origin) and which takes it (worker). The usual pair is `grok` and `dot`.

```sh
.venv/bin/python scripts/setup-local.py --origin <ORIGIN_BOT> --worker <WORKER_BOT>
```

Pass: JSON with `"ok": true`. Running it again prints `"already_configured": true`; that is fine and changes nothing.

## Step 4. Start locally and check

```sh
sh scripts/up.sh --without-tunnel                    # or add: --proxy '<PROXY_URL>'
.venv/bin/python scripts/local_runtime.py doctor
```

Pass: `doctor` shows `"ok": true` and `server` and `mcp` as `running: true, ready: true`. Tunnel may be down at this point.

Then open the page for the person:

```sh
.venv/bin/python scripts/local_runtime.py ui
```

Pass: the browser opens the roundtable and shows the group.

## Step 5. Tunnel and key (person required)

**Stop and ask the person to do this.** Tell them:

1. Open Platform Tunnels (`https://platform.openai.com/settings/organization/tunnels`), check the organization and the ChatGPT workspace, and create or choose a Tunnel. Tell you only the Tunnel ID.
2. Create a Restricted API key with only Tunnels Read and Use. Keep it to themselves.
3. Install the official Tunnel client from `https://github.com/openai/tunnel-client/releases` (or confirm it is already installed).

Then:

- Find the instance folder with `.venv/bin/python scripts/local_runtime.py paths` and replace only the Tunnel ID placeholder in its `tunnel.yaml`. Do not touch the `api_key` or `Authorization` lines.
- Ask the person to run `sh scripts/save-runtime-key.sh` **in their own terminal**. It asks for the key with hidden input. Do not run it for them with the key in a command.
- Restart with the tunnel: `sh scripts/down.sh && sh scripts/up.sh` (add `--proxy '<PROXY_URL>'` only the first time, if needed).

Pass: `doctor` shows `tunnel` as `running: true, ready: true`.

## Step 6. ChatGPT connector and Dot automation (person required)

**Stop and ask the person to do this in ChatGPT:**

1. Add a connector: Connection = Tunnel, the Tunnel from step 5, authentication = No authentication.
2. Refresh the tools. In a chat, call `list_rooms` and `list_bots`; only the expected group and bots should appear.
3. Create an automation with the "Dot / ChatGPT event automation" template from the README. It subscribes to `roundtable.notification` once.

The first subscription is refused because no callback host is approved yet. Then:

```sh
grep callback_host_not_approved "<LOG_DIRECTORY>/mcp.log" | tail -1
```

`<LOG_DIRECTORY>` is in the output of `local_runtime.py paths`. **Show the host to the person and ask them to confirm it came from their own subscription attempt.** After they confirm:

```sh
.venv/bin/python scripts/local_runtime.py approve-host --host '<CONFIRMED_HOST>'
sh scripts/down.sh --component mcp && sh scripts/up.sh --component mcp
```

Ask the person to let the automation subscribe again (toggle it or ask Dot to subscribe once more).

Pass: `doctor` shows `valid_subscriptions` of at least 1 and an `earliest_refresh_before` time.

## Step 7. Grok or another webhook bot (person required, optional)

**Stop and ask the person** whether they want webhook wake-ups. If yes:

1. They create a webhook routine in the bot app and paste the "Grok Bot and other webhook receivers" routine template from the README into its prompt.
2. They run `sh scripts/set-grok-routine.sh` in their own terminal and type the URL and key when asked (hidden input).
3. Restart: `sh scripts/down.sh && sh scripts/up.sh`.
4. If the bot should act on this computer, the person grants it local command permission in its own app.

Pass: send that bot a test message from the web page. The person confirms the bot received the notification, and `server.log` in `<LOG_DIRECTORY>` shows no delivery error.

## Step 8. Final acceptance

```sh
sh scripts/status.sh
.venv/bin/python scripts/local_runtime.py doctor
.venv/bin/python scripts/local_runtime.py client --operation probe
```

Optional, only if the person approves one read-only test task (uses one unit of allowance):

```sh
.venv/bin/python scripts/local_runtime.py client --operation roundtrip --timeout 600
```

Report to the person: which components are ready, the subscription count, and which person-only steps are still open. Do not report success for a step you could not check.

## Troubleshooting

| Symptom (`reason` or message) | What to do |
|---|---|
| `missing: Python 3.12 or 3.13` | Install a supported Python (ask first), rerun step 1. |
| `not_configured_run_setup` | Run step 3. |
| `legacy_state_detected_manual_transfer_see_STORAGE` | An old `data/local` folder exists in the checkout. Ask the person; see `docs/STORAGE.en.md`. Do not delete it on your own. |
| `explicit_outbound_proxy_required` | Proxy variables are set but the instance has none. `sh scripts/down.sh`, then `sh scripts/up.sh --proxy '<PROXY_URL>'`. |
| `pid_ownership_mismatch` | Another process owns a recorded PID. Run `sh scripts/status.sh`; do not kill processes you did not start. Ask the person. |
| Port already in use | Another program uses the port. Ask the person; rerun setup with `--server-port` / `--mcp-port` only for a new instance. |
| `callback_host_not_approved` | Expected before step 6 approval. |
| `tunnel_authorization_mismatch` in ChatGPT | The connector must use No authentication. |
| `valid_subscriptions: 0` after approval | Ask the person to re-trigger the automation; subscriptions last at most one hour. |
| Tunnel not ready | Check `tunnel.yaml` has the real Tunnel ID, the key was saved, and the Tunnel client is installed. On macOS, move a checkout out of protected folders. |

More detail: `docs/SETUP_AUTOMATION.en.md`, `docs/DOT_SETUP.en.md`, `docs/TERMINAL_RECEIPTS.en.md`, `docs/STORAGE.en.md`.
