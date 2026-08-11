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
`links`, `screenshot`, `verify_cf`, `close`.

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
