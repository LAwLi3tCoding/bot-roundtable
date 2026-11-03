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

Then install the short client command that webhook bots use (Step 7). It writes `~/.local/bin/roundtable-client` with this checkout's `.venv` and the instance folder built in; rerunning it overwrites and updates it. Pass the same `--state-dir` / `--name` you used for setup, if any; `--output` picks another location. It refuses to overwrite a file it did not generate.

```sh
.venv/bin/python scripts/local_runtime.py install-client
```

Pass: JSON with `"ok": true` and the `client` path. If `~/.local/bin` is not on the person's `PATH`, say so; the README template already falls back to the full path.

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

**Stop and ask the person** whether they want webhook wake-ups. If no, skip to step 8. If yes, go through these in order. Steps marked **person only** are things you cannot do; stop, tell the person exactly what is needed, and wait until they confirm.

1. **Person only: create the routine.** In the bot's own app, the person asks the bot to create a webhook-triggered routine and pastes the "Grok Bot and other webhook receivers" routine template from the README into its instruction. The routine then shows a webhook URL and a key (for Grok Bot: the routine's Webhook section, fields "POST to" and "key"; see https://cursor.com/help/grok-bot/routines). Do not ask the person to paste either value into chat.
2. **Person only: save the URL and key.** The person runs `sh scripts/set-grok-routine.sh` **in their own terminal**. It asks with hidden input for `Approved Grok routine HTTPS URL` and then `Routine key`. The key is the bare key, without `Bearer `; Roundtable sends `Authorization: Bearer <key>` itself. The URL must be HTTPS on port 443. Do not run the script for them with values in a command.
3. Restart: `sh scripts/down.sh && sh scripts/up.sh`.
4. **Fill in the template placeholder.** Make sure Step 3's `install-client` ran (rerun it if the checkout or instance moved). Give the person `<my bot ID>` (this bot's Roundtable ID, `grok` for the first bot by default) to put in the routine instruction. Nothing else in the template is machine-specific.
5. **Person only: allow local commands.** For the bot to run `roundtable-client` on this computer, the person connects this computer to the bot's app as one of its computers and allows command execution on it (for Grok Bot: Settings > Computer > Your computer > Execution on this computer; see https://cursor.com/docs/grok-bot/settings). The bot's desktop app must stay open and online. If the person does not allow this, the bot can still be woken but cannot read its mailbox here; say so in the final report.

The routine reads and replies with `roundtable-client` (full path `~/.local/bin/roundtable-client` when it is not on `PATH`). It reads the bot's credentials from the instance folder itself, so no secret appears on a command line:

```sh
roundtable-client --operation probe
printf '%s' '{"after":0}' | roundtable-client --operation mailbox
```

Other operations: `task --task-id ID`, `tasks`, `inbox`, `topics`, `reply` (stdin `{"body","request_id"}`, plus optional `"topic_id"` and `"mentions"`), `cancel --task-id ID [--reason TEXT]`, `create` (see `docs/ONBOARDING_RUNTIME.en.md`). Without `--bot <bot ID>` the client acts as the instance's `--origin` bot.

Pass: `roundtable-client --operation probe` returns JSON with the expected `room` and `"agent"` (the origin bot), and `mailbox` returns `messages` and `next_cursor`. Then send that bot a test message from the web page. The person confirms the bot received the notification and read the message, and `server.log` in `<LOG_DIRECTORY>` shows no delivery error.

## Step 8. Codex for Dot (person required, optional)

**Stop and ask the person** whether Dot should do coding work through Codex. Roundtable never starts Codex; Dot does it with access the person already gave it in ChatGPT. If yes, tell the person they must do these themselves, then wait for confirmation:

1. **Person only:** give ChatGPT / Codex access to the repository Dot should change (for example connect GitHub or their computer), following the official OpenAI Codex docs (https://developers.openai.com/codex). You cannot verify or set up this access from here.
2. **Person only:** decide what Codex may do (push branches, open PRs, run commands) and which steps need their approval. Merges, deploys and real accounts should always be "ask me first".
3. The Dot automation template in the README already tells Dot to use only that access and to report a PR link or the failure reason. Do not widen it.

Pass: the person confirms the access is set up. Do not create a test coding task without their explicit approval. If they decline, Dot still works for non-coding tasks.

## Step 9. Final acceptance

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

## Add another Bot

Use the existing instance selector (`--name` or `--state-dir`) consistently. The server must be running. Do not create a second instance or edit live credentials.

```sh
python scripts/local_runtime.py add-bot --bot helper --kind grok --wake grok-routine
python scripts/local_runtime.py set-grok-routine --bot helper
```

**Stop and ask the person** to create a separate routine for this Bot, approve access, and enter its URL and key through the hidden prompts. Never extract keys from another app or place them in command arguments or chat. The private `routine-<id>.json` takes effect on the next server start. Each routine wakes only its selected Bot.

For an event-driven Bot, use `--kind dot --wake mcp-events`. **Stop and ask the person** to approve its connector and callback host before configuring subscriptions. Each Bot uses its own scoped credential. `--kind other-bot --wake poll` requires the Bot to poll its own mailbox and enables no webhook.

Restart the managed services, then read the selected mailbox:

```sh
python scripts/local_runtime.py down
python scripts/local_runtime.py up
printf '{}\n' | python scripts/local_runtime.py client --bot helper --operation mailbox
```

Existing `origin` / `worker` instances load automatically as two Bots. Legacy `routine.json` remains a fallback for the original Bot; `routine-<id>.json` takes precedence. New Bots receive the default hourly allowance of 20; `--allowance` chooses a different limit.

If adding a Bot fails after its credential was saved, retry with the same ID and kind: the command validates and reuses that credential without rotating it. If a join response was lost before saving the credential, stop and ask the person to inspect and recover that Bot; do not silently remove or re-register it.
