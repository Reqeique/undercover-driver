#!/bin/sh
# One-line installer for the undercover-driver CLI.
#
#   curl -fsSL https://raw.githubusercontent.com/Reqeique/undercover-driver/main/install.sh | sh
#
# Binaries are attached to a public GitHub release of this repo, so no
# authentication is required.
#
# Env overrides:
#   AB_VERSION      release tag to install (default: latest)
#   AB_REPO         owner/repo (default: Reqeique/undercover-driver)
#   AB_BIN_DIR      binary install dir (default: ~/.local/bin)
set -e

REPO="${AB_REPO:-Reqeique/undercover-driver}"
VERSION="${AB_VERSION:-latest}"
BIN_DIR="${AB_BIN_DIR:-$HOME/.local/bin}"

# --- detect platform -------------------------------------------------------
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
  Linux)  OS=linux ;;
  Darwin) OS=darwin ;;
  MINGW*|MSYS*|CYGWIN*) OS=windows ;;
  *) echo "error: unsupported OS: $OS" >&2; exit 1 ;;
esac
case "$ARCH" in
  x86_64|amd64)  ARCH=amd64 ;;
  aarch64|arm64) ARCH=arm64 ;;
  *) echo "error: unsupported arch: $ARCH" >&2; exit 1 ;;
esac
EXT=""
[ "$OS" = "windows" ] && EXT=".exe"
ASSET="undercover-driver-${OS}-${ARCH}${EXT}"
echo "target: $OS/$ARCH -> $ASSET (repo $REPO, version $VERSION)"

# --- resolve release + asset download URL ----------------------------------
if [ "$VERSION" = "latest" ]; then
  REL_URL="https://api.github.com/repos/$REPO/releases/latest"
else
  REL_URL="https://api.github.com/repos/$REPO/releases/tags/$VERSION"
fi
RELEASE_JSON="$(curl -fsSL -H "Accept: application/vnd.github+json" "$REL_URL")"
DOWNLOAD_URL="$(printf '%s' "$RELEASE_JSON" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    name = "'"$ASSET"'"
    for a in d.get("assets", []):
        if a["name"] == name:
            print(a["browser_download_url"]); sys.exit(0)
    sys.exit(1)
except Exception:
    sys.exit(1)
' || true)"
if [ -z "$DOWNLOAD_URL" ]; then
  echo "error: asset '$ASSET' not found in release '$VERSION'." >&2
  echo "       Build it first via the .github/workflows/build-release.yml workflow." >&2
  exit 1
fi

# --- download + install ----------------------------------------------------
mkdir -p "$BIN_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "downloading $ASSET ..."
curl -fsSL -o "$TMP/$ASSET" "$DOWNLOAD_URL"
install -m 0755 "$TMP/$ASSET" "$BIN_DIR/undercover-driver$EXT"
echo "installed: $BIN_DIR/undercover-driver$EXT"

# --- PATH hint -------------------------------------------------------------
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo ""
     echo "NOTE: add $BIN_DIR to your PATH:"
     echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
     echo "  export PATH=\"$HOME/.local/bin:\$PATH\"" ;;
esac

echo ""
echo "done.  Usage:"
echo "  export BROWSER_URL=https://<container>.runs.apify.net"
echo "  export BROWSER_TOKEN=<auth_token>"
echo "  undercover-driver health"
echo "  undercover-driver goto https://example.com"
echo "  undercover-driver snapshot"
