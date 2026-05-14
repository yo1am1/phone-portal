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

from plugin.ios_phone import tools  # noqa: E402

BRIDGE_TOKEN = os.getenv("PHONE_LINK_TOKEN", "dev-token")
BRIDGE_PORT = urllib.parse.urlparse(_bridge_url).port or 8765
BRIDGE_SCRIPT = ROOT / "bridge" / "hermes_phone_bridge.py"

_bridge_proc: subprocess.Popen | None = None
_bridge_lock = threading.Lock()


def _alive() -> bool:
    try:
        with urllib.request.urlopen(f"{_bridge_url}/health", timeout=2):
            return True
    except Exception:
        return False


def _start_bridge() -> None:
    global _bridge_proc
    # stdout → MCP server's stderr so QR/startup prints reach the terminal
    # without corrupting the MCP stdio protocol pipe on stdout.
    # stderr → DEVNULL silences uvicorn request logs.
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
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if _alive():
            return
        time.sleep(0.3)
    raise RuntimeError(f"Bridge did not start within 15 s (pid {_bridge_proc.pid})")


def _ensure_bridge() -> None:
    if _alive():
        return
    with _bridge_lock:
        if _alive():
            return
        _start_bridge()


def _cleanup() -> None:
    if _bridge_proc and _bridge_proc.poll() is None:
        _bridge_proc.terminate()


atexit.register(_cleanup)


@asynccontextmanager
async def _lifespan(server):
    _ensure_bridge()
    yield


mcp = FastMCP("phone-link", lifespan=_lifespan)


@mcp.tool()
def ios_phone_begin_upload() -> str:
    """Start the smartphone upload flow.
    IMPORTANT: always show the qr_ascii block verbatim to the user — do not summarize or skip it.
    Also show the upload URL. Then call ios_phone_wait_for_files with the returned baseline values."""
    _ensure_bridge()
    import json as _json
    data = _json.loads(tools.ios_phone_begin_upload({}))
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
    return "\n".join(lines)


@mcp.tool()
def ios_phone_link() -> str:
    """Get the exact http:// link for the phone-upload page. Prefer ios_phone_begin_upload for the normal first step."""
    _ensure_bridge()
    return tools.ios_phone_link({})


@mcp.tool()
def ios_phone_wait_for_files(
    timeout_seconds: int = 120,
    poll_interval_seconds: int = 2,
    min_files: int = 1,
    since_count: int = 0,
    since_uploaded_at: float = 0.0,
) -> str:
    """Wait for new files from the phone upload page, then return the file list.
    Pass since_count and since_uploaded_at from ios_phone_begin_upload to skip pre-existing files."""
    _ensure_bridge()
    return tools.ios_phone_wait_for_files({
        "timeout_seconds": timeout_seconds,
        "poll_interval_seconds": poll_interval_seconds,
        "min_files": min_files,
        "since_count": since_count,
        "since_uploaded_at": since_uploaded_at,
    })


@mcp.tool()
def ios_phone_status() -> str:
    """Check bridge and device connection status."""
    _ensure_bridge()
    return tools.ios_phone_status({})


@mcp.tool()
def ios_phone_list_files() -> str:
    """List all files uploaded from the phone."""
    _ensure_bridge()
    return tools.ios_phone_list_files({})


@mcp.tool()
def ios_phone_read_file(file_id: str, max_bytes: int = 200_000) -> str:
    """Read a specific uploaded file by id.
    Text files: returns UTF-8 text.
    Small binary files (<=100 KB): returns base64.
    Large binary files (>100 KB, e.g. images): returns storage_path + read_hint instead of data.
      Use the Read tool directly on storage_path to view the file.
    Get file_id from ios_phone_list_files."""
    _ensure_bridge()
    return tools.ios_phone_read_file({"file_id": file_id, "max_bytes": max_bytes})


@mcp.tool()
def ios_phone_read_latest_file(max_bytes: int = 200_000) -> str:
    """Read the most recently uploaded phone file without needing a file_id."""
    _ensure_bridge()
    return tools.ios_phone_read_latest_file({"max_bytes": max_bytes})


@mcp.tool()
def ios_phone_summary() -> str:
    """Return a human-friendly summary of bridge status, latest file, and suggested next tool."""
    _ensure_bridge()
    return tools.ios_phone_summary({})


@mcp.tool()
def ios_phone_create_zip(name: str = "") -> str:
    """Create a zip bundle from all currently uploaded files."""
    _ensure_bridge()
    return tools.ios_phone_create_zip({"name": name})


@mcp.tool()
def ios_phone_send_text(text: str, title: str = "") -> str:
    """Send a text message from the agent to the phone display."""
    _ensure_bridge()
    return tools.ios_phone_send_text({"text": text, "title": title})


@mcp.tool()
def ios_phone_delete_file(file_id: str) -> str:
    """Delete an uploaded file by id. Use after processing to free space."""
    _ensure_bridge()
    return tools.ios_phone_delete_file({"file_id": file_id})


if __name__ == "__main__":
    mcp.run()
