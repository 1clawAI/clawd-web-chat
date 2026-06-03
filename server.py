#!/usr/bin/env python3
"""
clawd-web — browser chat UI that talks to a Hermes agent over its
OpenAI-compatible API server.

The browser drives the chat UI; this Python server proxies to Hermes so the
bearer key (which grants Hermes's full toolset, incl. terminal) never reaches
the browser, and so we sidestep Hermes's CORS-off API and any MagicDNS gaps.
The browser hits /config (key-free) + /api/hermes/chat (SSE) + /api/* helpers.

No pip deps, stdlib only.
"""
import http.client
import json
import os
import socket
import ssl
import sys
import queue
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn, TCPServer
from urllib.parse import urlsplit


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


def tts_backend():
    """Pick the active TTS backend by env var availability."""
    if os.environ.get("ELEVENLABS_API_KEY"):
        return "elevenlabs"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "none"


# ── Hermes agent (OpenAI-compatible API server) ─────────────────────────────
# HERMES_BASE_URL may be given with or without a trailing "/v1" or "/"; we
# normalize to a bare scheme://host[:port] root and build paths ourselves.
def _normalize_base(url):
    url = (url or "").strip().rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url


HERMES_BASE_URL = _normalize_base(os.environ.get("HERMES_BASE_URL", ""))
HERMES_API_KEY = os.environ.get("HERMES_API_KEY", "")
HERMES_MODEL = os.environ.get("HERMES_MODEL", "hermes-agent")
# Optional personality nudge prepended as a system message on the main chat.
# Keeps answers helpful but lets a little dry wit surface now and then. Set
# HERMES_PERSONA="" to disable.
_DEFAULT_PERSONA = (
    "You have a dry, understated sense of humor. Occasionally — only when it "
    "fits naturally — slip in a subtle witty aside or a light, deadpan joke to "
    "show personality. Keep it brief and never at the expense of being genuinely "
    "helpful, accurate, or clear. Most of the time just answer well; let the "
    "humor surface sparingly, maybe one response in three.\n\n"
    "Your replies are read aloud by a text-to-speech voice, so write them to be "
    "heard, not just read: use complete, clearly punctuated sentences with commas "
    "and periods for natural pauses, keep a relaxed conversational rhythm, and "
    "avoid dense run-on sentences, long lists, or walls of symbols. When you must "
    "include code or commands for the screen, still give a plain, spoken-friendly "
    "sentence explaining them.\n\n"
    "Keep replies concise and punchy — usually two to four sentences. Get to the "
    "point fast and lead with the answer; only go longer when the user explicitly "
    "asks for depth or the topic truly needs it."
)
HERMES_PERSONA = os.environ.get("HERMES_PERSONA", _DEFAULT_PERSONA)
# Optional: pin the hostname to a tailnet IP when MagicDNS isn't wired into the
# OS resolver (common with open-source tailscaled on macOS). TLS still validates
# against the real hostname — we only override which IP the socket connects to.
HERMES_RESOLVE_IP = os.environ.get("HERMES_RESOLVE_IP", "").strip()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS to a fixed IP while keeping SNI + cert validation on the hostname."""

    def __init__(self, host, ip, **kw):
        super().__init__(host, **kw)  # self.host = real hostname (SNI + Host header)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _hermes_request(method, path, body=None, extra_headers=None, timeout=120):
    """Open a request to the Hermes API server. Returns (conn, response).

    Caller must conn.close() when done. Body should be pre-encoded bytes.
    """
    if not HERMES_BASE_URL:
        raise RuntimeError("HERMES_BASE_URL not configured")
    sp = urlsplit(HERMES_BASE_URL)
    host = sp.hostname
    port = sp.port or (443 if sp.scheme == "https" else 80)
    headers = {"Authorization": f"Bearer {HERMES_API_KEY}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    if sp.scheme == "https":
        if HERMES_RESOLVE_IP:
            conn = _PinnedHTTPSConnection(host, HERMES_RESOLVE_IP, port=port, timeout=timeout)
        else:
            conn = http.client.HTTPSConnection(host, port, timeout=timeout)
    else:
        conn = http.client.HTTPConnection(HERMES_RESOLVE_IP or host, port, timeout=timeout)
    conn.request(method, path, body=body, headers=headers)
    return conn, conn.getresponse()


def resolve_settings():
    """Key-free config the browser is allowed to see."""
    return {
        "backend": "hermes",
        "model": HERMES_MODEL,
        "hermesConfigured": bool(HERMES_BASE_URL and HERMES_API_KEY),
        "ttsBackend": tts_backend(),
    }


# Steers the gpt-4o-mini-tts delivery — see /api/tts.
TTS_INSTRUCTIONS = (
    "Speak with a German accent — a witty cypherpunk hacker who finds the "
    "whole system mildly hilarious. Deep and relaxed, dry deadpan delivery "
    "with sly comic timing and the faint smirk of someone who encrypts for "
    "sport. Crisp German consonants, slightly clipped vowels, unhurried "
    "pacing. Unbothered and a little smug — like you already owned the box "
    "and are just narrating it for fun. Never excitable; the humor is in the "
    "calm."
)


PORT = int(os.environ.get("PORT", "7800"))
MODES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modes")


def list_modes():
    """Return [{slug, name, content}] for every .md file in modes/.

    `slug` is the filename without .md, `name` is the same string with hyphens
    swapped for spaces (display label), `content` is the raw markdown.
    Read at request time so edits to .md files take effect without a restart.
    """
    out = []
    if not os.path.isdir(MODES_DIR):
        return out
    for name in sorted(os.listdir(MODES_DIR)):
        if not name.endswith(".md") or name.startswith("."):
            continue
        slug = name[:-3]
        try:
            with open(os.path.join(MODES_DIR, name), "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue
        out.append({"slug": slug, "name": slug.replace("-", " "), "content": content})
    return out


def _llm_chat_with_fallback(messages, max_tokens, bankr_model, venice_model,
                            anthropic_model, timeout=15, temperature=None,
                            hermes_model=None):
    """Cascade: hermes (optional) → bankr → venice → anthropic-direct.

    Returns the assistant's raw content string. Each tier is skipped if its
    key isn't set. When a later tier is available, the earlier tier's timeout
    is capped so a hung provider can't burn the whole budget. Raises the last
    upstream exception if every available tier fails (or RuntimeError if none
    are configured).

    Hermes runs the full agent (slow, heavy), so it's only used when a caller
    opts in via `hermes_model` and always with a tight timeout — if it stalls
    we fall through to the fast cloud tiers below.
    """
    bankr_key = os.environ.get("BANKR_LLM_KEY", "")
    venice_key = os.environ.get("VENICE_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    last_err = None

    if hermes_model and HERMES_BASE_URL and HERMES_API_KEY:
        try:
            body_obj = {"model": hermes_model, "max_tokens": max_tokens, "messages": messages}
            if temperature is not None:
                body_obj["temperature"] = temperature
            # Tight cap when a fast fallback exists — Hermes is the full agent.
            ht = min(12, timeout) if (bankr_key or venice_key or anthropic_key) else timeout
            conn, resp = _hermes_request(
                "POST", "/v1/chat/completions",
                body=json.dumps(body_obj).encode(), timeout=ht,
            )
            try:
                return json.loads(resp.read())["choices"][0]["message"]["content"]
            finally:
                conn.close()
        except Exception as e:
            last_err = e

    if bankr_key:
        try:
            body_obj = {
                "model": bankr_model,
                "max_tokens": max_tokens,
                "messages": messages,
            }
            if temperature is not None:
                body_obj["temperature"] = temperature
            body = json.dumps(body_obj).encode()
            req = urllib.request.Request(
                "https://llm.bankr.bot/v1/chat/completions",
                data=body,
                headers={"Content-Type": "application/json", "X-API-Key": bankr_key},
                method="POST",
            )
            bt = min(5, timeout) if (venice_key or anthropic_key) else timeout
            with urllib.request.urlopen(req, timeout=bt) as resp:
                return json.loads(resp.read())["choices"][0]["message"]["content"]
        except Exception as e:
            last_err = e

    if venice_key:
        try:
            body_obj = {
                "model": venice_model,
                "max_tokens": max_tokens,
                "messages": messages,
            }
            if temperature is not None:
                body_obj["temperature"] = temperature
            body = json.dumps(body_obj).encode()
            req = urllib.request.Request(
                "https://api.venice.ai/api/v1/chat/completions",
                data=body,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {venice_key}"},
                method="POST",
            )
            vt = min(8, timeout) if anthropic_key else timeout
            with urllib.request.urlopen(req, timeout=vt) as resp:
                return json.loads(resp.read())["choices"][0]["message"]["content"]
        except Exception as e:
            last_err = e

    if anthropic_key:
        # Anthropic-messages API splits the system prompt out of `messages`.
        sys_parts = [m.get("content", "") for m in messages if m.get("role") == "system"]
        rest = [m for m in messages if m.get("role") != "system"]
        payload = {
            "model": anthropic_model,
            "max_tokens": max_tokens,
            "messages": rest,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if sys_parts:
            payload["system"] = "\n\n".join(p for p in sys_parts if p)
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "x-api-key": anthropic_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            for block in data.get("content", []):
                if block.get("type") == "text":
                    return block.get("text", "")
            return ""

    raise last_err or RuntimeError(
        "no LLM provider configured (BANKR_LLM_KEY / VENICE_API_KEY / ANTHROPIC_API_KEY)"
    )


# ── HTTP server ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{self.address_string()}] {fmt % args}")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self.serve_file("index.html", "text/html; charset=utf-8")
        elif path == "/manifest.webmanifest":
            self.serve_file("manifest.webmanifest", "application/manifest+json")
        elif path == "/sw.js":
            # Served from root so the worker's scope covers the whole app.
            self.serve_file("sw.js", "text/javascript", extra_headers={"Service-Worker-Allowed": "/"})
        elif path == "/config":
            self.send_json(resolve_settings())
        elif path == "/health":
            self.send_json({"status": "ok"})
        elif path == "/api/modes":
            self.send_json({"modes": list_modes()})
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
        if path == "/api/hermes/chat":
            self.handle_hermes_chat()
        elif path == "/api/autotitle":
            self.handle_autotitle()
        elif path == "/api/filler":
            self.handle_filler()
        elif path == "/api/tts":
            self.handle_tts()
        elif path == "/trigger-mic":
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            push_event("toggle-mic")
            self.send_json({"ok": True})
        elif path == "/trigger-toggle-view":
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            push_event("toggle-view")
            self.send_json({"ok": True})
        elif path == "/trigger-reveal-history":
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            push_event("reveal-history")
            self.send_json({"ok": True})
        elif path == "/trigger-new-tab":
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            push_event("new-tab")
            self.send_json({"ok": True})
        elif path == "/trigger-speech-mode":
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            push_event("toggle-speech-mode")
            self.send_json({"ok": True})
        elif path == "/trigger-stop-talking":
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            push_event("stop-talking")
            self.send_json({"ok": True})
        else:
            self.send_error(404)

    def handle_hermes_chat(self):
        """Proxy a streaming chat turn to Hermes /v1/chat/completions.

        Body: {sessionKey, text}. The bearer key + DNS pinning stay here;
        the browser receives Hermes's SSE stream verbatim (chat.completion.chunk
        + hermes.tool.progress events) and parses it client-side.

        Continuity is server-side in Hermes, keyed by X-Hermes-Session-Key, so
        we only forward the single new user turn. If the browser disconnects
        (Stop button), the upstream socket closes, which aborts the Hermes run.
        """
        if not (HERMES_BASE_URL and HERMES_API_KEY):
            self.send_json({"error": "HERMES_BASE_URL / HERMES_API_KEY not configured"}, status=503)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            req_body = json.loads(self.rfile.read(length)) if length else {}
        except Exception as e:
            self.send_json({"error": f"bad request body: {e}"}, status=400)
            return
        session_key = (req_body.get("sessionKey") or "").strip()
        text = req_body.get("text") or ""
        if not text:
            self.send_json({"error": "missing text"}, status=400)
            return

        msgs = []
        if HERMES_PERSONA:
            msgs.append({"role": "system", "content": HERMES_PERSONA})
        msgs.append({"role": "user", "content": text})
        upstream_body = json.dumps({
            "model": HERMES_MODEL,
            "stream": True,
            "messages": msgs,
        }).encode()
        extra = {"Accept": "text/event-stream"}
        if session_key:
            extra["X-Hermes-Session-Key"] = session_key

        conn = resp = None
        try:
            conn, resp = _hermes_request(
                "POST", "/v1/chat/completions",
                body=upstream_body, extra_headers=extra, timeout=600,
            )
        except Exception as e:
            self.send_json({"error": f"hermes connect failed: {e}"}, status=502)
            if conn:
                conn.close()
            return

        if resp.status != 200:
            detail = b""
            try:
                detail = resp.read()[:500]
            except Exception:
                pass
            self.send_json(
                {"error": f"hermes returned {resp.status}", "detail": detail.decode("utf-8", "replace")},
                status=502,
            )
            conn.close()
            return

        # Stream the SSE through. HTTP/1.0 + connection-close framing lets us
        # write unbounded bytes without chunked encoding (mirrors handle_tts).
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            while True:
                chunk = resp.read(512)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # Browser hit Stop / navigated away — closing the upstream conn
            # below severs the socket to Hermes, aborting the in-flight run.
            pass
        except Exception as e:
            print(f"[hermes] stream error: {e}")
        finally:
            conn.close()

    def handle_autotitle(self):
        if not ((HERMES_BASE_URL and HERMES_API_KEY) or os.environ.get("BANKR_LLM_KEY")
                or os.environ.get("VENICE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
            self.send_json({"error": "no LLM provider configured"}, status=503)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            messages = body.get("messages", [])
            full_messages = [
                {"role": "system", "content": "You generate ultra-short chat tab titles. Reply with ONLY 2-3 words, no punctuation, no explanation, no thinking."},
            ] + messages
            raw = _llm_chat_with_fallback(
                full_messages,
                max_tokens=200,
                hermes_model=HERMES_MODEL,
                bankr_model="minimax-m2.7",
                venice_model="minimax-m27",
                anthropic_model="claude-haiku-4-5",
                timeout=15,
            )
            # strip <think>...</think> reasoning blocks
            import re
            title = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            title = re.sub(r'["""\'\'.,!?:;]', "", title).strip()[:40]
            self.send_json({"title": title})
        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    def handle_filler(self):
        """Bankr/Haiku stall-talk while the main model is still answering.

        Three kinds:
          - "ack":      quick verbal acknowledgement of the user's question
          - "tool":     casual narration of a tool call
          - "thinking": paraphrase of the assistant's inner reasoning delta
        Always answers in <=14 words, first person, no quotes, never answers
        the user's actual question.
        """
        if not (os.environ.get("BANKR_LLM_KEY") or os.environ.get("VENICE_API_KEY")
                or os.environ.get("ANTHROPIC_API_KEY")):
            self.send_json({"error": "no LLM provider configured"}, status=503)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            kind = body.get("kind") or "ack"
            history = body.get("history") or []
            last_user = (body.get("lastUser") or "").strip()[:600]
            tool_name = (body.get("toolName") or "").strip()[:60]
            tool_input = (body.get("toolInput") or "").strip()[:300]
            thinking_text = (body.get("thinkingText") or "").strip()[:600]

            if kind == "ack":
                system = (
                    "You are a voice filling dead air out loud while a "
                    "smarter model composes the real answer. Your ONLY job "
                    "is to make a natural human stall noise so the silence "
                    "isn't awkward. You are NOT answering anything.\n"
                    "\n"
                    "Pull from a WIDE variety and keep it fresh every time. "
                    "Range from a single sound to a short phrase — lean "
                    "short. Mix these registers:\n"
                    "  - bare sounds: 'Hmm.' 'Mmm.' 'Uhh...' 'Hmmm.' "
                    "'Okay.' 'Ummm.' 'Huh.' 'Right.' 'Ah.' 'Welp.'\n"
                    "  - tiny phrases: 'Let me think.' 'Gimme a sec.' "
                    "'Lemme check.' 'One moment.' 'Hold on.' 'Let me look.' "
                    "'Hang on a sec.' 'Lemme dig in.' 'Working on it.' "
                    "'Okay, thinking.' 'Hmm, lemme see.' 'Alright, gimme a "
                    "moment.' 'Let me pull that up.' 'Checking now.'\n"
                    "  - when the request clearly feels big, heavy, or "
                    "tricky, you MAY acknowledge its WEIGHT (never its "
                    "content): 'Oh, that's a heavy one — let me think on "
                    "that.' 'Big question. Gimme a sec.' 'Ooh, tricky one.' "
                    "'That's a good one, lemme sit with it.' 'Hmm, deep "
                    "one.'\n"
                    "\n"
                    "Hard rules:\n"
                    "  - NEVER answer, hint at, or begin to address the "
                    "request. No facts, no opinions, no claims.\n"
                    "  - NEVER reference the actual topic or repeat words "
                    "from their message. Commenting that it's 'big' or "
                    "'tricky' is fine; naming the subject is not.\n"
                    "  - NEVER echo greetings, thanks, or pleasantries.\n"
                    "  - NEVER promise what the answer will be.\n"
                    "\n"
                    "First-person, casual, spoken-aloud. No quotes, no "
                    "emojis. Output ONLY the filler itself."
                )
                user_msg = (
                    f"User's message (for gauging weight ONLY — DO NOT "
                    f"respond to it, DO NOT echo it):\n{last_user}\n\n"
                    "Give ONE fresh stall noise. Vary it — could be a single "
                    "sound, could be a few words. If the request feels big "
                    "or tricky, you may nod to that weight, but never touch "
                    "the topic itself."
                )
            elif kind == "tool":
                system = (
                    "You narrate, casually and out loud, what an AI assistant "
                    "is about to do with a tool. One short sentence, under 14 "
                    "words, first person. No quotes, no emojis."
                )
                user_msg = (
                    f"Tool: {tool_name}\nInput: {tool_input}\n\n"
                    "Casually narrate in one short sentence what you're "
                    "about to do. Examples: 'Let me grep for that.', "
                    "'Pulling up the file now.', 'Running a quick check.'"
                )
            else:  # thinking / reasoning
                system = (
                    "You paraphrase, casually and out loud, the inner thought "
                    "of an AI assistant. One short sentence, under 16 words, "
                    "first person, no quotes."
                )
                user_msg = (
                    f"Inner thought:\n{thinking_text}\n\n"
                    "Paraphrase the gist out loud in one short sentence."
                )

            msgs = [{"role": "system", "content": system}]
            if history:
                ctx = "\n".join(
                    f"{m.get('role')}: {(m.get('content') or '')[:300]}"
                    for m in history[-4:] if m.get("role") and m.get("content")
                )
                if ctx:
                    msgs.append({"role": "user", "content": f"Recent context (for reference, do not respond to it):\n{ctx}"})
                    msgs.append({"role": "assistant", "content": "Got it."})
            msgs.append({"role": "user", "content": user_msg})

            raw = _llm_chat_with_fallback(
                msgs,
                max_tokens=80,
                bankr_model="claude-haiku-4.5",
                venice_model="claude-sonnet-4-6",
                anthropic_model="claude-haiku-4-5",
                timeout=10,
                # High temp on the ack only — its whole value is sounding
                # fresh and varied each time, not correct.
                temperature=(1.0 if kind == "ack" else None),
            )
            import re
            text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            text = text.strip("\"'`").strip()
            text = text[:240]
            self.send_json({"text": text})
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            self.send_json({"error": f"upstream {e.code}: {detail}"}, status=502)
        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    def handle_tts(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            text = (body.get("text") or "").strip()
            if not text:
                self.send_json({"error": "empty text"}, status=400)
                return
            backend = tts_backend()
            if backend == "elevenlabs":
                self._tts_elevenlabs(text[:4000])
            elif backend == "openai":
                self._tts_openai(text[:4000])
            else:
                self.send_json({"error": "no tts backend configured"}, status=503)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            self.send_json({"error": f"upstream {e.code}: {detail}"}, status=502)
        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    def _tts_elevenlabs(self, text):
        api_key = os.environ["ELEVENLABS_API_KEY"]
        voice_id = os.environ.get("ELEVENLABS_VOICE_ID") or "nPczCjzI2devNBz1zQrb"  # Brian
        url = (
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
            "?optimize_streaming_latency=4&output_format=mp3_44100_64"
        )
        req_body = json.dumps({
            "text": text,
            "model_id": "eleven_flash_v2_5",
            # Tuned for a chill, relaxed delivery: lower stability lets the voice
            # breathe and stay loose; speed pulled back below 1.0 so it reads
            # unhurried (it sometimes felt rushed at 1.0).
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.6,
                "use_speaker_boost": True,
                "speed": 0.9,
            },
        }).encode()
        req = urllib.request.Request(
            url,
            data=req_body,
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            method="POST",
        )
        # Pipe ElevenLabs' chunked response straight through to the browser so
        # the first audio bytes hit the client as soon as they're generated.
        # No Content-Length + Connection: close = "read until EOF" streaming
        # (works on HTTP/1.0 without chunked transfer encoding).
        with urllib.request.urlopen(req, timeout=60) as resp:
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            while True:
                chunk = resp.read(2048)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()

    def _tts_openai(self, text):
        api_key = os.environ["OPENAI_API_KEY"]
        req_body = json.dumps({
            "model": "gpt-4o-mini-tts",
            "voice": "onyx",
            "input": text,
            "instructions": TTS_INSTRUCTIONS,
            "response_format": "mp3",
        }).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/speech",
            data=req_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            audio = resp.read()
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(audio)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(audio)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def serve_file(self, name, content_type, extra_headers=None):
        path = Path(__file__).parent / name
        if not path.exists():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
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


if __name__ == "__main__":
    print(f"🕸️  clawd-web → http://127.0.0.1:{PORT}")
    print(f"   hermes    → {HERMES_BASE_URL or 'MISSING — set HERMES_BASE_URL'}"
          + (f"  (pinned → {HERMES_RESOLVE_IP})" if HERMES_RESOLVE_IP else ""))
    print(f"   model     → {HERMES_MODEL}")
    print(f"   key       → {'set' if HERMES_API_KEY else 'MISSING — set HERMES_API_KEY'}")
    print(f"   tts       → {tts_backend()}")
    if not (HERMES_BASE_URL and HERMES_API_KEY):
        print("[warn] Hermes not fully configured — set HERMES_BASE_URL and HERMES_API_KEY (see .env.example)")
    print("   hotkey    → run `python3 hotkey.py` in a separate terminal for Ctrl+.")
    try:
        ThreadedHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        sys.exit(0)
