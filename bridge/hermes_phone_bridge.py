#!/usr/bin/env python3
"""Phone Link bridge.

FastAPI backend for phone or tablet mobile browser uploads.
Frontend assets live under web/.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import secrets
import socket
import subprocess
import threading
import time
import ipaddress
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import qrcode
import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from qrcode.image.svg import SvgPathImage

MAX_UPLOAD_BYTES = 5_000_000
BINARY_INLINE_MAX_BYTES = 100_000
DEFAULT_WEB_DEVICE_NAME = "Mobile Companion"
BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
STATIC_DIR = WEB_DIR / "static"
INDEX_FILE = WEB_DIR / "index.html"
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
STATE_FILE = DATA_DIR / "state.json"


def _resolve_storage_path(storage_path: str) -> Path | None:
    """Resolve stored path (relative filename or legacy absolute path) to absolute Path."""
    if not storage_path:
        return None
    p = Path(storage_path)
    if p.is_absolute():
        return p  # backward compat: old state.json entries
    return UPLOADS_DIR / p


@dataclass
class DeviceState:
    device_id: str
    name: str
    files: list[dict[str, Any]] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)
    outbox: list[dict[str, Any]] = field(default_factory=list)
    # uploaded_data removed — files read from disk on demand to prevent memory leak


class BridgeState:
    def __init__(
        self,
        token: str,
        public_url: str,
        allow_subnets: list[str] | None = None,
        token_ttl_seconds: float | None = None,
        webhook_url: str | None = None,
    ):
        self.token = token
        self.public_url = public_url
        self.allow_subnets = allow_subnets or []
        self.token_ttl_seconds = token_ttl_seconds
        self.token_created_at = time.time()
        self.webhook_url = webhook_url
        self.devices: dict[str, DeviceState] = {}
        self._lock = threading.RLock()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        self._load_from_disk()

    def allowlist_ok(self, client_host: str | None) -> bool:
        if not self.allow_subnets:
            return True
        if not client_host:
            return False
        try:
            ip = ipaddress.ip_address(client_host)
        except ValueError:
            return False
        for cidr in self.allow_subnets:
            try:
                if ip in ipaddress.ip_network(cidr, strict=False):
                    return True
            except ValueError:
                continue
        return False

    def authenticate(self, token: str | None) -> bool:
        if not token or not secrets.compare_digest(token, self.token):
            return False
        if self.token_ttl_seconds is not None:
            if time.time() - self.token_created_at > self.token_ttl_seconds:
                return False
        return True

    def get_device(self, device_id: str | None = None) -> DeviceState | None:
        if device_id:
            return self.devices.get(device_id)
        if not self.devices:
            return None
        return max(self.devices.values(), key=lambda d: d.last_seen)

    def get_or_create_web_device(self, session_id: str) -> DeviceState:
        with self._lock:
            device_id = f"web-{session_id}"
            device = self.devices.get(device_id)
            if device is None:
                device = DeviceState(device_id=device_id, name=DEFAULT_WEB_DEVICE_NAME)
                self.devices[device_id] = device
            device.last_seen = time.time()
            self._save_to_disk()
            return device

    def upsert_file(self, device: DeviceState, *, name: str, mime_type: str, data: bytes) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            file_id = secrets.token_hex(10)
            ext = Path(name).suffix.lower() or ".bin"
            file_path = UPLOADS_DIR / f"{file_id}{ext}"
            file_path.write_bytes(data)
            meta = {
                "id": file_id,
                "name": name,
                "size": len(data),
                "type": mime_type,
                "uploaded_at": now,
                "storage_path": file_path.name,  # relative: filename only, no absolute path
            }
            device.files = [item for item in device.files if item.get("name") != name]
            device.files.append(meta)
            device.files.sort(key=lambda item: float(item.get("uploaded_at") or 0.0))
            device.last_seen = now
            self._save_to_disk()
            return meta

    def clear_device(self, device: DeviceState) -> None:
        with self._lock:
            for item in device.files:
                path = _resolve_storage_path(item.get("storage_path", ""))
                if path:
                    try:
                        path.unlink(missing_ok=True)
                    except Exception:
                        pass
            device.files = []
            device.last_seen = time.time()
            self._save_to_disk()

    def fire_webhook(self, event: str, payload: dict) -> None:
        if not self.webhook_url:
            return

        def _post():
            try:
                data = json.dumps({"event": event, "timestamp": time.time(), **payload}).encode()
                req = urllib.request.Request(
                    self.webhook_url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass

        threading.Thread(target=_post, daemon=True).start()

    def _load_from_disk(self) -> None:
        if not STATE_FILE.exists():
            return
        try:
            raw = STATE_FILE.read_text().strip()
            if not raw:
                return
            payload = json.loads(raw)
        except Exception as exc:
            print(f"[bridge] Warning: could not load state.json: {exc}", flush=True)
            return
        for raw_device in payload.get("devices", []):
            device = DeviceState(
                device_id=raw_device.get("device_id", "unknown"),
                name=raw_device.get("name", DEFAULT_WEB_DEVICE_NAME),
                last_seen=float(raw_device.get("last_seen") or time.time()),
            )
            for item in raw_device.get("files", []):
                storage_path = item.get("storage_path")
                if not storage_path:
                    continue
                path = _resolve_storage_path(storage_path)
                if not path or not path.exists():
                    continue
                try:
                    size = path.stat().st_size
                except Exception:
                    continue
                item = dict(item)
                item["size"] = size
                item["storage_path"] = path.name  # normalise to relative on load
                device.files.append(item)
            device.files.sort(key=lambda entry: float(entry.get("uploaded_at") or 0.0))
            self.devices[device.device_id] = device

    def _save_to_disk(self) -> None:
        """Atomic write via temp file + os.replace to prevent partial writes on crash."""
        payload = {
            "devices": [
                {
                    "device_id": device.device_id,
                    "name": device.name,
                    "last_seen": device.last_seen,
                    "files": device.files,
                }
                for device in self.devices.values()
            ]
        }
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        os.replace(tmp, STATE_FILE)


class WebBase(BaseModel):
    session_id: str
    token: str


class UploadItem(BaseModel):
    name: str
    mime_type: str = "application/octet-stream"
    size: int = 0
    base64: str


class UploadBody(WebBase):
    name: str
    mime_type: str = "application/octet-stream"
    size: int = 0
    base64: str


class UploadBundle(WebBase):
    files: list[UploadItem]


class ZipBody(WebBase):
    name: str | None = None


class PasteBody(WebBase):
    name: str
    text: str


class AgentCommandBody(BaseModel):
    device_id: str | None = None
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    timeout: float = 45.0


class SendTextBody(BaseModel):
    text: str
    title: str = ""
    device_id: str | None = None


class SetWebhookBody(BaseModel):
    session_id: str
    token: str
    webhook_url: str


class DeleteFileBody(BaseModel):
    session_id: str
    token: str
    file_id: str


STATE: BridgeState
app = FastAPI()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def detect_lan_ip() -> str:
    try:
        result = subprocess.run(
            ["ip", "route", "get", "1.1.1.1"],
            capture_output=True,
            text=True,
            check=False,
        )
        parts = result.stdout.split()
        if "src" in parts:
            return parts[parts.index("src") + 1]
    except Exception:
        pass

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip:
            return ip
    except Exception:
        pass

    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass

    return "127.0.0.1"


def build_public_url(host: str, port: int, token: str) -> str:
    display_host = host
    if host in {"0.0.0.0", "::"}:
        display_host = detect_lan_ip()
    safe_token = quote(token)
    return f"http://{display_host}:{port}/?token={safe_token}"


def public_url_redacted(url: str) -> str:
    token_marker = "token="
    if token_marker not in url:
        return url
    prefix, token = url.split(token_marker, 1)
    return prefix + token_marker + "***"


def make_qr_svg(data: str) -> bytes:
    image = qrcode.make(data, image_factory=SvgPathImage, box_size=10, border=4)
    return image.to_string(encoding="unicode").encode("utf-8")


def print_terminal_qr(data: str) -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(data)
    qr.make(fit=True)
    buf = io.StringIO()
    qr.print_ascii(out=buf, tty=False, invert=True)
    print(buf.getvalue())


def current_summary(device: DeviceState | None) -> dict[str, Any]:
    if not device:
        return {"connected": False, "device": None, "files": [], "file_count": 0}
    return {
        "connected": True,
        "device": {
            "id": device.device_id,
            "name": device.name,
            "last_seen": device.last_seen,
            "file_count": len(device.files),
        },
        "files": device.files,
        "file_count": len(device.files),
    }


def create_zip_for_device(device: DeviceState, name: str | None = None) -> dict[str, Any]:
    if not device.files:
        return {"ok": False, "error": "no files to zip"}
    zip_name = name.strip() if name else f"bundle-{int(time.time())}.zip"
    if not zip_name.lower().endswith('.zip'):
        zip_name += '.zip'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in device.files:
            storage_path = item.get("storage_path", "")
            path = _resolve_storage_path(storage_path)
            if not path or not path.exists():
                continue
            try:
                data = path.read_bytes()
            except Exception:
                continue
            arcname = item.get("name") or item.get("id", "file")
            zf.writestr(arcname, data)
    data = buffer.getvalue()
    return {"ok": True, "file": STATE.upsert_file(device, name=zip_name, mime_type="application/zip", data=data)}


def handle_local_read(device: DeviceState, args: dict[str, Any]) -> dict[str, Any]:
    file_id = str(args.get("file_id") or "").strip()
    if not file_id:
        return {"ok": False, "error": "file_id is required"}

    meta = next((f for f in device.files if f.get("id") == file_id), None)
    if meta is None:
        return {"ok": False, "error": "file not found"}

    storage_path_str = meta.get("storage_path", "")
    path = _resolve_storage_path(storage_path_str)
    if not path or not path.exists():
        return {"ok": False, "error": "file data not found on disk"}

    try:
        data = path.read_bytes()
    except Exception as exc:
        return {"ok": False, "error": f"could not read file: {exc}"}

    max_bytes = max(1, min(int(args.get("max_bytes") or 200_000), 2_000_000))
    abs_path = str(path)

    payload: dict[str, Any] = {
        "ok": True,
        "id": file_id,
        "name": meta.get("name"),
        "size": meta.get("size", len(data)),
        "type": meta.get("type"),
        "uploaded_at": meta.get("uploaded_at"),
        "storage_path": abs_path,
    }

    try:
        payload["encoding"] = "utf8"
        payload["text"] = data[:max_bytes].decode("utf-8")
        payload["truncated"] = len(data) > max_bytes
        return payload
    except UnicodeDecodeError:
        pass

    if len(data) <= BINARY_INLINE_MAX_BYTES:
        payload["encoding"] = "base64"
        payload["base64"] = base64.b64encode(data[:max_bytes]).decode("ascii")
        payload["truncated"] = len(data) > max_bytes
    else:
        payload["encoding"] = "binary"
        payload["inline"] = False
        payload["read_hint"] = (
            f"Binary file too large to inline ({len(data):,} bytes). "
            f"Use the Read tool directly on storage_path: {abs_path}"
        )

    return payload


def _delete_file_from_device(device: DeviceState, file_id: str) -> bool:
    """Remove file from device.files and disk. Returns True if found."""
    target = next((f for f in device.files if f.get("id") == file_id), None)
    if not target:
        return False
    path = _resolve_storage_path(target.get("storage_path", ""))
    if path:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
    device.files = [f for f in device.files if f.get("id") != file_id]
    return True


def require_token(token: str, request: Request) -> None:
    if not STATE.authenticate(token):
        raise HTTPException(status_code=401, detail="bad token")
    client_host = request.client.host if request.client else None
    if not STATE.allowlist_ok(client_host):
        raise HTTPException(status_code=403, detail="client not allowed")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(INDEX_FILE)


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    return {"ok": True, "public_url": STATE.public_url, "public_url_redacted": public_url_redacted(STATE.public_url)}


@app.get("/qr.svg")
def qr_svg() -> Response:
    return Response(content=make_qr_svg(STATE.public_url), media_type="image/svg+xml")


@app.get("/icon.svg")
def icon_svg() -> Response:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect width="100" height="100" rx="22" fill="#5b8cff"/>'
        '<rect x="32" y="18" width="36" height="64" rx="6" fill="white" opacity="0.95"/>'
        '<rect x="40" y="24" width="20" height="4" rx="2" fill="#5b8cff" opacity="0.5"/>'
        '<rect x="36" y="34" width="28" height="28" rx="3" fill="#0b1020"/>'
        '<circle cx="50" cy="72" r="4" fill="#5b8cff"/>'
        '<path d="M43 48 L50 40 L57 48" fill="none" stroke="#5b8cff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
        '<line x1="50" y1="40" x2="50" y2="58" stroke="#5b8cff" stroke-width="2.5" stroke-linecap="round"/>'
        '</svg>'
    )
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/manifest.webmanifest")
def web_manifest() -> Response:
    manifest = {
        "name": "Phone Link Bridge",
        "short_name": "Phone Link",
        "start_url": f"/?token={quote(STATE.token)}",
        "display": "standalone",
        "background_color": "#0b1020",
        "theme_color": "#5b8cff",
        "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}],
        "share_target": {
            "action": f"/api/web/share?token={quote(STATE.token)}",
            "method": "POST",
            "enctype": "multipart/form-data",
            "params": {
                "title": "title",
                "text": "text",
                "url": "url",
                "files": [{"name": "files", "accept": ["*/*"]}],
            },
        },
    }
    return Response(content=json.dumps(manifest), media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "devices": len(STATE.devices),
        "public_url": public_url_redacted(STATE.public_url),
        "storage_dir": str(DATA_DIR),
        "allow_subnets": STATE.allow_subnets,
        "token_ttl_seconds": STATE.token_ttl_seconds,
    }


@app.post("/api/web/status")
def web_status(body: WebBase, request: Request) -> dict[str, Any]:
    require_token(body.token, request)
    device = STATE.get_or_create_web_device(body.session_id)
    return {"ok": True, **current_summary(device)}


@app.post("/api/web/upload")
def web_upload(body: UploadBody, request: Request) -> dict[str, Any]:
    require_token(body.token, request)
    try:
        data = base64.b64decode(body.base64, validate=True)
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"invalid base64 payload: {error}") from error

    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail=f"file too large; max {MAX_UPLOAD_BYTES} bytes")

    device = STATE.get_or_create_web_device(body.session_id)
    meta = STATE.upsert_file(device, name=body.name, mime_type=body.mime_type, data=data)
    STATE.fire_webhook("upload", {"file_count": 1})
    return {"ok": True, "file": meta}


@app.post("/api/web/upload_bundle")
def web_upload_bundle(body: UploadBundle, request: Request) -> dict[str, Any]:
    require_token(body.token, request)
    device = STATE.get_or_create_web_device(body.session_id)
    saved = []
    for item in body.files:
        try:
            data = base64.b64decode(item.base64, validate=True)
        except Exception as error:
            raise HTTPException(status_code=400, detail=f"invalid base64 payload: {error}") from error
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail=f"file too large; max {MAX_UPLOAD_BYTES} bytes")
        meta = STATE.upsert_file(device, name=item.name, mime_type=item.mime_type, data=data)
        saved.append(meta)
    STATE.fire_webhook("upload_bundle", {"file_count": len(saved)})
    return {"ok": True, "files": saved}


@app.post("/api/web/zip")
def web_zip(body: ZipBody, request: Request) -> dict[str, Any]:
    require_token(body.token, request)
    device = STATE.get_or_create_web_device(body.session_id)
    result = create_zip_for_device(device, body.name)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "zip failed"))
    STATE.fire_webhook("zip", {"file_count": 1})
    return result


@app.post("/api/web/paste")
def web_paste(body: PasteBody, request: Request) -> dict[str, Any]:
    require_token(body.token, request)
    text = body.text or ""
    data = text.encode("utf-8")
    if not text.strip():
        raise HTTPException(status_code=400, detail="empty text")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail=f"text too large; max {MAX_UPLOAD_BYTES} bytes")

    device = STATE.get_or_create_web_device(body.session_id)
    name = body.name.strip() or "pasted.txt"
    meta = STATE.upsert_file(device, name=name, mime_type="text/plain; charset=utf-8", data=data)
    STATE.fire_webhook("paste", {"file_count": 1})
    return {"ok": True, "file": meta}


@app.post("/api/web/clear")
def web_clear(body: WebBase, request: Request) -> dict[str, Any]:
    require_token(body.token, request)
    device = STATE.get_or_create_web_device(body.session_id)
    STATE.clear_device(device)
    return {"ok": True}


@app.post("/api/web/set_webhook")
def web_set_webhook(body: SetWebhookBody, request: Request) -> dict[str, Any]:
    if not STATE.authenticate(body.token):
        raise HTTPException(status_code=401, detail="bad token")
    STATE.webhook_url = body.webhook_url
    return {"ok": True}


@app.post("/api/web/messages")
def web_messages(body: WebBase, request: Request) -> dict[str, Any]:
    require_token(body.token, request)
    device = STATE.get_or_create_web_device(body.session_id)
    with STATE._lock:
        messages = list(device.outbox)
        device.outbox = []
    return {"ok": True, "messages": messages}


@app.post("/api/web/delete_file")
def web_delete_file(body: DeleteFileBody, request: Request) -> dict[str, Any]:
    if not STATE.authenticate(body.token):
        raise HTTPException(status_code=401, detail="bad token")
    device = STATE.get_or_create_web_device(body.session_id)
    with STATE._lock:
        found = _delete_file_from_device(device, body.file_id)
        if not found:
            raise HTTPException(status_code=404, detail="file not found")
        STATE._save_to_disk()
    return {"ok": True, "deleted": body.file_id}


@app.post("/api/web/share")
async def web_share(
    token: str = Query(...),
    title: str = Form(default=""),
    text: str = Form(default=""),
    url: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
) -> RedirectResponse:
    if not STATE.authenticate(token):
        raise HTTPException(status_code=401, detail="bad token")
    device = STATE.get_or_create_web_device("share-target")
    saved_files = []
    for upload in files:
        data = await upload.read()
        if len(data) > MAX_UPLOAD_BYTES:
            continue
        name = upload.filename or "shared-file"
        mime = upload.content_type or "application/octet-stream"
        meta = STATE.upsert_file(device, name=name, mime_type=mime, data=data)
        saved_files.append(meta)
    if not saved_files and text:
        name = (title.strip() or "shared-text") + ".txt"
        data = text.encode("utf-8")
        if len(data) <= MAX_UPLOAD_BYTES:
            meta = STATE.upsert_file(device, name=name, mime_type="text/plain; charset=utf-8", data=data)
            saved_files.append(meta)
    STATE.fire_webhook("share", {"file_count": len(saved_files)})
    return RedirectResponse(url=f"/?token={quote(STATE.token)}&shared=1", status_code=303)


@app.get("/api/agent/begin_upload")
def agent_begin_upload() -> dict[str, Any]:
    device = STATE.get_device()
    summary = current_summary(device)
    return {
        "ok": True,
        "url": STATE.public_url,
        "qr_path": "/qr.svg",
        "instructions": [
            "Open the exact http:// URL on your phone or tablet mobile browser.",
            "Upload files or paste text.",
            "Return to your agent after upload, or let Hermes wait for new files.",
        ],
        **summary,
    }


@app.get("/api/agent/status")
def agent_status() -> dict[str, Any]:
    device = STATE.get_device()
    return {"ok": True, **current_summary(device)}


@app.get("/api/agent/files")
def agent_files(since_count: int = Query(default=0), since_uploaded_at: float = Query(default=0.0)) -> JSONResponse:
    device = STATE.get_device()
    if not device:
        return JSONResponse(status_code=404, content={"ok": False, "error": "no device connected"})
    files = device.files
    new_files = [
        item for idx, item in enumerate(files)
        if idx >= since_count and float(item.get("uploaded_at") or 0.0) > since_uploaded_at
    ]
    return JSONResponse(
        content={
            "ok": True,
            "device_id": device.device_id,
            "files": files,
            "new_files": new_files,
            "file_count": len(files),
        }
    )


@app.post("/api/agent/command")
def agent_command(body: AgentCommandBody) -> JSONResponse:
    device = STATE.get_device(body.device_id)
    if not device:
        return JSONResponse(status_code=404, content={"ok": False, "error": "no device connected"})
    if body.name == "read_file":
        return JSONResponse(content={"ok": True, "result": handle_local_read(device, body.args)})
    if body.name == "create_zip":
        result = create_zip_for_device(device, body.args.get("name"))
        return JSONResponse(content=result)
    if body.name == "delete_file":
        file_id = str(body.args.get("file_id") or "").strip()
        if not file_id:
            return JSONResponse(content={"ok": False, "error": "file_id required"})
        with STATE._lock:
            found = _delete_file_from_device(device, file_id)
            if not found:
                return JSONResponse(content={"ok": False, "error": "file not found"})
            STATE._save_to_disk()
        return JSONResponse(content={"ok": True, "deleted": file_id})
    return JSONResponse(status_code=400, content={"ok": False, "error": f"unsupported command: {body.name}"})


@app.post("/api/agent/send_text")
def agent_send_text(body: SendTextBody) -> dict[str, Any]:
    device = STATE.get_device(body.device_id)
    if not device:
        raise HTTPException(status_code=404, detail="no device connected")
    message = {
        "id": secrets.token_hex(8),
        "title": body.title,
        "text": body.text,
        "sent_at": time.time(),
    }
    with STATE._lock:
        device.outbox.append(message)
    return {"ok": True, "message": message}


def main() -> None:
    parser = argparse.ArgumentParser(description="Phone Link bridge")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default="dev-token")
    parser.add_argument("--token-ttl-seconds", type=float, default=None)
    parser.add_argument("--allow-subnet", action="append", default=[])
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--webhook-url", default=None)
    args = parser.parse_args()

    public_url = build_public_url(args.host, args.port, args.token)

    global STATE
    STATE = BridgeState(
        token=args.token,
        public_url=public_url,
        allow_subnets=args.allow_subnet,
        token_ttl_seconds=args.token_ttl_seconds,
        webhook_url=args.webhook_url,
    )

    print(f"Phone Link bridge listening on http://{args.host}:{args.port}")
    print(f"Open on phone: {public_url}")
    print("Scan this QR:")
    print_terminal_qr(public_url)
    print(f"Persistent storage: {DATA_DIR}")
    print("Frontend split into web/ and web/static/.")

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
