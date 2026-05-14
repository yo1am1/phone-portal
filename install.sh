#!/usr/bin/env bash
# phone-portal installer
# Usage: curl -sSL https://raw.githubusercontent.com/yo1am1/phone-portal/main/install.sh | bash
set -euo pipefail

INSTALL_DIR="${PHONE_PORTAL_DIR:-$HOME/.phone-portal}"
TOKEN="${PHONE_PORTAL_TOKEN:-$(openssl rand -hex 16 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(16))')}"
RELAY_CLI="${PHONE_LINK_RELAY_CLI:-auto}"
GUM_VERSION="0.14.5"

# ── Bootstrap gum ─────────────────────────────────────────────
_ensure_gum() {
  command -v gum >/dev/null 2>&1 && return 0
  printf "  bootstrapping gum %s...\n" "$GUM_VERSION"
  if command -v brew >/dev/null 2>&1; then
    brew install gum --quiet 2>/dev/null && return 0
  fi
  local os arch tmpdir
  os=$(uname -s | tr '[:upper:]' '[:lower:]')
  arch=$(uname -m)
  case "$arch" in x86_64) arch="amd64" ;; aarch64|arm64) arch="arm64" ;; esac
  tmpdir=$(mktemp -d)
  curl -fsSL \
    "https://github.com/charmbracelet/gum/releases/download/v${GUM_VERSION}/gum_${GUM_VERSION}_${os}_${arch}.tar.gz" \
    | tar -xz -C "$tmpdir" 2>/dev/null
  export PATH="$tmpdir:$PATH"
}

_ensure_gum

# ── Header ────────────────────────────────────────────────────
printf "\n"
gum style \
  --border rounded \
  --border-foreground 99 \
  --padding "1 3" \
  --margin "0 2" \
  "$(gum style --bold '📱  phone-portal')" \
  "$(gum style --faint 'send files to any AI agent')" \
  "$(gum style --faint --foreground 99 'github.com/yo1am1/phone-portal')"
printf "\n"

# ── Helpers ───────────────────────────────────────────────────
step() { gum style --bold --foreground 99 "  ▌ $1"; }
ok()   { gum style --foreground 2          "  ✓ $1"; }
warn() { gum style --foreground 3          "  ⚠ $1"; }
die()  { gum style --foreground 1 --bold   "  ✗ $1"; printf "\n"; exit 1; }
run()  { local t="$1"; shift; gum spin --title "    $t" --spinner points -- "$@"; }

# ── Preflight ─────────────────────────────────────────────────
step "Checking requirements"
command -v git    >/dev/null 2>&1 || die "git not found"
command -v uv     >/dev/null 2>&1 || die "uv not found — install: curl -LsSf https://astral.sh/uv/install.sh | sh"
command -v claude >/dev/null 2>&1 || die "claude not found — install Claude Code: https://claude.ai/code"
ok "git · uv · claude — all present"
printf "\n"

# ── Clone / update ────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
  step "Updating existing install"
  run "Pulling latest changes..." git -C "$INSTALL_DIR" pull --ff-only --quiet
  ok "Up to date"
else
  step "Cloning repository"
  run "Cloning from GitHub..." git clone --quiet https://github.com/yo1am1/phone-portal "$INSTALL_DIR"
  ok "Cloned to $INSTALL_DIR"
fi
printf "\n"

# ── Dependencies ──────────────────────────────────────────────
step "Installing dependencies"
run "Running uv sync..." uv sync --project "$INSTALL_DIR" --quiet
ok "Dependencies ready"
printf "\n"

# ── MCP registration ──────────────────────────────────────────
step "Registering MCP server with Claude Code"
if claude mcp get phone-portal >/dev/null 2>&1; then
  warn "Existing entry found — replacing"
  claude mcp remove phone-portal --scope user 2>/dev/null || \
  claude mcp remove phone-portal 2>/dev/null || true
fi

claude mcp add phone-portal \
  --scope user \
  -e PHONE_LINK_TOKEN="$TOKEN" \
  -e PHONE_LINK_BRIDGE_URL="http://127.0.0.1:8765" \
  -e PHONE_LINK_RELAY_PORT="9001" \
  -e PHONE_LINK_RELAY_CLI="$RELAY_CLI" \
  -- uv --directory "$INSTALL_DIR" run python mcp/phone_link_server.py

ok "Registered — user scope (available in all Claude Code projects)"
printf "\n"

# ── Detect relay CLI ──────────────────────────────────────────
detected_cli=""
for c in claude gemini llm ollama; do
  if command -v "$c" >/dev/null 2>&1; then detected_cli="$c"; break; fi
done
relay_label="$RELAY_CLI"
[ "$RELAY_CLI" = "auto" ] && [ -n "$detected_cli" ] && relay_label="auto -> $detected_cli"

# ── Done ──────────────────────────────────────────────────────
gum style \
  --border rounded \
  --border-foreground 2 \
  --padding "1 3" \
  --margin "0 2" \
  "$(gum style --bold --foreground 2 '✓  Installation complete!')" \
  "" \
  "$(gum style --faint "$(printf '%-9s' 'install')")  $(gum style --faint "${INSTALL_DIR/$HOME/~}")" \
  "$(gum style --faint "$(printf '%-9s' 'token')")  $(gum style --faint "${TOKEN:0:20}..")" \
  "$(gum style --faint "$(printf '%-9s' 'relay')")  $(gum style --faint "$relay_label")" \
  "" \
  "$(gum style --bold 'Restart Claude Code, then ask:')" \
  "$(gum style --foreground 6 '"I want to send files from my phone"')"
printf "\n"
