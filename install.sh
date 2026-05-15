#!/usr/bin/env bash
# phone-portal installer
#
# Basic usage:
#   curl -fsSL https://raw.githubusercontent.com/yo1am1/phone-portal/main/install.sh | bash
#
# Advanced:
#   curl -fsSL https://raw.githubusercontent.com/yo1am1/phone-portal/main/install.sh | bash -s -- --help
#
set -euo pipefail

# ── Defaults (overridable via env or CLI flags) ────────────────────────────────
REPO_URL="${PHONE_PORTAL_REPO_URL:-https://github.com/yo1am1/phone-portal}"
REPO_BRANCH="${PHONE_PORTAL_BRANCH:-main}"
INSTALL_DIR="${PHONE_PORTAL_DIR:-$HOME/.phone-portal}"

TOKEN="${PHONE_PORTAL_TOKEN:-$(openssl rand -hex 16 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(16))')}"
RELAY_PORT="${PHONE_LINK_RELAY_PORT:-9001}"
RELAY_CLI="${PHONE_LINK_RELAY_CLI:-auto}"
RELAY_CMD="${PHONE_LINK_RELAY_CMD:-}"
BRIDGE_URL="${PHONE_LINK_BRIDGE_URL:-http://127.0.0.1:8765}"

# Installer-specific knobs
TARGETS_CSV="${PHONE_PORTAL_TARGETS:-}" # comma-separated targets (see --help)
CLAUDE_SCOPE="${PHONE_PORTAL_CLAUDE_SCOPE:-user}" # user|project
MCP_NAME="${PHONE_PORTAL_MCP_NAME:-phone-portal}"
INTERACTIVE="${PHONE_PORTAL_INTERACTIVE:-no}"   # auto|yes|no

REGISTERED_TARGETS=()
AVAILABLE_CLIENTS=()

usage() {
  cat <<'EOF'
phone-portal installer

Usage:
  curl -fsSL https://raw.githubusercontent.com/yo1am1/phone-portal/main/install.sh | bash
  curl -fsSL https://raw.githubusercontent.com/yo1am1/phone-portal/main/install.sh | bash -s -- [options]

Options:
  --install-dir PATH     Install location (default: ~/.phone-portal)
  --repo URL             Repo URL (default: https://github.com/yo1am1/phone-portal)
  --branch NAME          Git branch (default: main)

  --token TOKEN          Auth token for phone UI (default: random)
  --bridge-url URL       Bridge URL (default: http://127.0.0.1:8765)
  --relay-port PORT      Relay port (default: 9001)
  --relay-cli NAME       Relay CLI: auto|claude|gemini|llm|ollama|custom
  --relay-cmd TEMPLATE   Custom relay command template, e.g. "llm -m gpt-4o {prompt}"

  --targets CSV          Where to install/register MCP config (comma-separated):
                           auto            (default) register with detected CLIs (claude/codex)
                           claude          register with Claude Code CLI
                           codex           register with Codex CLI
                           mcpjson-global  write/merge into ~/.mcp.json (for clients that read it)
                           mcpjson-here    write/merge into ./.mcp.json (current directory)
                           print           print a ready-to-copy mcpServers JSON snippet
                           none            do not register anywhere (just clone + deps)
                         Shorthands:
                           --all           same as: --targets auto,mcpjson-global

  --claude-scope SCOPE   Claude scope: user|project (default: user)
  --name NAME            MCP server name/key to register (default: phone-portal)

  --ui / --no-ui         Force interactive UI on/off (default: auto)
  -h, --help             Show this help

Environment variables (equivalents):
  PHONE_PORTAL_DIR, PHONE_PORTAL_REPO_URL, PHONE_PORTAL_BRANCH
  PHONE_PORTAL_TOKEN, PHONE_LINK_BRIDGE_URL, PHONE_LINK_RELAY_PORT,
  PHONE_LINK_RELAY_CLI, PHONE_LINK_RELAY_CMD
  PHONE_PORTAL_TARGETS, PHONE_PORTAL_CLAUDE_SCOPE, PHONE_PORTAL_MCP_NAME,
  PHONE_PORTAL_INTERACTIVE
EOF
}

# ── CLI args ────────────────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
  case "$1" in
    --install-dir|--dir) INSTALL_DIR="$2"; shift 2;;
    --repo) REPO_URL="$2"; shift 2;;
    --branch) REPO_BRANCH="$2"; shift 2;;

    --token) TOKEN="$2"; shift 2;;
    --bridge-url) BRIDGE_URL="$2"; shift 2;;
    --relay-port) RELAY_PORT="$2"; shift 2;;
    --relay-cli) RELAY_CLI="$2"; shift 2;;
    --relay-cmd) RELAY_CMD="$2"; shift 2;;

    --targets) TARGETS_CSV="$2"; shift 2;;
    --all) TARGETS_CSV="auto,mcpjson-global"; shift;;

    --claude-scope) CLAUDE_SCOPE="$2"; shift 2;;
    --name) MCP_NAME="$2"; shift 2;;

    --ui) INTERACTIVE="yes"; shift;;
    --no-ui) INTERACTIVE="no"; shift;;

    -h|--help) usage; exit 0;;
    *)
      printf "Unknown argument: %s\n\n" "$1" >&2
      usage
      exit 2
      ;;
  esac
