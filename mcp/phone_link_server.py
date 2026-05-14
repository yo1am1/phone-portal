#!/usr/bin/env python3
"""MCP server for phone-link bridge.

Starts the bridge at MCP server startup. Compatible with Claude Code, Cursor,
Windsurf, Continue, and any MCP-capable agent.
"""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Resolve bridge URL before importing tools so the module picks it up.
_bridge_url = (
    os.getenv("PHONE_LINK_BRIDGE_URL")
    or os.getenv("HERMES_IOS_BRIDGE_URL")
    or "http://127.0.0.1:8765"
).rstrip("/")
os.environ["HERMES_IOS_BRIDGE_URL"] = _bridge_url

from plugin.phone import tools  # noqa: E402

BRIDGE_TOKEN = os.getenv("PHONE_LINK_TOKEN", "dev-token")
BRIDGE_PORT = urllib.parse.urlparse(_bridge_url).port or 8765
BRIDGE_SCRIPT = ROOT / "bridge" / "hermes_phone_bridge.py"

RELAY_PORT = int(os.getenv("PHONE_LINK_RELAY_PORT", "9001"))
RELAY_CLI = os.getenv("PHONE_LINK_RELAY_CLI", "auto")
RELAY_MODEL = os.getenv("PHONE_LINK_RELAY_MODEL", "llama3.2")
RELAY_CMD = os.getenv("PHONE_LINK_RELAY_CMD", "")
RELAY_SCRIPT = ROOT / "relay" / "example_relay.py"
_relay_url = f"http://127.0.0.1:{RELAY_PORT}"

BRIDGE_PID_FILE = ROOT / "data" / "bridge.pid"

_bridge_proc: subprocess.Popen | None = None
_relay_proc: subprocess.Popen | None = None
_bridge_lock = threading.Lock()
_relay_lock = threading.Lock()


def _alive() -> bool:
    try:
        with urllib.request.urlopen(f"{_bridge_url}/health", timeout=2):
            return True
    except Exception:
        return False


def _relay_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{_relay_url}/health", timeout=2):
            return True
    except Exception:
        return False


def _kill_orphan_bridge() -> None:
    """Kill a leftover bridge process from a previous MCP session."""
    if not BRIDGE_PID_FILE.exists():
        return
    try:
        pid = int(BRIDGE_PID_FILE.read_text().strip())
        os.kill(pid, 0)  # check if alive
        # Process exists but bridge not healthy — kill it.
        if not _alive():
            os.kill(pid, 15)  # SIGTERM
            time.sleep(1)
    except (ProcessLookupError, ValueError, OSError):
        pass
    finally:
        BRIDGE_PID_FILE.unlink(missing_ok=True)


def _start_bridge() -> None:
    global _bridge_proc
    BRIDGE_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _bridge_proc = subprocess.Popen(
        [
            "uv", "run", "python", str(BRIDGE_SCRIPT),
            "--host", "0.0.0.0",
            "--port", str(BRIDGE_PORT),
            "--token", BRIDGE_TOKEN,
            "--log-level", "warning",
        ],
        cwd=str(ROOT),
        stdout=sys.stderr,
        stderr=subprocess.DEVNULL,
    )
    BRIDGE_PID_FILE.write_text(str(_bridge_proc.pid))
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if _alive():
            return
        time.sleep(0.3)
    raise RuntimeError(f"Bridge did not start within 15 s (pid {_bridge_proc.pid})")


