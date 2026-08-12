# undercover-driver

CLI client for the **Stealth Browser Agent** on Apify — a remote, residential-IP
browser session that looks human and passes bot-detection checks (7/7) where
datacenter IPs get flagged.

This repo is the thin HTTP client only. It has zero browser or stealth logic —
it just talks to a running session server. The server-side stealth engine is a
separate, proprietary Apify actor.

## What it does

`undercover-driver` drives a running session server one command at a time and prints
JSON on stdout, so an LLM/agent can feed the result straight back in:

```
POST /command    execute one command, return JSON result
GET  /health     readiness + current page status
```

Every subcommand maps 1:1 to the server's command surface: `status`, `snapshot`,
`goto`, `wait`, `click`, `fill`, `type`, `press`, `select`, `eval`, `text`,
`links`, `screenshot`, `verify_cf`, `vnc`, `close`.

## Install (one line)

```sh
curl -fsSL https://raw.githubusercontent.com/Reqeique/undercover-driver/main/install.sh | sh
```

```powershell
irm https://raw.githubusercontent.com/Reqeique/undercover-driver/main/install.ps1 | iex
```

Binaries are attached to public [GitHub releases](../../releases) for
windows-amd64, linux-amd64 and darwin-arm64. No authentication required.

Environment overrides: `AB_VERSION` (release tag, default `latest`),
`AB_REPO`, `AB_BIN_DIR` (default `~/.local/bin`).

## Usage

```sh
export BROWSER_URL=https://<container>.runs.apify.net
export BROWSER_TOKEN=<auth_token>

undercover-driver health
undercover-driver status
undercover-driver snapshot
undercover-driver goto https://example.com
undercover-driver wait "button[type='submit']" --timeout-ms 15000
undercover-driver click @e3
undercover-driver fill @e4 "hi@example.com"
undercover-driver verify_cf
undercover-driver close
```

### Manual logins via noVNC (`vnc`)

Some flows (Google login, CAPTCHA-on-login pages) are easier done by hand.
`vnc` prints the noVNC viewer URL of the running session; `--start` boots a
new **VNC-enabled** session (`vnc=true`, cloak backend) if nothing is
running, and can pin a persistent R2 profile so the login survives future
runs:

```sh
undercover-driver vnc                                   # URL of the live viewer
undercover-driver vnc --start                            # start a VNC session
undercover-driver vnc --start --session-name google      # persist profile as "google"
undercover-driver vnc --start --backend zendriver        # pick the backend
```

The session server behind it must have `vnc=true`; the URL points at
`/vnc` on the container. Viewers are plain noVNC — no extra install.

### Auto-resolved URL

`BROWSER_URL` is optional. With an Apify API token, the CLI finds the most
recent **RUNNING** run of the actor and uses its container URL automatically.
If **no** run is running, it starts a new server session and waits for its
container URL — one token, no manual setup:

```sh
export APIFY_TOKEN=<apify-api-token>      # resolves + starts the session + auth
undercover-driver goto https://example.com
```

The new session uses the CLI's bearer token (`BROWSER_TOKEN`, else
`APIFY_TOKEN`) as its `auth_token`, so the same token authenticates the
session. Pass `--no-autostart` (or `AB_NO_AUTOSTART=1`) to only attach to an
existing run and error if none is active.

Override with `BROWSER_URL` / `--url`, or point at a different actor with
`APIFY_ACTOR_ID` / `--actor-id` (default: the Stealth Browser Agent actor).

Or run from source:

```sh
export BROWSER_URL=http://localhost:4321
python -m src.cli health
```

### Exit codes

- `0` — command executed and `result.ok` is true
- `1` — server returned `ok:false` (command-level failure)
- `2` — connection/HTTP error, bad args, or invalid response

## License

MIT — see [LICENSE](LICENSE).