done

# ── Bootstrap gum (optional in --no-ui mode) ────────────────────────────────
_have() { command -v "$1" >/dev/null 2>&1; }

_ensure_gum() {
  _have gum && return 0
  printf "  bootstrapping gum...\n"
  if _have brew; then
    brew install gum --quiet 2>/dev/null && return 0
  fi
  local os arch version tmpdir
  os=$(uname -s)    # Linux or Darwin
  arch=$(uname -m)  # x86_64 or arm64
  case "$arch" in aarch64) arch="arm64" ;; esac
  version=$(curl -fsSL "https://api.github.com/repos/charmbracelet/gum/releases/latest" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'].lstrip('v'))" 2>/dev/null \
    || echo "0.17.0")
  tmpdir=$(mktemp -d)
  curl -fsSL \
    "https://github.com/charmbracelet/gum/releases/download/v${version}/gum_${version}_${os}_${arch}.tar.gz" \
    | tar -xz -C "$tmpdir" --strip-components 1
  export PATH="$tmpdir:$PATH"
}

_is_tty() { [ -t 0 ] && [ -t 1 ]; }

if [ "$INTERACTIVE" != "no" ] && _is_tty; then
  _ensure_gum
fi

# ── UI helpers (gum if available, otherwise plain) ──────────────────────────
style_box() {
  if _have gum; then
    gum style \
      --border rounded \
      --border-foreground "$1" \
      --padding "1 3" \
      --margin "0 2" \
      "${@:2}"
  else
    printf "%s\n" "${@:2}"
  fi
}

step() { if _have gum; then gum style --bold --foreground 99 "  ▌ $1"; else printf "== %s\n" "$1"; fi; }
ok()   { if _have gum; then gum style --foreground 2 "  ✓ $1"; else printf "OK: %s\n" "$1"; fi; }
warn() { if _have gum; then gum style --foreground 3 "  ⚠ $1"; else printf "WARN: %s\n" "$1" >&2; fi; }
die()  { if _have gum; then gum style --foreground 1 --bold "  ✗ $1"; else printf "ERROR: %s\n" "$1" >&2; fi; printf "\n"; exit 1; }

run() {
  local t="$1"; shift
  if _have gum; then
    if gum spin --title "    $t" --spinner points -- "$@"; then
      return 0
    else
      gum style --faint "    $t"
      "$@"
    fi
  else
    printf "    %s\n" "$t"
    "$@"
  fi
}

# ── Interactive configuration ───────────────────────────────────────────────
_parse_targets() {
  local csv="$1"
  csv="${csv// /}"
  if [ -z "$csv" ]; then
    # Default = "install on all CLI agents" on this machine:
    # - register with detected CLIs (claude/codex)
    # - also write ~/.mcp.json for other MCP clients
    printf "%s\n" "auto"
    printf "%s\n" "mcpjson-global"
    return 0
  fi
  IFS=',' read -r -a _t <<<"$csv"
  for x in "${_t[@]}"; do
    [ -n "$x" ] && printf "%s\n" "$x"
  done
}

