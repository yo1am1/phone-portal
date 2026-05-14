# phone-portal

Send files from iPhone/iPad to any AI agent. No Swift. No Xcode. FastAPI + Safari.

Scan a QR, open the page, upload files or paste text. Agent reads them instantly.

---

## How it works

1. Bridge starts on your machine, prints QR + LAN URL
2. Scan QR on phone → Safari opens with token prefilled
3. Upload files, paste text, or share directly from any iOS app (PWA)
4. Agent calls tools to read, process, delete files

---

## Structure

```
bridge/hermes_phone_bridge.py   FastAPI server, all API endpoints
mcp/phone_link_server.py        MCP server (Claude Code, Cursor, Windsurf, Continue)
plugin/ios_phone/               Hermes plugin (same 11 tools)
web/                            Safari UI (PWA, Share Target, dark theme)
data/                           Persisted uploads + state (gitignored)
```

---

## Run the bridge

```bash
uv sync
uv run python bridge/hermes_phone_bridge.py \
  --host 0.0.0.0 \
  --port 8765 \
  --token dev-token \
  --token-ttl-seconds 900 \
  --allow-subnet 192.168.0.0/16 \
  --webhook-url http://127.0.0.1:9000/webhook   # optional
```

Bridge prints QR in terminal and serves the UI on your LAN.

---

## MCP setup (Claude Code / Cursor / Windsurf / Continue)

`.mcp.json` is already in the repo root. Edit the env vars if needed:

```json
{
  "mcpServers": {
    "phone-link": {
      "command": "uv",
      "args": ["run", "python", "mcp/phone_link_server.py"],
      "env": {
        "PHONE_LINK_TOKEN": "dev-token",
        "PHONE_LINK_BRIDGE_URL": "http://127.0.0.1:8765"
      }
    }
  }
}
```

MCP server auto-starts the bridge on first use. QR code is returned inline in the agent conversation.

---

## Hermes plugin setup

```bash
mkdir -p ~/.hermes/plugins/ios_phone
cp plugin/ios_phone/*.py plugin/ios_phone/*.yaml ~/.hermes/plugins/ios_phone/
hermes plugins enable ios_phone
```

---

## Agent tools (11 total)

| Tool | What it does |
|------|-------------|
| `ios_phone_begin_upload` | Start upload flow — returns QR art + URL + baseline for wait |
| `ios_phone_link` | Get upload URL only |
| `ios_phone_wait_for_files` | Block until new files arrive (uses baseline to skip old ones) |
| `ios_phone_status` | Bridge + device connection status |
| `ios_phone_list_files` | List all uploaded files |
| `ios_phone_read_file` | Read file by id — text returns UTF-8, small binary returns base64, large binary (>100 KB) returns `storage_path` |
| `ios_phone_read_latest_file` | Read most recent upload without needing an id |
| `ios_phone_create_zip` | Bundle all uploads into a ZIP |
| `ios_phone_summary` | Human-friendly status + suggested next tool |
| `ios_phone_send_text` | Send a message from agent → phone display |
| `ios_phone_delete_file` | Delete uploaded file by id |

---

## Typical agent flow

```
User: "I want to send files from my phone"

1. ios_phone_begin_upload       → show QR + URL to user
2. user scans QR, uploads files
3. ios_phone_wait_for_files     → block until files arrive (pass baseline from step 1)
4. ios_phone_read_latest_file   → read content
5. ios_phone_delete_file        → clean up after processing
```

---

## Phone UI features

- File upload (multiple, up to 5 MB each)
- Text paste → saved as `.txt`
- Create ZIP bundle
- Per-file delete
- **PWA**: Add to Home Screen in Safari → standalone app icon
- **Web Share Target** (iOS 16.4+): share files directly from Photos, Files, or any app → Phone Portal
- Messages from agent displayed in "From Agent" section
- 6 collapsible sections, dark theme, 560 px max-width layout

---

## API reference

### Agent endpoints (no auth — localhost assumed)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agent/begin_upload` | Start flow, get URL + file baseline |
| `GET` | `/api/agent/status` | Connection + file status |
| `GET` | `/api/agent/files` | File list, supports `since_count` + `since_uploaded_at` |
| `POST` | `/api/agent/command` | Commands: `read_file`, `create_zip`, `delete_file` |
| `POST` | `/api/agent/send_text` | Send message to phone display |

### Web endpoints (token + IP auth)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/web/status` | Device status |
| `POST` | `/api/web/upload_bundle` | Upload batch (base64 JSON) |
| `POST` | `/api/web/paste` | Save pasted text |
| `POST` | `/api/web/zip` | Create ZIP |
| `POST` | `/api/web/clear` | Clear all files |
| `POST` | `/api/web/delete_file` | Delete one file |
| `POST` | `/api/web/messages` | Poll agent messages (clears on read) |
| `POST` | `/api/web/set_webhook` | Set server-side webhook URL |
| `POST` | `/api/web/share` | Web Share Target endpoint (multipart) |

### Other

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/manifest.webmanifest` | Dynamic PWA manifest (token embedded) |
| `GET` | `/sw.js` | Service worker |
| `GET` | `/icon.svg` | App icon |
| `GET` | `/qr.svg` | QR code as SVG |
| `GET` | `/health` | Health check |

---

## Limits

- 5 MB per file
- Large binary files (>100 KB): agent gets `storage_path` to use with Read tool instead of base64
- Files persisted to `data/` — survive bridge restart
- Token TTL enforced on web endpoints; agent endpoints are localhost-only
- LAN only — not designed for internet exposure
