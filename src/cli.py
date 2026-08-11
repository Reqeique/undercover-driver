#!/usr/bin/env python3
"""undercover-driver CLI — drive a running session server from the agent harness.

Thin client over the session server's HTTP API:

    POST /command   execute one command, return JSON result
    GET  /health    readiness + current page status

Every subcommand maps 1:1 to the server's command surface (status, snapshot,
goto, wait, click, fill, type, press, select, eval, text, links, screenshot,
verify_cf, close).  Output is JSON on stdout so an agent can feed it straight
back into an LLM; use --pretty for a human-readable rendering.

Usage:

    export APIFY_TOKEN=<apify-api-token>     # auto-resolves BROWSER_URL, starts a session if none is running, + auth
    # or explicitly:
    export BROWSER_URL=http://localhost:4321  # session server base URL
    export BROWSER_TOKEN=secret               # Bearer token (optional)

    python -m src.cli health
    python -m src.cli status
    python -m src.cli snapshot
    python -m src.cli goto https://example.com
    python -m src.cli wait "button[type='submit']" --timeout-ms 15000
    python -m src.cli click @e3
    python -m src.cli fill @e4 "hi@example.com" --wait-ms 300
    python -m src.cli type "hello world"
    python -m src.cli press Enter
    python -m src.cli select @e7 "option value"
    python -m src.cli eval "document.title"
    python -m src.cli text
    python -m src.cli links
    python -m src.cli screenshot --name dashboard
    python -m src.cli verify_cf --timeout 30 --click-delay 3
    python -m src.cli close

Exit codes:
    0  command executed and result.ok is true
    1  server returned ok:false (command-level failure)
    2  connection/HTTP error, bad args, or invalid response
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, NoReturn


class _CliError(Exception):
    """Fatal client-side error -> exit code 2."""


def _fatal(msg: str) -> "NoReturn":
    raise _CliError(msg)

DEFAULT_URL = "http://localhost:4321"
DEFAULT_ACTOR_ID = "pHO5Yrhfzq7ZCu5Fy"


# ---------------------------------------------------------------------------
# session URL resolution (Apify API)
# ---------------------------------------------------------------------------

def _actor_id(args: argparse.Namespace) -> str:
    return (args.actor_id or os.environ.get("APIFY_ACTOR_ID") or DEFAULT_ACTOR_ID)


def _resolve_browser_url(args: argparse.Namespace) -> tuple[str | None, str | None]:
    """Find the containerUrl of the most recent RUNNING run of the actor.

    If no run is RUNNING, starts a fresh server run and waits for its
    container URL (unless --no-autostart).  Returns (url, None) on success,
    (None, error) otherwise.
    """
    tok = _apify_token(args)
    if not tok:
        return None, "no token; set APIFY_TOKEN or BROWSER_TOKEN (or pass --token) to auto-resolve BROWSER_URL"
    actor = _actor_id(args)
    api_headers = {"Accept": "application/json", "Authorization": f"Bearer {tok}"}

    list_url = f"https://api.apify.com/v2/actors/{actor}/runs?desc=1&limit=5"
    try:
        status, resp = _http("GET", list_url, api_headers)
    except _CliError as e:
        return None, str(e)
    if status != 200:
        return None, f"could not list actor runs (HTTP {status}): {str(resp)[:300]}"

    for item in resp.get("data", {}).get("items", []):
        if item.get("status") != "RUNNING":
            continue
        rid = item.get("id")
        for detail_url in (
            f"https://api.apify.com/v2/actor-runs/{rid}",
            f"https://api.apify.com/v2/actors/{actor}/runs/{rid}",
        ):
            dstatus, dresp = _http("GET", detail_url, api_headers)
            if dstatus != 200:
                continue
            cu = dresp.get("data", {}).get("containerUrl")
            if cu:
                return cu.rstrip("/"), None

    if getattr(args, "no_autostart", False) or os.environ.get("AB_NO_AUTOSTART") == "1":
        return None, f"no RUNNING run found for actor {actor} (--no-autostart; start one, then retry)"
    return _start_server_run(args, actor, tok)


RUN_START_TIMEOUT_S = 300.0
RUN_POLL_INTERVAL_S = 5.0
RUN_MEMORY_MB = 2048  # smallest Apify power-of-2 tier above observed ~1.3 GB max usage


def _start_server_run(args: argparse.Namespace, actor: str, tok: str) -> tuple[str | None, str | None]:
    """Start a fresh server run for the actor and wait for its container URL.

    The new run's auth_token is the CLI's session bearer token (_token), so a
    single token authenticates both the API and the session.
    """
    session_token = _token(args) or tok
    payload = {
        "mode": "server",
        "backend": "zendriver",
        "proxy_country": "US",
        "idle_timeout_s": 3600,
        "auth_token": session_token,
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {tok}",
    }
    start_url = f"https://api.apify.com/v2/actors/{actor}/runs?memory={RUN_MEMORY_MB}"
    try:
        status, resp = _http("POST", start_url, headers, json.dumps(payload).encode("utf-8"))
    except _CliError as e:
        return None, str(e)
    if status not in (200, 201):
        return None, f"could not start actor run (HTTP {status}): {str(resp)[:300]}"
    rid = resp.get("data", {}).get("id")
    if not rid:
        return None, "started run but got no run id back"

    print(f"started new session run {rid} for actor {actor} (waiting for container URL)", file=sys.stderr)
    poll_headers = {"Accept": "application/json", "Authorization": f"Bearer {tok}"}
    deadline = time.monotonic() + RUN_START_TIMEOUT_S
    while time.monotonic() < deadline:
        time.sleep(RUN_POLL_INTERVAL_S)
        try:
            dstatus, dresp = _http("GET", f"https://api.apify.com/v2/actor-runs/{rid}", poll_headers)
        except _CliError as e:
            return None, str(e)
        if dstatus != 200:
            continue
        d = dresp.get("data", {})
        st = d.get("status")
        cu = d.get("containerUrl")
        if cu:
            return cu.rstrip("/"), None
        if st in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED_OUT"):
            return None, f"new run {rid} exited with status {st} before a session URL was available"
        print(f"  waiting for run {rid} (status {st})...", file=sys.stderr)
    return None, f"timed out waiting for run {rid} to become RUNNING"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _base_url(args: argparse.Namespace) -> str:
    return (args.url or os.environ.get("BROWSER_URL") or DEFAULT_URL).rstrip("/")


def _token(args: argparse.Namespace) -> str:
    return args.token or os.environ.get("BROWSER_TOKEN") or os.environ.get("APIFY_TOKEN") or ""


def _apify_token(args: argparse.Namespace) -> str:
    """Token for Apify API calls (resolution) — prefers the real API token.

    The session bearer (BROWSER_TOKEN) is often a per-run auth_token that the
    Apify API would reject, so resolution only uses it as a last resort.
    """
    return (os.environ.get("APIFY_TOKEN") or args.token or os.environ.get("BROWSER_TOKEN") or "")


def _headers(args: argparse.Namespace, json_body: bool = False) -> dict[str, str]:
    h = {"Accept": "application/json"}
    if json_body:
        h["Content-Type"] = "application/json"
    tok = _token(args)
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _http(method: str, url: str, headers: dict[str, str], body: bytes | None = None,
          timeout: float = 60.0) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            detail = {"detail": str(e)}
        return e.code, detail
    except Exception as e:  # URLError, timeout, etc.
        raise _CliError(f"connection to {url} failed: {e}") from e


def _post_command(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_base_url(args)}/command"
    status, resp = _http("POST", url, _headers(args, json_body=True),
                         json.dumps(payload).encode("utf-8"))
    if status != 200:
        raise _CliError(f"server returned HTTP {status}: {json.dumps(resp)[:500]}")
    if not isinstance(resp, dict):
        raise SystemExit(f"error: unexpected response type {type(resp).__name__}")
    return resp


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _emit(args: argparse.Namespace, result: dict[str, Any]) -> None:
    if args.pretty:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False))


def _finish(args: argparse.Namespace, result: dict[str, Any]) -> int:
    _emit(args, result)
    return 0 if result.get("ok", False) else 1


# ---------------------------------------------------------------------------
# command handlers
# ---------------------------------------------------------------------------

def _cmd_health(args: argparse.Namespace) -> int:
    url = f"{_base_url(args)}/health"
    status, resp = _http("GET", url, _headers(args))
    if status != 200:
        raise _CliError(f"server returned HTTP {status}: {json.dumps(resp)[:500]}")
    _emit(args, {"ok": True, **resp})
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    return _finish(args, _post_command(args, {"cmd": "status"}))


def _cmd_snapshot(args: argparse.Namespace) -> int:
    return _finish(args, _post_command(args, {"cmd": "snapshot"}))


def _cmd_goto(args: argparse.Namespace) -> int:
    return _finish(args, _post_command(args, {"cmd": "goto", "url": args.url_arg}))


def _cmd_wait(args: argparse.Namespace) -> int:
    return _finish(args, _post_command(args, {
        "cmd": "wait",
        "selector": args.selector,
        "timeout_ms": args.timeout_ms,
    }))


def _cmd_click(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {"cmd": "click", "target": args.target}
    if args.wait_ms:
        payload["wait_ms"] = args.wait_ms
    return _finish(args, _post_command(args, payload))


def _cmd_fill(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {"cmd": "fill", "target": args.target, "value": args.value}
    if args.wait_ms:
        payload["wait_ms"] = args.wait_ms
    return _finish(args, _post_command(args, payload))


def _cmd_type(args: argparse.Namespace) -> int:
    return _finish(args, _post_command(args, {"cmd": "type", "text": args.text}))


def _cmd_press(args: argparse.Namespace) -> int:
    return _finish(args, _post_command(args, {"cmd": "press", "key": args.key}))


def _cmd_select(args: argparse.Namespace) -> int:
    return _finish(args, _post_command(args, {"cmd": "select", "target": args.target, "value": args.value}))


def _cmd_eval(args: argparse.Namespace) -> int:
    return _finish(args, _post_command(args, {"cmd": "eval", "expr": args.expr}))


def _cmd_text(args: argparse.Namespace) -> int:
    return _finish(args, _post_command(args, {"cmd": "text"}))


def _cmd_links(args: argparse.Namespace) -> int:
    return _finish(args, _post_command(args, {"cmd": "links"}))


def _cmd_screenshot(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {"cmd": "screenshot"}
    if args.name:
        payload["name"] = args.name
    return _finish(args, _post_command(args, payload))


def _cmd_verify_cf(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {"cmd": "verify_cf"}
    if args.timeout:
        payload["timeout"] = args.timeout
    if args.click_delay:
        payload["click_delay"] = args.click_delay
    return _finish(args, _post_command(args, payload))


def _cmd_close(args: argparse.Namespace) -> int:
    return _finish(args, _post_command(args, {"cmd": "close"}))


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="undercover-driver",
        description="Drive a running session server from the agent harness.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--url", help=f"session server base URL (env BROWSER_URL, default {DEFAULT_URL})")
    parser.add_argument("--token", help="Bearer token (env BROWSER_TOKEN or APIFY_TOKEN)")
    parser.add_argument("--actor-id", help=f"Apify actor ID to auto-resolve BROWSER_URL (env APIFY_ACTOR_ID, default {DEFAULT_ACTOR_ID})")
    parser.add_argument("--no-autostart", action="store_true",
                        help="if no RUNNING run exists, fail instead of starting a new one")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout in seconds")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("health", help="GET /health — readiness + current page status")
    p.set_defaults(func=_cmd_health)

    p = sub.add_parser("status", help="current page status")
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("snapshot", help="visible interactive elements with @refs")
    p.set_defaults(func=_cmd_snapshot)

    p = sub.add_parser("goto", help="navigate to a URL")
    p.add_argument("url_arg", metavar="URL", help="destination URL")
    p.set_defaults(func=_cmd_goto)

    p = sub.add_parser("wait", help="wait for a selector or text")
    p.add_argument("selector", help="CSS selector or text to wait for")
    p.add_argument("--timeout-ms", type=int, default=15000)
    p.set_defaults(func=_cmd_wait)

    p = sub.add_parser("click", help="click an element by @ref")
    p.add_argument("target", metavar="REF", help="element ref, e.g. @e3")
    p.add_argument("--wait-ms", type=int, help="extra settle delay after click")
    p.set_defaults(func=_cmd_click)

    p = sub.add_parser("fill", help="fill an input by @ref")
    p.add_argument("target", metavar="REF", help="element ref, e.g. @e4")
    p.add_argument("value", help="value to type")
    p.add_argument("--wait-ms", type=int, help="extra settle delay after fill")
    p.set_defaults(func=_cmd_fill)

    p = sub.add_parser("type", help="type text at the focused element")
    p.add_argument("text", help="text to type")
    p.set_defaults(func=_cmd_type)

    p = sub.add_parser("press", help="press a keyboard key")
    p.add_argument("key", help="key name, e.g. Enter / Tab")
    p.set_defaults(func=_cmd_press)

    p = sub.add_parser("select", help="pick an option in a <select> by @ref")
    p.add_argument("target", metavar="REF", help="element ref")
    p.add_argument("value", help="option value or visible text")
    p.set_defaults(func=_cmd_select)

    p = sub.add_parser("eval", help="run a JS expression in the page")
    p.add_argument("expr", help="JavaScript expression")
    p.set_defaults(func=_cmd_eval)

    p = sub.add_parser("text", help="dump trimmed body text")
    p.set_defaults(func=_cmd_text)

    p = sub.add_parser("links", help="list page links")
    p.set_defaults(func=_cmd_links)

    p = sub.add_parser("screenshot", help="capture a screenshot (stored as SCREENSHOT-<name>)")
    p.add_argument("--name", help="storage key suffix (default shot-<epoch>)")
    p.set_defaults(func=_cmd_screenshot)

    p = sub.add_parser("verify_cf", help="solve a Cloudflare challenge on the current page")
    p.add_argument("--timeout", type=float, help="seconds to wait for CF iframe (default 30)")
    p.add_argument("--click-delay", type=float, help="human click delay (default 3)")
    p.set_defaults(func=_cmd_verify_cf)

    p = sub.add_parser("close", help="shut down the session server")
    p.set_defaults(func=_cmd_close)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if not (args.url or os.environ.get("BROWSER_URL")):
            url, err = _resolve_browser_url(args)
            if url:
                args.url = url
                print(f"auto-resolved BROWSER_URL: {url}", file=sys.stderr)
            elif err:
                print(f"warning: {err}", file=sys.stderr)
        return int(args.func(args))
    except _CliError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
