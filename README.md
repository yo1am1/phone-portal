# phone-portal

Send files from any phone or tablet to any AI agent. No native app required. FastAPI + mobile browser.

Scan a QR, open the page, upload files or paste text. Agent reads them instantly.
Tap a suggestion chip → prompt fires to your AI CLI automatically.

---

## How it works

1. Start Claude Code (or any MCP-compatible agent) — bridge + relay boot automatically
2. Ask agent *"I want to send files from my phone"* → QR + URL appear inline
3. Scan QR on phone → upload files, paste text, or share from any app (PWA)
4. Agent reads, processes, deletes files via tools
5. Tap a suggestion chip on the phone → prompt fires to your AI CLI → answer appears on phone

---

## Structure

```
bridge/hermes_phone_bridge.py   FastAPI server, all API endpoints
mcp/phone_link_server.py        MCP server — auto-starts bridge + relay on launch
relay/example_relay.py          Prompt relay — receives chip taps, runs AI CLI, replies to phone
plugin/phone/                   Hermes plugin (same 11 tools)
web/                            Mobile browser UI (PWA, Share Target, dark theme)
data/                           Persisted uploads + state (gitignored)
```

---

## Install

```bash
curl -sSL https://raw.githubusercontent.com/yo1am1/phone-portal/main/install.sh | bash
```

Clones repo to `~/.phone-portal`, installs deps, registers MCP server with Claude Code (user scope — available in all projects). Restart Claude Code when done.

**Override defaults:**
```bash
PHONE_PORTAL_TOKEN=my-secret-token \
PHONE_LINK_RELAY_CLI=ollama \
  curl -sSL https://raw.githubusercontent.com/yo1am1/phone-portal/main/install.sh | bash
```

**Manual / local dev:**
```bash
git clone https://github.com/yo1am1/phone-portal
cd phone-portal
uv sync
claude mcp add phone-portal --scope user \
  -e PHONE_LINK_TOKEN=dev-token \
  -- uv --directory "$PWD" run python mcp/phone_link_server.py
```

→ **[Full testing guide: TESTING.md](TESTING.md)**

---

## MCP config reference

| Env var | Default | Description |
|---------|---------|-------------|
| `PHONE_LINK_TOKEN` | `dev-token` | Auth token for phone UI |
| `PHONE_LINK_BRIDGE_URL` | `http://127.0.0.1:8765` | Bridge address |
| `PHONE_LINK_RELAY_PORT` | `9001` | Relay server port |
| `PHONE_LINK_RELAY_CLI` | `auto` | AI CLI to use (see below) |
| `PHONE_LINK_RELAY_MODEL` | `llama3.2` | Model name (Ollama only) |
| `PHONE_LINK_RELAY_CMD` | _(none)_ | Custom command template |
| `PHONE_LINK_CLAUDE_TIMEOUT` | `120` | Relay subprocess timeout (s) |

---

## Prompt relay — supported CLIs

Relay auto-detects the first available CLI in PATH. Override with `PHONE_LINK_RELAY_CLI`.

