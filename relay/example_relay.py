#!/usr/bin/env python3
"""Prompt relay server.

Receives prompt chip taps from the phone UI, fetches uploaded file context
from the bridge, runs a configured AI CLI, sends the response back to the
phone's "From Agent" section.

Supported CLIs (--cli):
  auto     detect first available CLI in PATH (default)
  claude   Claude Code:  claude -p "..."
  gemini   Gemini CLI:   gemini "..."
  ollama   Ollama:       ollama run <model> "..."
  llm      Simon Willison's llm: llm "..."
  custom   use --cmd template, e.g. --cmd 'my-agent --input {prompt}'

Usage:
    uv run python relay/example_relay.py
    uv run python relay/example_relay.py --cli ollama --model llama3.2
    uv run python relay/example_relay.py --cmd 'llm -m gpt-4o {prompt}'
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

BRIDGE_URL = os.getenv("PHONE_LINK_BRIDGE_URL", "http://127.0.0.1:8765").rstrip("/")
CLAUDE_TIMEOUT = int(os.getenv("PHONE_LINK_CLAUDE_TIMEOUT", "120"))

# CLI preset: list of args with {prompt} and optional {model} placeholders.
_CLI_PRESETS: dict[str, list[str]] = {
    "claude": ["claude", "-p", "{prompt}"],
    "gemini": ["gemini", "{prompt}"],
    "ollama": ["ollama", "run", "{model}", "{prompt}"],
    "llm":    ["llm", "{prompt}"],
}
_AUTO_ORDER = ["claude", "gemini", "llm", "ollama"]

# Set by main() from CLI args.
_cli_preset: str = "claude"
_cli_model: str = "llama3.2"
_cli_cmd_template: str | None = None  # overrides preset when set


# ── CLI detection + command building ─────────────────────────

def _detect_cli() -> str:
    for name in _AUTO_ORDER:
        if shutil.which(name):
            return name
    return "claude"


def _build_cmd(prompt: str) -> list[str]:
    if _cli_cmd_template:
        parts = shlex.split(_cli_cmd_template)
        return [p.replace("{prompt}", prompt).replace("{model}", _cli_model) for p in parts]
    preset = _CLI_PRESETS.get(_cli_preset)
    if not preset:
        raise ValueError(f"Unknown CLI preset: {_cli_preset!r}")
    return [p.replace("{prompt}", prompt).replace("{model}", _cli_model) for p in preset]


# ── Bridge helpers ────────────────────────────────────────────

def _bridge_get(path: str) -> dict:
    with urllib.request.urlopen(f"{BRIDGE_URL}{path}", timeout=5) as r:
        return json.loads(r.read())


def _bridge_post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BRIDGE_URL}{path}", data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def send_text_to_phone(text: str, title: str = "") -> None:
    payload = json.dumps({"text": text, "title": title}).encode()
    req = urllib.request.Request(
        f"{BRIDGE_URL}/api/agent/send_text",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[relay] send_text failed: {e}")


# ── File context ──────────────────────────────────────────────

def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _fetch_context() -> str:
    try:
        data = _bridge_get("/api/agent/files")
    except Exception as e:
        return f"(could not fetch files: {e})"

    files = data.get("files") or []
    if not files:
        return "No files uploaded yet."

    lines = []
    for f in files:
        name = f.get("name", "?")
        size = f.get("size", 0)
        ftype = f.get("type", "")
        file_id = f.get("id", "")
        lines.append(f"• {name}  ({_fmt_bytes(size)}, {ftype})")

        is_text = "text" in ftype or name.endswith(
            (".txt", ".md", ".csv", ".json", ".yaml", ".yml",
             ".py", ".js", ".ts", ".html", ".css", ".sh", ".log")
        )
        if is_text and size < 40_000:
            try:
                result = _bridge_post("/api/agent/command", {
                    "name": "read_file",
                    "args": {"file_id": file_id, "max_bytes": 8_000},
                    "timeout": 10,
                })
                inner = result.get("result", result)
                if inner.get("ok") and inner.get("encoding") == "utf8":
                    snippet = inner.get("text", "").strip()
                    if snippet:
                        lines.append(f"  ```\n  {snippet[:3000]}\n  ```")
            except Exception:
                pass

    return "\n".join(lines)


# ── Core handler ──────────────────────────────────────────────

def handle_prompt(prompt: str, session_id: str) -> None:
    print(f"\n[relay] ← {prompt!r}")

    context = _fetch_context()
    full_prompt = (
        "You are helping a user who sent files from their phone to an AI agent.\n\n"
        f"Uploaded files:\n{context}\n\n"
        f"User request: {prompt}\n\n"
        "Be concise — response is displayed on a small phone screen."
    )

    try:
        cmd = _build_cmd(full_prompt)
        print(f"[relay] running: {cmd[0]}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
        )
        if result.returncode == 0:
            response = result.stdout.strip()
        else:
            stderr = result.stderr.strip()
            response = f"{cmd[0]} exited {result.returncode}.\n{stderr[:400]}" if stderr else f"{cmd[0]} exited {result.returncode}."
    except FileNotFoundError:
        name = (_cli_cmd_template or _cli_preset).split()[0]
        response = f"CLI not found: {name!r}. Check it is installed and in PATH."
    except subprocess.TimeoutExpired:
        response = f"Timed out after {CLAUDE_TIMEOUT}s."
    except Exception as e:
        response = f"Relay error: {e}"

    print(f"[relay] → {response[:120]}{'…' if len(response) > 120 else ''}")
    title = prompt[:60] + ("…" if len(prompt) > 60 else "")
    send_text_to_phone(response, title=title)


# ── HTTP server ───────────────────────────────────────────────

class RelayHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"ok": True, "service": "prompt-relay", "cli": _cli_preset})
        else:
            self._respond(404, {"ok": False})

    def do_POST(self):
        if self.path != "/prompt":
            self._respond(404, {"ok": False})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
        except Exception:
            self._respond(400, {"ok": False, "error": "invalid JSON"})
            return
        prompt = str(data.get("prompt") or "").strip()
        if not prompt:
            self._respond(400, {"ok": False, "error": "prompt required"})
            return
        session_id = str(data.get("session_id") or "")
        threading.Thread(target=handle_prompt, args=(prompt, session_id), daemon=True).start()
        self._respond(202, {"ok": True, "status": "processing"})

    def _respond(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    global BRIDGE_URL, _cli_preset, _cli_model, _cli_cmd_template  # noqa: PLW0603

    parser = argparse.ArgumentParser(description="Prompt relay server")
    parser.add_argument("--port", type=int, default=9001)
    parser.add_argument("--bridge", default=BRIDGE_URL)
    parser.add_argument(
        "--cli",
        default="auto",
        choices=[*_CLI_PRESETS, "auto"],
        help="AI CLI to use (default: auto-detect from PATH)",
    )
    parser.add_argument("--model", default=_cli_model, help="Model name (used by ollama)")
    parser.add_argument("--cmd", default=None, help="Custom command template, e.g. 'llm -m gpt-4o {prompt}'")
    args = parser.parse_args()

    BRIDGE_URL = args.bridge.rstrip("/")
    _cli_model = args.model
    _cli_cmd_template = args.cmd

    if args.cmd:
        _cli_preset = "custom"
    elif args.cli == "auto":
        _cli_preset = _detect_cli()
    else:
        _cli_preset = args.cli

    active = _cli_cmd_template or f"{_cli_preset} preset"

    server = HTTPServer(("0.0.0.0", args.port), RelayHandler)
    print(f"[relay] Listening on http://0.0.0.0:{args.port}/prompt")
    print(f"[relay] Bridge:  {BRIDGE_URL}")
    print(f"[relay] CLI:     {active}")
    if _cli_preset == "ollama":
        print(f"[relay] Model:   {_cli_model}")
    print(f"[relay] Timeout: {CLAUDE_TIMEOUT}s")
    print(f"[relay] Set Prompt Relay URL in phone UI → Settings:")
    print(f"[relay]   http://<your-machine-ip>:{args.port}/prompt")
    print(f"[relay] Waiting for chip taps…\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[relay] Stopped.")


if __name__ == "__main__":
    main()