_pick_ui() {
  # Only if gum is present and in a TTY.
  _have gum || return 0
  _is_tty || return 0

  # If the user already provided explicit targets, don't override.
  if [ -n "$TARGETS_CSV" ]; then
    return 0
  fi

  printf "\n"
  style_box 99 \
    "$(gum style --bold '📱  phone-portal')" \
    "$(gum style --faint 'send files to any AI agent')" \
    "$(gum style --faint --foreground 99 "$REPO_URL")"
  printf "\n"

  step "Installer UI"
  INSTALL_DIR=$(gum input --prompt "Install dir: " --value "$INSTALL_DIR")

  # Token (masked) — allow blank to keep generated
  local tok
  tok=$(gum input --prompt "Token (blank = keep generated): " --password --value "")
  if [ -n "$tok" ]; then TOKEN="$tok"; fi

  RELAY_CLI=$(gum choose --header "Relay CLI" auto claude gemini llm ollama custom)
  if [ "$RELAY_CLI" = "custom" ]; then
    RELAY_CMD=$(gum input --prompt "Relay cmd template (use {prompt}): " --value "${RELAY_CMD:-llm -m gpt-4o {prompt}}")
  else
    RELAY_CMD="${RELAY_CMD:-}"
  fi

  local picks
  picks=$(gum choose --no-limit --header "Install/register for" \
    "Auto-detect CLIs (claude/codex) [auto]" \
    "Claude Code (CLI) [claude]" \
    "Codex (CLI) [codex]" \
    "Global ~/.mcp.json [mcpjson-global]" \
    "Current dir ./.mcp.json [mcpjson-here]" \
    "Print snippet only [print]" \
    "Do not register (clone + deps only) [none]" || true)

  if [ -z "$picks" ]; then
    TARGETS_CSV="auto"
  else
    TARGETS_CSV=$(printf "%s\n" "$picks" | sed -n 's/.*\[\(.*\)\].*/\1/p' | paste -sd, -)
  fi

  case ",${TARGETS_CSV}," in
    *,claude,*)
      CLAUDE_SCOPE=$(gum choose --header "Claude scope" user project)
      ;;
  esac

  ok "Selections saved"
  printf "\n"
}

if [ "$INTERACTIVE" = "yes" ]; then
  _ensure_gum
  _pick_ui
elif [ "$INTERACTIVE" = "auto" ]; then
  _pick_ui
fi

# ── Header (always, if gum is present) ──────────────────────────────────────
if _have gum; then
  printf "\n"
  gum style \
    --border rounded \
    --border-foreground 99 \
    --padding "1 3" \
    --margin "0 2" \
    "$(gum style --bold '📱  phone-portal')" \
    "$(gum style --faint 'send files to any AI agent')" \
    "$(gum style --faint --foreground 99 "$REPO_URL")"
  printf "\n"
fi

# ── Preflight ───────────────────────────────────────────────────────────────
step "Checking requirements"
_have git || die "git not found"
_have uv || die "uv not found — install: curl -LsSf https://astral.sh/uv/install.sh | sh"
_have python3 || die "python3 not found"
_have curl || die "curl not found"