| Value | Command used |
|-------|-------------|
| `auto` | First of: `claude → gemini → llm → ollama` found in PATH |
| `claude` | `claude -p "..."` (Claude Code) |
| `gemini` | `gemini "..."` (Google Gemini CLI) |
| `ollama` | `ollama run <model> "..."` |
| `llm` | `llm "..."` (Simon Willison's [llm](https://llm.datasette.io)) |
| `custom` | Set `PHONE_LINK_RELAY_CMD` to a template, e.g. `my-agent --input {prompt}` |

Custom example (any HTTP agent):
```json
"PHONE_LINK_RELAY_CMD": "llm -m gpt-4o {prompt}"
```

The relay fetches uploaded file context from the bridge, builds an enriched prompt
(file list + text content for small files), runs the CLI, and sends the response back
to the phone's **From Agent** section.

### One-time phone setup

After first `phone_begin_upload`, the agent prints:
```
Prompt relay running at: http://192.168.x.x:9001/prompt
In phone UI → Settings → Prompt Relay URL → set to the above URL (one-time setup).
```

Paste that URL into **Settings → Prompt Relay URL** on the phone. Saved in localStorage — never needed again.

---

## Running the bridge manually (without MCP)

```bash
uv run python bridge/hermes_phone_bridge.py \
  --host 0.0.0.0 \
  --port 8765 \
  --token dev-token \
  --token-ttl-seconds 900 \
  --allow-subnet 192.168.0.0/16 \
  --webhook-url http://127.0.0.1:9000/webhook   # optional
```

Running the relay manually:
```bash
uv run python relay/example_relay.py --cli claude
uv run python relay/example_relay.py --cli ollama --model llama3.2
uv run python relay/example_relay.py --cmd 'llm -m gpt-4o {prompt}'
```

---

## Hermes plugin setup

```bash
mkdir -p ~/.hermes/plugins/phone
cp plugin/phone/*.py plugin/phone/*.yaml ~/.hermes/plugins/phone/
hermes plugins enable phone
```

---

## Agent tools (11 total)

| Tool | What it does |
|------|-------------|
| `phone_begin_upload` | Start upload flow — shows QR + URL inline, returns baseline for wait |
| `phone_link` | Get upload URL only |
| `phone_wait_for_files` | Block until new files arrive (uses baseline to skip old ones) |
| `phone_status` | Bridge + device connection status |
| `phone_list_files` | List all uploaded files |
| `phone_read_file` | Read file by id — text → UTF-8, small binary → base64, large binary → `storage_path` |
| `phone_read_latest_file` | Read most recent upload without needing an id |
| `phone_create_zip` | Bundle all uploads into a ZIP |
| `phone_summary` | Human-friendly status + suggested next tool |
| `phone_send_text` | Send a message from agent → phone display |
| `phone_delete_file` | Delete uploaded file by id |

---

## Typical agent flow

```
User: "I want to send files from my phone"

1. phone_begin_upload       → QR + URL shown inline, baseline captured
2. user scans QR, uploads files on phone
3. phone_wait_for_files     → blocks until files arrive
4. phone_read_latest_file   → reads content
5. phone_send_text          → sends result back to phone display
6. phone_delete_file        → cleans up
```

---

## Phone UI features

- File upload (multiple files, up to 5 MB each)
- Text paste → saved as `.txt`
- Create ZIP bundle
- Per-file delete
- Suggestion chips — tap to fire prompt to AI CLI, answer appears in **From Agent**
- **PWA**: Add to Home Screen → standalone app icon
- **Web Share Target** (Android Chrome 86+, iOS 16.4+): share directly from Photos, Files, any app
- Messages from agent in **From Agent** section (polls every 6 s)
- 6 collapsible sections, dark theme, 560 px max-width

---

## API reference

### Agent endpoints (no auth — localhost assumed)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agent/begin_upload` | Start flow, get URL + file baseline |
| `GET` | `/api/agent/status` | Connection + file status |
| `GET` | `/api/agent/files` | File list — `?since_count=N&since_uploaded_at=T` |
| `POST` | `/api/agent/command` | Commands: `read_file`, `create_zip`, `delete_file` |
| `POST` | `/api/agent/send_text` | Send message to phone display |

### Web endpoints (token + IP auth)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/web/status` | Device status |
| `POST` | `/api/web/upload_bundle` | Batch upload (base64 JSON) |
| `POST` | `/api/web/paste` | Save pasted text |
| `POST` | `/api/web/zip` | Create ZIP |
| `POST` | `/api/web/clear` | Clear all files |
| `POST` | `/api/web/delete_file` | Delete one file |
| `POST` | `/api/web/messages` | Poll agent messages (clears on read) |
| `POST` | `/api/web/set_webhook` | Set server-side webhook URL |
| `POST` | `/api/web/share` | Web Share Target (multipart form) |

### Other

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/manifest.webmanifest` | Dynamic PWA manifest (token embedded) |
| `GET` | `/sw.js` | Service worker |
| `GET` | `/icon.svg` | App icon |
| `GET` | `/qr.svg` | QR code as SVG |
| `GET` | `/health` | Health check |

### Relay endpoint

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/prompt` | Receive prompt, run CLI, reply to phone |
| `GET` | `/health` | Reports active CLI |

---

## Limits

- 5 MB per file
- Large binary (>100 KB): agent gets `storage_path` to use with Read tool instead of base64
- Files persisted to `data/` — survive bridge restart
- Token TTL enforced on web endpoints; agent endpoints are localhost-only
- LAN only — not designed for internet exposure
