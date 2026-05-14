"""Tool handlers for the Hermes phone plugin."""

from __future__ import annotations

import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

try:
    import qrcode as _qrcode

    def _ascii_qr(url: str) -> str:
        qr = _qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        buf = io.StringIO()
        qr.print_ascii(out=buf, tty=False, invert=True)
        return buf.getvalue()

except ImportError:
    def _ascii_qr(url: str) -> str:
        return ""


BRIDGE_URL = (
    os.getenv("PHONE_LINK_BRIDGE_URL")
    or os.getenv("HERMES_IOS_BRIDGE_URL")
    or "http://127.0.0.1:8765"
).rstrip("/")


def _json_request(method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 35.0) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BRIDGE_URL}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - local/configured bridge
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8"))
        except Exception:
            detail = {"error": str(e)}
        return {"ok": False, "status": e.code, **detail}
    except Exception as e:
        return {"ok": False, "error": f"bridge request failed: {e}", "bridge_url": BRIDGE_URL}


def _agent_files_query(since_count: int = 0, since_uploaded_at: float = 0.0) -> str:
    query = urllib.parse.urlencode({"since_count": since_count, "since_uploaded_at": since_uploaded_at})
    return f"/api/agent/files?{query}"


def phone_begin_upload(args: dict, **kwargs) -> str:
    """One-shot start for the smartphone upload flow."""
    payload = _json_request("GET", "/api/agent/begin_upload")
    if not payload.get("ok"):
        return json.dumps(payload, ensure_ascii=False)
    files = payload.get("files") or []
    latest_uploaded_at = 0.0
    if files:
        latest_uploaded_at = max(float(item.get("uploaded_at") or 0.0) for item in files)
    url = payload.get("url") or ""
    return json.dumps(
        {
            "ok": True,
            "url": url,
            "qr_ascii": _ascii_qr(url),
            "qr_path": payload.get("qr_path"),
            "instructions": payload.get("instructions"),
            "existing_file_count": len(files),
            "latest_uploaded_at": latest_uploaded_at,
            "connected": payload.get("connected", False),
            "device": payload.get("device"),
            "existing_files": files,
        },
        ensure_ascii=False,
    )


def phone_link(args: dict, **kwargs) -> str:
    """Return the exact phone-upload link and short instructions."""
    meta = _json_request("GET", "/api/meta")
    if not meta.get("ok"):
        return json.dumps(meta, ensure_ascii=False)
    return json.dumps(
        {
            "ok": True,
            "url": meta.get("public_url"),
            "instructions": [
                "Open the exact http:// URL on your phone or tablet mobile browser.",
                "Upload files or paste text.",
                "Then ask Hermes to wait for files or read the latest file.",
            ],
        },
        ensure_ascii=False,
    )


def phone_wait_for_files(args: dict, **kwargs) -> str:
    """Poll until new phone files exist, then return the current file list."""
    timeout_seconds = max(1, min(int(args.get("timeout_seconds") or 120), 900))
    poll_interval_seconds = max(1, min(int(args.get("poll_interval_seconds") or 2), 30))
    min_files = max(1, min(int(args.get("min_files") or 1), 1000))
    since_count = max(0, int(args.get("since_count") or 0))
    since_uploaded_at = max(0.0, float(args.get("since_uploaded_at") or 0.0))
    deadline = time.time() + timeout_seconds

    last_status: dict[str, Any] | None = None
    while time.time() < deadline:
        last_status = _json_request("GET", _agent_files_query(since_count=since_count, since_uploaded_at=since_uploaded_at))
        if last_status.get("ok") and len(last_status.get("new_files") or []) >= min_files:
            return json.dumps(
                {
                    "ok": True,
                    "waited_seconds": round(timeout_seconds - max(0, deadline - time.time()), 1),
                    **last_status,
                },
                ensure_ascii=False,
            )
        time.sleep(poll_interval_seconds)

    return json.dumps(
        {
            "ok": False,
            "error": "timeout waiting for phone files",
            "timeout_seconds": timeout_seconds,
            "last_status": last_status,
        },
        ensure_ascii=False,
    )


