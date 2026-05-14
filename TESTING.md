# Testing phone-portal

End-to-end test path. Takes ~5 minutes.

---

## Install (one command)

```bash
curl -sSL https://raw.githubusercontent.com/yo1am1/phone-portal/main/install.sh | bash
```

Then **restart Claude Code**.

---

## 1. Bridge + relay start

Ask Claude Code:
> *"what is my phone portal status?"*

Expected: Claude calls `phone_status`, returns connected/disconnected info.
If it errors — MCP server did not start. Run `claude mcp list` to verify `phone-portal` is registered.

---

## 2. Connect phone (same WiFi)

Ask:
> *"I want to send files from my phone"*

Expected:
- QR code rendered inline in conversation
- Upload URL like `http://192.168.x.x:8765/?token=...`
- Relay URL printed: `http://192.168.x.x:9001/prompt`

Scan QR on phone → browser opens → hit **Connect**.
Status pill goes green.

---

## 3. Upload a file

On phone — **Files** tab → choose any file → **Upload**.

Back in Claude Code:
> *"list my phone files"*

Expected: file appears with name, size, type.

---

## 4. Read the file

> *"read the latest file from my phone"*

Expected:
- Text files → content shown directly
- Images → `storage_path` returned, agent reads via Read tool

---

## 5. Test paste

On phone — **Text** tab → type something → **Send Text**.

> *"summarize the latest file from my phone"*

Expected: summary of pasted text.

---

## 6. Test suggestion chips (relay)

**One-time setup** (only if not done):
- Copy relay URL from step 2
- Phone UI → **Settings** → **Prompt Relay URL** → paste → **Save Relay URL**

Upload any file. Scroll to **Files** section. Tap any suggestion chip (e.g. *"Summarize the latest file."*).

Expected:
- Chip shows ⏳ Sending…
- After a few seconds: answer appears in **From Agent** section on phone

---

## 7. Test delete

> *"delete all phone files"*

Expected: Claude calls `phone_delete_file` per file, list empties.

---

## 8. Test ZIP

Upload 2+ files, then:
> *"zip my phone files"*

Expected: zip file appears in file list.

---

## 9. Test PWA install (optional)

**Android Chrome**: menu → *Add to Home Screen*
**iOS Safari**: share → *Add to Home Screen*

After install: go to phone home screen, open Phone Portal icon → standalone app.
Share a photo from Photos app → should offer *Phone Portal* as destination (Android Chrome 86+ / iOS 16.4+).

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| MCP not found | `claude mcp list` — verify `phone-portal` is registered |
| Bridge not starting | `uv run python bridge/hermes_phone_bridge.py --port 8765 --token dev-token` manually, check errors |
| Phone can't reach bridge | Same WiFi? Try `http://192.168.x.x:8765/health` in phone browser |
| Token rejected | Token in URL must match `PHONE_LINK_TOKEN` in MCP config |
| Relay not responding | `curl http://127.0.0.1:9001/health` — check CLI is installed and in PATH |
| Chip tap does nothing | Relay URL not set in phone Settings, or relay URL uses `127.0.0.1` (use LAN IP instead) |
| Share Target missing | PWA must be installed (Add to Home Screen) first |
