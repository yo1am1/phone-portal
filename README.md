# Phone Link Bridge

Small project. No Swift. No Xcode. FastAPI only.

Goal: scan QR on iPhone/iPad, open Safari page, send files or pasted text to your AI agent.

## What stays

- `bridge/hermes_phone_bridge.py` — FastAPI backend + API + QR
- `web/index.html` — frontend HTML
- `web/static/app.js` — frontend logic
- `web/static/styles.css` — frontend styles
- `plugin/ios_phone/` — Hermes plugin tools
- `data/` — persisted uploaded files and bridge state
- `pyproject.toml` — uv-managed deps
- `README.md` — how to run

## What it does

- Starts FastAPI server on your machine
- Prints LAN URL and QR on startup
- QR opens Safari with token prefilled
- Safari can:
  - upload files
  - paste text as a named `.txt` item
- Agent can:
  - `ios_phone_begin_upload`
  - `ios_phone_link`
  - `ios_phone_wait_for_files`
  - `ios_phone_read_latest_file`
  - `ios_phone_status`
  - `ios_phone_list_files`
  - `ios_phone_read_file`

## Run

```bash
cd /home/user/VS/foo/hermes-phone-link
uv sync
uv run python bridge/hermes_phone_bridge.py --host 0.0.0.0 --port 8765 --token dev-token --token-ttl-seconds 900 --allow-subnet 192.168.0.0/16
```

Bridge prints QR in terminal and serves page on your LAN.
Frontend is split into separate HTML/CSS/JS files so browser-side issues are easier to debug.

## Best agent flow

When user says: `I want to send files from the smartphone`

1. Agent calls `ios_phone_begin_upload`
2. Hermes shows the exact returned `http://...` URL
3. User opens Safari and uploads/pastes content
4. Agent calls `ios_phone_wait_for_files` with the baseline from step 1
5. Agent calls `ios_phone_read_latest_file` for one obvious upload
6. If multiple files matter, Hermes uses `ios_phone_list_files` and `ios_phone_read_file`

## Phone flow

1. Scan QR from terminal.
2. Safari opens bridge page.
3. Token auto-fills from QR.
4. Upload files or paste text.
5. Ask your agent to use the uploaded item.

If QR scan fails, open the printed URL manually in Safari. Keep the explicit `http://` prefix.

## Install plugin into an agent

```bash
Example (Hermes):

mkdir -p ~/.hermes/plugins/ios_phone
cp plugin/ios_phone/*.py plugin/ios_phone/*.yaml ~/.hermes/plugins/ios_phone/
hermes plugins enable ios_phone

For other agents, wire the HTTP endpoints directly (see API below).
```

Then restart Hermes or start a new session.

## Example asks to Hermes

- `I want to send files from the smartphone`
- `Wait for my upload from the phone`
- `Read the latest file from my phone`
- `List phone files`

## Limits

- Persisted to disk under `data/`
- Restart keeps uploaded items
- About 5 MB per item
- Trusted LAN only
- Read-only from Hermes side

## Why no Bluetooth

Bluetooth bad MVP.
- more pain
- less debug
- worse throughput
- more permissions

LAN + Safari simpler. Works now.

## New UX features

- Upload bundle endpoint (faster batch upload).
- Create ZIP bundle from uploaded files (UI + agent tool).
- Token TTL + IP allowlist for safer LAN use.
- ios_phone_summary tool for quick agent status.


## API (agent-agnostic)

Key endpoints:
- GET /api/agent/status
- GET /api/agent/files
- POST /api/agent/command (read_file, create_zip)
- GET /api/agent/begin_upload

Web endpoints (Safari UI):
- POST /api/web/status
- POST /api/web/upload_bundle
- POST /api/web/paste
- POST /api/web/zip
- POST /api/web/clear

Any agent can call these with HTTP requests.

