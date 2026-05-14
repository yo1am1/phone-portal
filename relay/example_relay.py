#!/usr/bin/env python3
"""Example prompt relay server.

Receives prompt chip taps from the phone UI and prints them to the terminal.
Wire your own agent logic where marked — no external dependencies required.

Usage:
    uv run python relay/example_relay.py [--port 9001] [--bridge http://127.0.0.1:8765]

In phone UI Settings → Prompt Relay URL → http://<your-machine-ip>:9001/prompt
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

BRIDGE_URL = os.getenv("PHONE_LINK_BRIDGE_URL", "http://127.0.0.1:8765").rstrip("/")


def send_text_to_phone(text: str, title: str = "") -> None:
    """Send a message back to the phone's 'From Agent' section."""
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


def handle_prompt(prompt: str, session_id: str) -> None:
    """
    Called in a background thread for each incoming chip tap.
    Replace the body of this function with your agent logic.
    """
    print(f"\n{'─' * 60}")
    print(f"[relay] Prompt received:")
    print(f"  {prompt}")
    print(f"  session: {session_id}")
    print(f"{'─' * 60}\n")

    # ── Wire your agent here ──────────────────────────────────
    # Examples:
    #
    # 1. Claude Code non-interactive:
    #    import subprocess
    #    result = subprocess.run(
    #        ["claude", "-p", prompt],
    #        capture_output=True, text=True
    #    )
    #    send_text_to_phone(result.stdout.strip(), title=prompt[:60])
    #
    # 2. Anthropic SDK:
    #    import anthropic
    #    client = anthropic.Anthropic()
    #    msg = client.messages.create(
    #        model="claude-sonnet-4-6",
    #        max_tokens=1024,
    #        messages=[{"role": "user", "content": prompt}],
    #    )
    #    send_text_to_phone(msg.content[0].text, title=prompt[:60])
    #
    # 3. Any HTTP agent:
    #    import urllib.request, json
    #    resp = urllib.request.urlopen(
    #        urllib.request.Request("http://your-agent/run",
    #            data=json.dumps({"input": prompt}).encode(),
    #            headers={"Content-Type": "application/json"})
    #    )
    #    send_text_to_phone(json.loads(resp.read())["output"])
    # ──────────────────────────────────────────────────────────

    # Default: acknowledge so user sees something on phone
    send_text_to_phone(
        f"Received: {prompt}\n\nWire your agent in relay/example_relay.py → handle_prompt()",
        title="Relay echo",
    )


class RelayHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress default access log

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"ok": True, "service": "prompt-relay"})
        else:
            self._respond(404, {"ok": False})

    def do_POST(self):
        if self.path != "/prompt":
            self._respond(404, {"ok": False})
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception:
            self._respond(400, {"ok": False, "error": "invalid JSON"})
            return
        prompt = str(data.get("prompt") or "").strip()
        session_id = str(data.get("session_id") or "")
        if not prompt:
            self._respond(400, {"ok": False, "error": "prompt is required"})
            return
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
    global BRIDGE_URL  # noqa: PLW0603
    parser = argparse.ArgumentParser(description="Prompt relay server")
    parser.add_argument("--port", type=int, default=9001)
    parser.add_argument("--bridge", default=BRIDGE_URL)
    args = parser.parse_args()
    BRIDGE_URL = args.bridge.rstrip("/")

    server = HTTPServer(("0.0.0.0", args.port), RelayHandler)
    print(f"[relay] Listening on http://0.0.0.0:{args.port}/prompt")
    print(f"[relay] Bridge: {BRIDGE_URL}")
    print(f"[relay] Set Prompt Relay URL in phone UI Settings to:")
    print(f"[relay]   http://<your-machine-ip>:{args.port}/prompt")
    print(f"[relay] Waiting for chip taps…\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[relay] Stopped.")


if __name__ == "__main__":
    main()
