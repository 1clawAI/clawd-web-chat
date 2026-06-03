# 🕸️ clawd-web

A minimal browser chat UI that talks to a **Hermes agent** (Nous Research)
over its OpenAI-compatible API server — so you get streaming replies and live
tool-call cards, with the agent's full memory, tools, and skills running on the
Hermes host.

A small Python server (`server.py`) sits between the browser and Hermes. It
holds the Hermes bearer key (which grants Hermes's **full toolset, including
terminal access**), proxies the streaming chat endpoint, and serves the static
UI. The key never reaches the browser.

> Independent community UI — not affiliated with or endorsed by Nous Research.
> "Hermes" refers to the [Hermes agent](https://hermes-agent.nousresearch.com).

## Setup

### 1. Enable the API server on your Hermes box

On the machine running Hermes, add to `~/.hermes/.env`:

```bash
API_SERVER_ENABLED=true
API_SERVER_KEY=<a-strong-secret>
# Bind so clawd-web's machine can reach it. localhost-only by default.
API_SERVER_HOST=0.0.0.0          # or a specific/tailnet interface IP
```

Then start (or restart) the gateway so the API server comes up:

```bash
hermes gateway        # serves the OpenAI-compatible API on :8642 by default
```

> **Security:** the API key gives full agent/tool access (incl. running shell
> commands) on the Hermes host. Prefer binding to a private interface — e.g. a
> [Tailscale](https://tailscale.com) tailnet IP — rather than `0.0.0.0` on an
> open LAN. clawd-web's own server binds to `127.0.0.1` only.

### 2. Configure and run clawd-web

```bash
git clone https://github.com/1clawAI/clawd-web-chat.git
cd clawd-web-chat
cp .env.example .env
# edit .env: set HERMES_BASE_URL + HERMES_API_KEY (never commit .env)
python3 server.py
# Open http://127.0.0.1:7800 in your browser
```

No pip dependencies. No build step.

## Configuration (`.env`)

- `PORT` — the clawd-web server port (default `7800`)
- `HERMES_BASE_URL` — your Hermes API server, e.g. `https://hermes-host:8642`
  (a trailing `/v1` or `/` is fine — it's normalized)
- `HERMES_API_KEY` — the `API_SERVER_KEY` you set on the Hermes box
- `HERMES_MODEL` — model id reported by `/v1/models` (default `hermes-agent`)
- `HERMES_RESOLVE_IP` — *optional.* Pin the hostname to a fixed IP (e.g. a
  Tailscale `100.x` address) when MagicDNS / system DNS can't resolve it. TLS
  still validates against the hostname in `HERMES_BASE_URL`.
- `BANKR_LLM_KEY` / `VENICE_API_KEY` / `ANTHROPIC_API_KEY` — cascade providers
  for auto tab titles + filler stall-talk (see [Auxiliary cascade](#auxiliary-cascade))
- `ELEVENLABS_API_KEY` — preferred TTS backend. Flash v2.5, ~200ms TTFB; server
  streams audio straight through. Default voice is Brian; override with
  `ELEVENLABS_VOICE_ID`.
- `OPENAI_API_KEY` — fallback TTS (`gpt-4o-mini-tts`, onyx voice). Higher
  latency (~2s) but richer instruction steering.
- Without either TTS key, the 🔊 toggle uses the browser's built-in
  `speechSynthesis` voices.

### Verifying connectivity

```bash
curl -H "Authorization: Bearer $HERMES_API_KEY" $HERMES_BASE_URL/v1/models
# → {"object":"list","data":[{"id":"hermes-agent",...}]}
```

## Features

- **Streaming text** straight from Hermes `/v1/chat/completions` (SSE)
- **Live tool-call cards** — Hermes `hermes.tool.progress` events render as cards
  with the command label and a running/done status pill
- **Session continuity** — each tab sends a stable `X-Hermes-Session-Key`, so the
  agent keeps its memory per tab; the UI repaints from a local transcript cache
- **Stop button** — aborts the in-flight request; the server closes its upstream
  socket to Hermes, cancelling the run
- **Reset** — rotates the tab's session key (fresh Hermes session) and clears the
  local transcript
- **Multi-tab** chats, each its own Hermes session

## How it works

```
browser ──HTTP/SSE──▶ server.py ──HTTPS/SSE──▶ Hermes API server
  (UI)                (holds key,             (/v1/chat/completions,
                       proxies, DNS pin)        runs the agent + tools)
```

- `GET /config` — key-free: `{ backend, model, hermesConfigured, ttsBackend }`
- `POST /api/hermes/chat` — `{ sessionKey, text }`; opens the Hermes SSE stream
  with `Authorization: Bearer …` + `X-Hermes-Session-Key`, and pipes the
  `chat.completion.chunk` + `hermes.tool.progress` events back to the browser
- TTS endpoints (`/api/tts`) and the auxiliary cascade (`/api/autotitle`,
  `/api/filler`) are unchanged

## Auxiliary cascade

Tab auto-titles and "filler" stall-talk use a fallback cascade. Hermes is the
primary tier for **titles** (with a tight timeout, then fast cloud fallback);
**filler** stays on the fast cloud models because the full Hermes agent is too
slow to fill a sub-second gap. Order: `hermes → bankr → venice → anthropic`.
Each tier is skipped if its key isn't set.

## Debug mode

Open `http://127.0.0.1:7800/?debug=1` to enable console logging and a
`window.__eventLog` buffer of the last 500 parsed SSE events.

## Voice

The hotkey daemon (`python3 hotkey.py`, needs `pip install pynput`) provides
global hotkeys for mic toggle, view toggle, new tab, history reveal, speech
mode, and panic-mute. See `hotkey.py` for the exact chords.
