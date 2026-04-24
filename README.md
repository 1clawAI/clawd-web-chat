# 🕸️ clawd-web

A minimal browser chat UI that talks **directly** to your local OpenClaw
gateway over its native WebSocket protocol — so the agent keeps its full
memory, tools, and subagents, and you see every tool call stream live.

## Setup

```bash
git clone <this-repo>
cd clawd-web
python3 server.py
# Open http://127.0.0.1:7800 in your browser
```

No pip dependencies. No build step. No API keys required — the token is
auto-read from `~/.openclaw/openclaw.json`.

## First-time gateway config

clawd-web needs two one-time changes to `~/.openclaw/openclaw.json` and
one CLI command so the gateway streams tool events. All local, no external
services.

**1. Allow the clawd-web origin** (required or WebSocket is rejected with 1008):

```json5
"gateway": {
  "controlUi": {
    "allowedOrigins": ["http://localhost:7800", "http://127.0.0.1:7800"]
  }
}
```

Restart the gateway after this.

**2. Pair the device for admin scope** (first connect will create a pending
request):

```bash
openclaw devices list          # grab the pending request id for "clawd-web"
openclaw devices approve <id>  # one-time, remembered after
```

Admin scope is needed so clawd-web can bump the session's `verboseLevel`,
which is what unlocks tool-call events in the live stream.

## Configuration

Defaults come from `~/.openclaw/openclaw.json`. Override via `.env` if you want:

```bash
cp .env.example .env
# edit .env
```

- `PORT` — the clawd-web server port (default `7800`)
- `OPENCLAW_WS_URL` — override the WebSocket URL (default `ws://127.0.0.1:<port>`)
- `OPENCLAW_TOKEN` — override the gateway auth token
- `OPENCLAW_SESSION_KEY` — session to load (default `agent:clawd:main`)

## Features

- **Direct WebSocket** to the OpenClaw gateway (protocol v3)
- **Ed25519 device identity** — keypair generated in-browser, persisted in localStorage
- **Streaming text** as it's generated
- **Live tool-call cards** — every bash/edit/fetch shows as a card (collapsible) with
  the command in the header and DONE/ERROR status pill
- **Inline thinking blocks** when the agent reasons (purple block)
- **Session continuity** — close the tab, come back, full history loads
- **Stop button** — abort a running turn via `chat.abort`
- **Reset session** — `sessions.reset` + fresh transcript

## Protocol

Uses OpenClaw gateway WebSocket v3:

- `connect` handshake with scopes `operator.read`, `operator.write`, `operator.admin`
  and `caps: ["tool-events"]` (required to receive `agent stream=tool` frames)
- `sessions.patch` on connect sets `verboseLevel: "on"` so tool events emit
- `chat.history` on load (default limit 100)
- `chat.send` with `idempotencyKey` for safe retries; returns `{ runId, status }`
- `chat.abort { sessionKey, runId }` to stop a run
- Subscribes to:
  - `chat` events: `state: delta|final|aborted|error`, `message.content` as block array
  - `agent` events: `stream: lifecycle | assistant | tool | thinking | reasoning`

Client id is `"openclaw-control-ui"` — `"webchat-ui"` is blocked from session
patching by the gateway, even with admin scope.

## Debug mode

Open `http://127.0.0.1:7800/?debug=1` to enable console logging and a
`window.__eventLog` buffer of the last 500 chat+agent frames. Useful for
protocol exploration without reading openclaw source.

## Voice

Voice input/output isn't wired yet. This project mirrors the structure of
[`clawd-voice-inline`](https://github.com/austintgriffith/clawd-voice-inline)
so hold-to-talk → Whisper → `chat.send` → streamed reply → macOS `say` can
drop in without restructuring.