if _have claude; then AVAILABLE_CLIENTS+=("claude"); fi
if _have codex; then AVAILABLE_CLIENTS+=("codex"); fi
if [ ${#AVAILABLE_CLIENTS[@]} -eq 0 ]; then
  warn "No supported MCP client CLIs found (claude/codex)."
  warn "Tip: use --targets mcpjson-global to write ~/.mcp.json for other MCP clients."
else
  ok "git · uv · ${AVAILABLE_CLIENTS[*]} — all present"
fi
printf "\n"

# ── Clone / update ─────────────────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
  step "Updating existing install"
  run "Fetching latest..." git -C "$INSTALL_DIR" fetch origin "$REPO_BRANCH"
  run "Applying updates..." git -C "$INSTALL_DIR" reset --hard -q "origin/$REPO_BRANCH"
  ok "Up to date"
else
  step "Cloning repository"
  run "Cloning..." git clone --quiet --branch "$REPO_BRANCH" "$REPO_URL" "$INSTALL_DIR"
  ok "Cloned to $INSTALL_DIR"
fi
printf "\n"

# ── Dependencies ───────────────────────────────────────────────────────────
step "Installing dependencies"
run "Running uv sync..." uv sync --project "$INSTALL_DIR" --quiet
ok "Dependencies ready"
printf "\n"

# ── Target actions ─────────────────────────────────────────────────────────
_register_claude() {
  _have claude || { warn "claude not found — skipping"; return 0; }
  step "Registering with Claude Code"

  if claude mcp get "$MCP_NAME" >/dev/null 2>&1; then
    warn "Existing entry found — replacing"
    claude mcp remove "$MCP_NAME" --scope "$CLAUDE_SCOPE" 2>/dev/null || \
    claude mcp remove "$MCP_NAME" 2>/dev/null || true
  fi

  # NB: Claude uses -e for env vars.
  claude mcp add "$MCP_NAME" \
    --scope "$CLAUDE_SCOPE" \
    -e PHONE_LINK_TOKEN="$TOKEN" \
    -e PHONE_LINK_BRIDGE_URL="$BRIDGE_URL" \
    -e PHONE_LINK_RELAY_PORT="$RELAY_PORT" \
    -e PHONE_LINK_RELAY_CLI="$RELAY_CLI" \
    -e PHONE_LINK_RELAY_CMD="$RELAY_CMD" \
    -- uv --directory "$INSTALL_DIR" run python mcp/phone_link_server.py

  ok "Registered with Claude Code ($CLAUDE_SCOPE scope)"
  REGISTERED_TARGETS+=("Claude Code")
}

_register_codex() {
  _have codex || { warn "codex not found — skipping"; return 0; }
  step "Registering with Codex"

  if codex mcp get "$MCP_NAME" >/dev/null 2>&1; then
    warn "Existing entry found — replacing"
    codex mcp remove "$MCP_NAME" 2>/dev/null || true
  fi

  codex mcp add "$MCP_NAME" \
    --env PHONE_LINK_TOKEN="$TOKEN" \
    --env PHONE_LINK_BRIDGE_URL="$BRIDGE_URL" \
    --env PHONE_LINK_RELAY_PORT="$RELAY_PORT" \
    --env PHONE_LINK_RELAY_CLI="$RELAY_CLI" \
    --env PHONE_LINK_RELAY_CMD="$RELAY_CMD" \
    -- uv --directory "$INSTALL_DIR" run python mcp/phone_link_server.py

  ok "Registered with Codex"
  REGISTERED_TARGETS+=("Codex")
}

_write_mcpjson() {
  # $1 path
  local target_path="$1"

  python3 - "$target_path" "$INSTALL_DIR" "$TOKEN" "$BRIDGE_URL" "$RELAY_PORT" "$RELAY_CLI" "$RELAY_CMD" "$MCP_NAME" <<'PY'
import json, os, sys

path, install_dir, token, bridge_url, relay_port, relay_cli, relay_cmd, name = sys.argv[1:]

cfg = {}
if os.path.exists(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            cfg = json.load(f) or {}
    except Exception:
        # If the file exists but isn't JSON, don't clobber it.
        raise SystemExit(f"Refusing to overwrite non-JSON file: {path}")

cfg.setdefault('mcpServers', {})
cfg['mcpServers'][name] = {
    'command': 'uv',
    'args': ['--directory', install_dir, 'run', 'python', 'mcp/phone_link_server.py'],
    'env': {
        'PHONE_LINK_TOKEN': token,
        'PHONE_LINK_BRIDGE_URL': bridge_url,
        'PHONE_LINK_RELAY_PORT': str(relay_port),
        'PHONE_LINK_RELAY_CLI': relay_cli,
        # Keep even if empty; some clients still want the key present.
        'PHONE_LINK_RELAY_CMD': relay_cmd,
    },
}

os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
with open(path, 'w', encoding='utf-8') as f:
    json.dump(cfg, f, indent=2)
    f.write('\n')

print(path)
PY
}

_register_mcpjson_global() {
  step "Writing ~/.mcp.json"
  local p="$HOME/.mcp.json"
  local wrote
  wrote=$(_write_mcpjson "$p")
  ok "Updated $wrote"
  REGISTERED_TARGETS+=("~/.mcp.json")
}

_register_mcpjson_here() {
  step "Writing ./.mcp.json"
  local p="$(pwd)/.mcp.json"
  local wrote
  wrote=$(_write_mcpjson "$p")
  ok "Updated $wrote"
  REGISTERED_TARGETS+=("./.mcp.json")
}

_print_snippet() {
  step "MCP config snippet"
  cat <<EOF
Add this to your MCP client's config (mcpServers):

"$MCP_NAME": {
  "command": "uv",
  "args": ["--directory", "$INSTALL_DIR", "run", "python", "mcp/phone_link_server.py"],
  "env": {
    "PHONE_LINK_TOKEN": "$TOKEN",
    "PHONE_LINK_BRIDGE_URL": "$BRIDGE_URL",
    "PHONE_LINK_RELAY_PORT": "$RELAY_PORT",
    "PHONE_LINK_RELAY_CLI": "$RELAY_CLI",
    "PHONE_LINK_RELAY_CMD": "$RELAY_CMD"
  }
}
EOF
  REGISTERED_TARGETS+=("printed snippet")
}

# Decide what to do
TARGETS=()
while IFS= read -r _line; do
  [ -n "${_line:-}" ] && TARGETS+=("$_line")
done < <(_parse_targets "$TARGETS_CSV")

# normalize convenience tokens
if printf "%s\n" "${TARGETS[@]}" | grep -Fxq "all"; then
  TARGETS=(auto mcpjson-global)
fi

# none means: skip all registration
if printf "%s\n" "${TARGETS[@]}" | grep -Fxq "none"; then
  TARGETS=()
fi

# auto expands to detected CLIs
if printf "%s\n" "${TARGETS[@]}" | grep -Fxq "auto"; then
  # remove 'auto'
  TARGETS=("${TARGETS[@]/auto/}")
  # strip empty entries
  TARGETS=($(printf "%s\n" "${TARGETS[@]}" | awk 'NF'))
  if _have claude; then TARGETS+=(claude); fi
  if _have codex; then TARGETS+=(codex); fi
fi

# de-dup targets (bash 3 compatible)
if [ ${#TARGETS[@]} -gt 0 ]; then
  TARGETS_UNIQ=()
  for x in "${TARGETS[@]}"; do
    [ -z "$x" ] && continue
    found=0
    for y in "${TARGETS_UNIQ[@]}"; do
      if [ "$y" = "$x" ]; then found=1; break; fi
    done
    [ $found -eq 0 ] && TARGETS_UNIQ+=("$x")
  done
  TARGETS=("${TARGETS_UNIQ[@]}")
fi

# Execute targets in a stable order
for t in claude codex mcpjson-global mcpjson-here print; do
  if printf "%s\n" "${TARGETS[@]}" | grep -Fxq "$t"; then
    case "$t" in
      claude) _register_claude ;;
      codex) _register_codex ;;
      mcpjson-global) _register_mcpjson_global ;;
      mcpjson-here) _register_mcpjson_here ;;
      print) _print_snippet ;;
    esac
    printf "\n"
  fi
done

# ── Detect relay CLI (nice label) ───────────────────────────────────────────
detected_cli=""
for c in claude gemini llm ollama; do
  if _have "$c"; then detected_cli="$c"; break; fi
done
relay_label="$RELAY_CLI"
[ "$RELAY_CLI" = "auto" ] && [ -n "$detected_cli" ] && relay_label="auto -> $detected_cli"

# ── Done ───────────────────────────────────────────────────────────────────
registered_label="${REGISTERED_TARGETS[*]:-none}"

style_box 2 \
  "$( _have gum && gum style --bold --foreground 2 '✓  Installation complete!' || printf '✓ Installation complete!' )" \
  "" \
  "install     ${INSTALL_DIR/$HOME/~}" \
  "token       ${TOKEN:0:20}.." \
  "relay       $relay_label" \
  "targets     $registered_label" \
  "" \
  "Restart your agent(s), then ask:" \
  "\"I want to send files from my phone\""

printf "\n"
