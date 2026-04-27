#!/usr/bin/env python3
"""
clawd-web — browser chat UI that talks directly to the OpenClaw gateway.

The browser does all the WebSocket work. This Python server just serves
the static HTML and exposes gateway config (URL + token + session key)
via a /config endpoint so the browser knows where to connect.

No pip deps, stdlib only.
"""
import json
import os
import queue
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn, TCPServer


class ThreadedHTTPServer(ThreadingMixIn, TCPServer):
    allow_reuse_address = True
    daemon_threads = True


# ── SSE broadcast ─────────────────────────────────────────────────────────────
_sse_clients: list[queue.Queue] = []
_sse_lock = threading.Lock()


def push_event(data: str):
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try:
                q.put_nowait(data)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)


# ── Load .env (optional) ─────────────────────────────────────────────────────
def load_dotenv(path=".env"):
    env_path = Path(__file__).parent / path
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


load_dotenv()


# ── Load gateway config from ~/.openclaw/openclaw.json ───────────────────────
def load_openclaw_config():
    path = Path(os.path.expanduser("~/.openclaw/openclaw.json"))
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as e:
        print(f"[warn] could not parse {path}: {e}")
        return {}


def resolve_gateway_settings():
    """Return {wsUrl, token, sessionKey, bankrKey} — env vars override openclaw.json."""
    cfg = load_openclaw_config()
    gateway = cfg.get("gateway", {})
    port = gateway.get("port", 18789)
    token = (gateway.get("auth", {}) or {}).get("token", "")

    return {
        "wsUrl": os.environ.get("OPENCLAW_WS_URL") or f"ws://127.0.0.1:{port}",
        "token": os.environ.get("OPENCLAW_TOKEN") or token,
        "sessionKey": os.environ.get("OPENCLAW_SESSION_KEY") or "agent:clawd:main",
        "bankrKey": os.environ.get("BANKR_LLM_KEY") or "",
    }


PORT = int(os.environ.get("PORT", "7800"))


# ── HTTP server ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{self.address_string()}] {fmt % args}")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self.serve_file("index.html", "text/html; charset=utf-8")
        elif path == "/config":
            cfg = resolve_gateway_settings()
            cfg.pop("bankrKey", None)  # keep API key server-side only
            self.send_json(cfg)
        elif path == "/health":
            self.send_json({"status": "ok"})
        elif path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            q: queue.Queue = queue.Queue(maxsize=32)
            with _sse_lock:
                _sse_clients.append(q)
            try:
                while True:
                    try:
                        data = q.get(timeout=15)
                        self.wfile.write(f"data: {data}\n\n".encode())
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
            except Exception:
                pass
            finally:
                with _sse_lock:
                    try:
                        _sse_clients.remove(q)
                    except ValueError:
                        pass
            return
        elif path.startswith("/clawdassets/"):
            name = path[len("/clawdassets/"):]
            if "/" in name or not name:
                self.send_error(404)
                return
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            mime = {"mp4": "video/mp4", "webm": "video/webm", "png": "image/png",
                    "jpg": "image/jpeg", "gif": "image/gif", "svg": "image/svg+xml"}.get(ext, "application/octet-stream")
            self.serve_file(f"clawdassets/{name}", mime)
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/autotitle":
            self.handle_autotitle()
        elif path == "/trigger-mic":
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            push_event("toggle-mic")
            self.send_json({"ok": True})
        else:
            self.send_error(404)

    def handle_autotitle(self):
        bankr_key = os.environ.get("BANKR_LLM_KEY", "")
        if not bankr_key:
            self.send_json({"error": "no bankr key"}, status=503)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            messages = body.get("messages", [])
            req_body = json.dumps({
                "model": "minimax-m2.7",
                "max_tokens": 200,
                "messages": [
                    {"role": "system", "content": "You generate ultra-short chat tab titles. Reply with ONLY 2-3 words, no punctuation, no explanation, no thinking."},
                ] + messages,
            }).encode()
            req = urllib.request.Request(
                "https://llm.bankr.bot/v1/chat/completions",
                data=req_body,
                headers={"Content-Type": "application/json", "X-API-Key": bankr_key},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            raw = data["choices"][0]["message"]["content"]
            # strip <think>...</think> reasoning blocks
            import re
            title = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            title = re.sub(r'["""\'\'.,!?:;]', "", title).strip()[:40]
            self.send_json({"title": title})
        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def serve_file(self, name, content_type):
        path = Path(__file__).parent / name
        if not path.exists():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def check_allowed_origins(port):
    """Warn if the gateway isn't configured to accept our origin."""
    cfg = load_openclaw_config()
    allowed = (((cfg.get("gateway") or {}).get("controlUi") or {}).get("allowedOrigins") or [])
    needed = [f"http://localhost:{port}", f"http://127.0.0.1:{port}"]
    missing = [o for o in needed if o not in allowed]
    if not missing:
        return
    print()
    print("⚠  gateway.controlUi.allowedOrigins is missing our origin.")
    print("   The openclaw gateway will reject our WebSocket unless you add:")
    print()
    print("     \"gateway\": {")
    print("       \"controlUi\": {")
    print(f"         \"allowedOrigins\": {json.dumps(needed)}")
    print("       }")
    print("     }")
    print()
    print("   Then restart the gateway. (See README for details.)")
    print()


if __name__ == "__main__":
    settings = resolve_gateway_settings()
    print(f"🕸️  clawd-web → http://127.0.0.1:{PORT}")
    print(f"   gateway   → {settings['wsUrl']}")
    print(f"   session   → {settings['sessionKey']}")
    print(f"   token     → {'set' if settings['token'] else 'MISSING — check ~/.openclaw/openclaw.json'}")
    if not settings["token"]:
        print("[warn] no gateway token found — the UI will prompt you to paste one")
    print("   hotkey    → run `python3 hotkey.py` in a separate terminal for Ctrl+.")
    check_allowed_origins(PORT)
    try:
        ThreadedHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        sys.exit(0)