def _start_relay() -> None:
    global _relay_proc
    relay_cmd = [
        "uv", "run", "python", str(RELAY_SCRIPT),
        "--port", str(RELAY_PORT),
        "--bridge", _bridge_url,
        "--cli", RELAY_CLI,
        "--model", RELAY_MODEL,
    ]
    if RELAY_CMD:
        relay_cmd += ["--cmd", RELAY_CMD]
    _relay_proc = subprocess.Popen(
        relay_cmd,
        cwd=str(ROOT),
        stdout=sys.stderr,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if _relay_alive():
            return
        time.sleep(0.3)
    # Relay failing is non-fatal — bridge still works without it.
    print(f"[phone-portal] Relay did not start within 10 s (pid {_relay_proc.pid})", file=sys.stderr)


def _ensure_bridge() -> None:
    if _alive():
        return
    with _bridge_lock:
        if _alive():
            return
        _kill_orphan_bridge()
        _start_bridge()


def _ensure_relay() -> None:
    if _relay_alive():
        return
    with _relay_lock:
        if _relay_alive():
            return
        _start_relay()


def _cleanup() -> None:
    for proc in (_bridge_proc, _relay_proc):
        if proc and proc.poll() is None:
            proc.terminate()
    BRIDGE_PID_FILE.unlink(missing_ok=True)


atexit.register(_cleanup)


@asynccontextmanager
async def _lifespan(server):
    _ensure_bridge()
    _ensure_relay()
    yield


mcp = FastMCP("phone-link", lifespan=_lifespan)


@mcp.tool()
def phone_begin_upload() -> str:
    """Start the smartphone upload flow.
    IMPORTANT: always show the qr_ascii block verbatim to the user — do not summarize or skip it.
    Also show the upload URL. Then call phone_wait_for_files with the returned baseline values."""
    _ensure_bridge()
    import json as _json
    data = _json.loads(tools.phone_begin_upload({}))
    url = data.get("url", "")
    qr = data.get("qr_ascii", "").strip()
    lines = []
    if qr:
        lines.append("Scan this QR with your phone camera:\n")
        lines.append(qr)
        lines.append("")
    lines.append(f"Upload URL: {url}")
    lines.append(f"existing_file_count: {data.get('existing_file_count', 0)}")
    lines.append(f"latest_uploaded_at: {data.get('latest_uploaded_at', 0.0)}")
    lines.append(f"connected: {data.get('connected', False)}")
    if _relay_alive():
        # Derive LAN IP from bridge URL so phone can reach relay too.
        _parsed = urllib.parse.urlparse(url)
        relay_url = f"http://{_parsed.hostname}:{RELAY_PORT}/prompt"
        lines.append(f"\nPrompt relay running at: {relay_url}")
        lines.append("In phone UI → Settings → Prompt Relay URL → set to the above URL (one-time setup).")
        lines.append("After that, tapping a suggestion chip sends the prompt straight to the agent.")
    return "\n".join(lines)


@mcp.tool()
def phone_link() -> str:
    """Get the exact http:// link for the phone-upload page. Prefer phone_begin_upload for the normal first step."""
    _ensure_bridge()
    return tools.phone_link({})


@mcp.tool()
def phone_wait_for_files(
    timeout_seconds: int = 120,
    poll_interval_seconds: int = 2,
    min_files: int = 1,
    since_count: int = 0,
    since_uploaded_at: float = 0.0,
) -> str:
    """Wait for new files from the phone upload page, then return the file list.
    Pass since_count and since_uploaded_at from phone_begin_upload to skip pre-existing files."""
    _ensure_bridge()
    return tools.phone_wait_for_files({
        "timeout_seconds": timeout_seconds,
        "poll_interval_seconds": poll_interval_seconds,
        "min_files": min_files,
        "since_count": since_count,
        "since_uploaded_at": since_uploaded_at,
    })


@mcp.tool()
def phone_status() -> str:
    """Check bridge and device connection status."""
    _ensure_bridge()
    return tools.phone_status({})


@mcp.tool()
def phone_list_files() -> str:
    """List all files uploaded from the phone."""
    _ensure_bridge()
    return tools.phone_list_files({})


@mcp.tool()
def phone_read_file(file_id: str, max_bytes: int = 200_000) -> str:
    """Read a specific uploaded file by id.
    Text files: returns UTF-8 text.
    Small binary files (<=100 KB): returns base64.
    Large binary files (>100 KB, e.g. images): returns storage_path + read_hint instead of data.
      Use the Read tool directly on storage_path to view the file.
    Get file_id from phone_list_files."""
    _ensure_bridge()
    return tools.phone_read_file({"file_id": file_id, "max_bytes": max_bytes})


@mcp.tool()
def phone_read_latest_file(max_bytes: int = 200_000) -> str:
    """Read the most recently uploaded phone file without needing a file_id."""
    _ensure_bridge()
    return tools.phone_read_latest_file({"max_bytes": max_bytes})


@mcp.tool()
def phone_summary() -> str:
    """Return a human-friendly summary of bridge status, latest file, and suggested next tool."""
    _ensure_bridge()
    return tools.phone_summary({})


@mcp.tool()
def phone_create_zip(name: str = "") -> str:
    """Create a zip bundle from all currently uploaded files."""
    _ensure_bridge()
    return tools.phone_create_zip({"name": name})


@mcp.tool()
def phone_send_text(text: str, title: str = "") -> str:
    """Send a text message from the agent to the phone display."""
    _ensure_bridge()
    return tools.phone_send_text({"text": text, "title": title})


@mcp.tool()
def phone_delete_file(file_id: str) -> str:
    """Delete an uploaded file by id. Use after processing to free space."""
    _ensure_bridge()
    return tools.phone_delete_file({"file_id": file_id})


if __name__ == "__main__":
    mcp.run()
