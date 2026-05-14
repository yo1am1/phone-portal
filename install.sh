#!/usr/bin/env bash
# phone-portal installer
# Usage: curl -sSL https://raw.githubusercontent.com/yo1am1/phone-portal/main/install.sh | bash
set -euo pipefail

INSTALL_DIR="${PHONE_PORTAL_DIR:-$HOME/.phone-portal}"
TOKEN="${PHONE_PORTAL_TOKEN:-$(openssl rand -hex 16 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(16))')}"
RELAY_CLI="${PHONE_LINK_RELAY_CLI:-auto}"

# ── 1. clone / update ─────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "[phone-portal] Updating $INSTALL_DIR …"
  git -C "$INSTALL_DIR" pull --ff-only
else
  echo "[phone-portal] Installing to $INSTALL_DIR …"
  git clone https://github.com/yo1am1/phone-portal "$INSTALL_DIR"
fi

# ── 2. install deps ───────────────────────────────────────────
echo "[phone-portal] Installing dependencies …"
uv sync --project "$INSTALL_DIR" --quiet

# ── 3. register MCP server (user scope = available everywhere) ─
echo "[phone-portal] Registering MCP server with Claude Code …"
claude mcp add phone-portal \
  --scope user \
  -e PHONE_LINK_TOKEN="$TOKEN" \
  -e PHONE_LINK_BRIDGE_URL="http://127.0.0.1:8765" \
  -e PHONE_LINK_RELAY_PORT="9001" \
  -e PHONE_LINK_RELAY_CLI="$RELAY_CLI" \
  -- uv --directory "$INSTALL_DIR" run python mcp/phone_link_server.py

# ── done ──────────────────────────────────────────────────────
cat <<EOF

[phone-portal] Done.

  Install dir : $INSTALL_DIR
  Token       : $TOKEN
  Relay CLI   : $RELAY_CLI (auto = first of claude/gemini/llm/ollama found in PATH)

Restart Claude Code, then ask:
  "I want to send files from my phone"

To change token or relay CLI later, edit:
  claude mcp edit phone-portal
EOF
