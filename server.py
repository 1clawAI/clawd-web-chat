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
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path


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
    """Return {wsUrl, token, sessionKey} — env vars override openclaw.json."""
    cfg = load_openclaw_config()
    gateway = cfg.get("gateway", {})
    port = gateway.get("port", 18789)
    token = (gateway.get("auth", {}) or {}).get("token", "")

    return {
        "wsUrl": os.environ.get("OPENCLAW_WS_URL") or f"ws://127.0.0.1:{port}",
        "token": os.environ.get("OPENCLAW_TOKEN") or token,
        "sessionKey": os.environ.get("OPENCLAW_SESSION_KEY") or "agent:clawdadsonnet:main",
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
            self.send_json(resolve_gateway_settings())
        elif path == "/health":
            self.send_json({"status": "ok"})
        else:
            self.send_error(404)

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
    check_allowed_origins(PORT)
    try:
        HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        sys.exit(0)
