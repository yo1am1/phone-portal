#!/usr/bin/env bash
# phone-portal installer
# Usage: curl -sSL https://raw.githubusercontent.com/yo1am1/phone-portal/main/install.sh | bash
set -euo pipefail

INSTALL_DIR="${PHONE_PORTAL_DIR:-$HOME/.phone-portal}"
TOKEN="${PHONE_PORTAL_TOKEN:-$(openssl rand -hex 16 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(16))')}"
RELAY_CLI="${PHONE_LINK_RELAY_CLI:-auto}"

# ── Colors (disabled when not a TTY) ─────────────────────────
if [ -t 1 ]; then
  R=$'\033[0m'   B=$'\033[1m'    DIM=$'\033[2m'
  CY=$'\033[36m' GN=$'\033[32m' YL=$'\033[33m'
  RD=$'\033[31m' GY=$'\033[90m'
  BCY=$'\033[1;36m' BGN=$'\033[1;32m' BRD=$'\033[1;31m'
else
  R='' B='' DIM='' CY='' GN='' YL='' RD='' GY='' BCY='' BGN='' BRD=''
fi

# ── Helpers ───────────────────────────────────────────────────
nl()    { printf "\n"; }
hdr()   { printf "  ${BCY}▌${R} ${B}%s${R}\n" "$1"; }
ok()    { printf "  ${BGN}✓${R}  %s\n" "$1"; }
info()  { printf "  ${GY}  %s${R}\n" "$1"; }
warn()  { printf "  ${YL}⚠${R}  %s\n" "$1"; }
die()   { nl; printf "  ${BRD}✗${R}  ${B}%s${R}\n" "$1"; nl; exit 1; }

spin() {
  # $1 = label, rest = command
  local label="$1"; shift
  if [ -t 1 ]; then
    "$@" &
    local pid=$! i=0 chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    while kill -0 "$pid" 2>/dev/null; do
      printf "\r  ${CY}%s${R}  ${DIM}%s${R}" "${chars:$((i % 10)):1}" "$label"
      (( i++ )) || true
      sleep 0.08
    done
    wait "$pid"
    printf "\r\033[K"
  else
    printf "  %s\n" "$label"
    "$@"
  fi
}

box_line() {
  # box_line <color> <left> <text> <width> <right>
  local col="$1" l="$2" txt="$3" w="$4" r="$5"
  local pad=$(( w - ${#txt} ))
  printf "  %s%s%s%s%${pad}s%s%s\n" "$col" "$l" "$R" "$txt" "" "$col" "$r" "$R"
}

# ── Header ────────────────────────────────────────────────────
nl
printf "  ${BCY}╭──────────────────────────────────────╮${R}\n"
printf "  ${BCY}│${R}                                      ${BCY}│${R}\n"
printf "  ${BCY}│${R}    ${B}📱  phone-portal${R}                  ${BCY}│${R}\n"
printf "  ${BCY}│${R}    ${DIM}send files to any AI agent${R}        ${BCY}│${R}\n"
printf "  ${BCY}│${R}    ${DIM}github.com/yo1am1/phone-portal${R}    ${BCY}│${R}\n"
printf "  ${BCY}│${R}                                      ${BCY}│${R}\n"
printf "  ${BCY}╰──────────────────────────────────────╯${R}\n"
nl

# ── Preflight ─────────────────────────────────────────────────
hdr "Checking requirements"
command -v git    >/dev/null 2>&1 || die "git not found"
command -v uv     >/dev/null 2>&1 || die "uv not found — install: curl -LsSf https://astral.sh/uv/install.sh | sh"
command -v claude >/dev/null 2>&1 || die "claude not found — install Claude Code first: https://claude.ai/code"
ok "git · uv · claude — all present"
nl

# ── Clone / update ────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
  hdr "Updating existing install"
  spin "Pulling latest…" git -C "$INSTALL_DIR" pull --ff-only --quiet
  ok "Up to date"
else
  hdr "Cloning repository"
  spin "Cloning phone-portal…" git clone --quiet https://github.com/yo1am1/phone-portal "$INSTALL_DIR"
  ok "Cloned → $INSTALL_DIR"
fi
nl

# ── Dependencies ──────────────────────────────────────────────
hdr "Installing dependencies"
spin "Running uv sync…" uv sync --project "$INSTALL_DIR" --quiet
ok "Dependencies ready"
nl

# ── MCP registration ──────────────────────────────────────────
hdr "Registering MCP server with Claude Code"
if claude mcp get phone-portal >/dev/null 2>&1; then
  info "Existing entry found — replacing"
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
nl

# ── Detect active relay CLI ───────────────────────────────────
detected_cli=""
for c in claude gemini llm ollama; do
  if command -v "$c" >/dev/null 2>&1; then
    detected_cli="$c"; break
  fi
done
if [ "$RELAY_CLI" = "auto" ] && [ -n "$detected_cli" ]; then
  relay_label="auto → ${detected_cli}"
else
  relay_label="$RELAY_CLI"
fi

# ── Done ──────────────────────────────────────────────────────
nl
printf "  ${BGN}╭──────────────────────────────────────╮${R}\n"
printf "  ${BGN}│${R}  ${BGN}✓${R}  ${B}Installation complete!${R}               ${BGN}│${R}\n"
printf "  ${BGN}├──────────────────────────────────────┤${R}\n"
printf "  ${BGN}│${R}  ${GY}install ${R} ${DIM}%-30s${R} ${BGN}│${R}\n" "$INSTALL_DIR"
printf "  ${BGN}│${R}  ${GY}token   ${R} ${DIM}%-30s${R} ${BGN}│${R}\n" "$TOKEN"
printf "  ${BGN}│${R}  ${GY}relay   ${R} ${DIM}%-30s${R} ${BGN}│${R}\n" "$relay_label"
printf "  ${BGN}├──────────────────────────────────────┤${R}\n"
printf "  ${BGN}│${R}                                      ${BGN}│${R}\n"
printf "  ${BGN}│${R}  ${B}Restart Claude Code, then ask:${R}        ${BGN}│${R}\n"
printf "  ${BGN}│${R}  ${CY}\"I want to send files from my phone\"${R}  ${BGN}│${R}\n"
printf "  ${BGN}│${R}                                      ${BGN}│${R}\n"
printf "  ${BGN}╰──────────────────────────────────────╯${R}\n"
nl