def phone_status(args: dict, **kwargs) -> str:
    """Return bridge and phone connection status."""
    return json.dumps(_json_request("GET", "/api/agent/status"), ensure_ascii=False)


def phone_list_files(args: dict, **kwargs) -> str:
    """List files the user selected in the phone or tablet web companion."""
    return json.dumps(_json_request("GET", _agent_files_query()), ensure_ascii=False)


def phone_read_file(args: dict, **kwargs) -> str:
    """Ask the bridge to read a selected file."""
    file_id = str(args.get("file_id") or "").strip()
    if not file_id:
        return json.dumps({"ok": False, "error": "file_id is required"})
    max_bytes = int(args.get("max_bytes") or 200_000)
    result = _json_request(
        "POST",
        "/api/agent/command",
        {"name": "read_file", "args": {"file_id": file_id, "max_bytes": max_bytes}, "timeout": 45},
        timeout=50,
    )
    # Unwrap command envelope so callers see file fields directly.
    if result.get("ok") and "result" in result:
        return json.dumps(result["result"], ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


def phone_read_latest_file(args: dict, **kwargs) -> str:
    """Read the most recently uploaded phone file."""
    max_bytes = int(args.get("max_bytes") or 200_000)
    files = _json_request("GET", _agent_files_query())
    if not files.get("ok"):
        return json.dumps(files, ensure_ascii=False)
    file_list = files.get("files") or []
    if not file_list:
        return json.dumps({"ok": False, "error": "no uploaded files"}, ensure_ascii=False)
    latest = max(file_list, key=lambda item: float(item.get("uploaded_at") or 0.0))
    result = _json_request(
        "POST",
        "/api/agent/command",
        {"name": "read_file", "args": {"file_id": latest.get("id"), "max_bytes": max_bytes}, "timeout": 45},
        timeout=50,
    )
    return json.dumps(
        {
            "ok": True,
            "selected_file": latest,
            "result": result.get("result", result),
        },
        ensure_ascii=False,
    )


def phone_summary(args: dict, **kwargs) -> str:
    """Return a human-friendly summary for the agent."""
    status = _json_request("GET", "/api/agent/status")
    if not status.get("ok"):
        return json.dumps(status, ensure_ascii=False)
    device = status.get("device") or {}
    files = status.get("files") or []
    latest = None
    if files:
        latest = max(files, key=lambda item: float(item.get("uploaded_at") or 0.0))
    summary = {
        "ok": True,
        "connected": status.get("connected", False),
        "device": device,
        "file_count": status.get("file_count", 0),
        "latest_file": latest,
        "suggested_next": "phone_read_latest_file" if latest else "phone_begin_upload",
    }
    return json.dumps(summary, ensure_ascii=False)


def phone_create_zip(args: dict, **kwargs) -> str:
    """Create a zip bundle from current uploaded files."""
    name = str(args.get("name") or "").strip()
    payload = {"name": name} if name else {}
    result = _json_request("POST", "/api/agent/command", {"name": "create_zip", "args": payload, "timeout": 45}, timeout=50)
    return json.dumps(result, ensure_ascii=False)


def phone_send_text(args: dict, **kwargs) -> str:
    """Send text from agent to the phone display."""
    text = str(args.get("text") or "").strip()
    if not text:
        return json.dumps({"ok": False, "error": "text is required"})
    title = str(args.get("title") or "").strip()
    device_id = args.get("device_id")
    payload: dict[str, Any] = {"text": text, "title": title}
    if device_id:
        payload["device_id"] = device_id
    return json.dumps(_json_request("POST", "/api/agent/send_text", payload), ensure_ascii=False)


def phone_delete_file(args: dict, **kwargs) -> str:
    """Delete an uploaded file by id."""
    file_id = str(args.get("file_id") or "").strip()
    if not file_id:
        return json.dumps({"ok": False, "error": "file_id is required"})
    result = _json_request(
        "POST",
        "/api/agent/command",
        {"name": "delete_file", "args": {"file_id": file_id}, "timeout": 10},
        timeout=15,
    )
    return json.dumps(result, ensure_ascii=False)
