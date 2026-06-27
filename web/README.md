# funky-web

**Funky** — a browser chat UI for creating and talking to AI agents, in a minimal
pixel-art / retro-game style. A Vite + React + TypeScript frontend for the local
Funky client ([`client/local_python`](../client/local_python)).

It drives the client's REST API end to end: create an agent, open a session, and
send messages — each message runs one real agent turn (a billed Anthropic call in
a fresh Docker sandbox) and the response streams back into the chat.

![three states: first run, the New Agent modal, and a live conversation]

## Run it

Two ways, both serving the UI at <http://localhost:5173>.

### Option A — the whole stack with Docker Compose (recommended)

From the repo root, this builds and serves the frontend alongside the backends:

```bash
cd ..                        # repo root
cp .env.example .env         # then put your ANTHROPIC_API_KEY in it
docker compose up --build    # backends, client (:8000), and the web UI (:5173)
```

The `web` service builds the production bundle and serves it with nginx, which
reverse-proxies `/v1` and `/health` to the `client` service (so the browser stays
same-origin — no CORS). There's no hot reload, so use Option B when iterating on
the UI.

### Option B — Vite dev server (for working on the UI, with hot reload)

Bring up the stack so the client is reachable on `:8000` (`docker compose up` from
the repo root), then:

```bash
npm install
npm run dev          # http://localhost:5173 (or the next free port)
```

The dev server proxies the API to the client itself, so this works even while the
Compose `web` service is running (Vite just picks the next free port).

Either way, open the UI and click **+ NEW AGENT** (pre-filled with a sample),
create it, then type a message and hit **SEND** (or Enter).

### How it connects (no CORS, no backend changes)

The Funky client ships no CORS headers, so the browser never calls it
cross-origin — a proxy sits in front and forwards the API paths, keeping every
request same-origin. In dev that proxy is the Vite dev server (`vite.config.ts`);
under Docker Compose it's nginx (`nginx.conf`). The dev-server path:

```
browser ──/v1/*, /health──> Vite dev server (:5173) ──proxy──> client (:8000)
```

Point the dev proxy at a client on a different host/port with `VITE_API_TARGET`:

```bash
VITE_API_TARGET=http://192.168.1.50:8000 npm run dev
```

(`.env.example` lists the available overrides.)

## What it does

The four-step flow from the client's REST API, wired to the UI:

| UI action | Calls |
|---|---|
| **+ NEW AGENT** → CREATE | `POST /v1/environments` (once, cached) → `POST /v1/agents` → `POST /v1/sessions` |
| Click **+** on the tab strip | `POST /v1/sessions` (new session for the agent) |
| Type + **SEND** | `POST /v1/sessions/{id}/messages` → renders the returned events |

A turn returns agent text, plus any `bash` tool calls the agent made and their
results — text becomes chat bubbles; tool calls/results render as compact rows
beneath them.

### Models

The modal's three buttons map to the model strings the agent-service sends to
Anthropic (`src/lib/models.ts`):

| Button | Model id |
|---|---|
| Opus 4.8 | `claude-opus-4-8` |
| Sonnet 4.6 | `claude-sonnet-4-6` |
| Haiku 4.5 | `claude-haiku-4-5-20251001` |

### State & persistence

The REST API has no "list agents" or "list history" endpoint — `send` is the only
call that returns events — so the **frontend is the source of truth** for which
agents/sessions exist and what was said. State persists to `localStorage` and is
restored on reload.

If you reset the backend stores (`docker compose down -v`), the persisted ids go
stale and calls will 404. Click **↺ reset** in the sidebar (bottom-left) to clear
local data and start fresh.

## Scripts

```bash
npm run dev          # dev server with API proxy + HMR
npm run build        # tsc typecheck + production build to dist/
npm run typecheck    # types only
npm run preview      # serve the production build
```

## Project layout

```
src/
  api/        REST client (client.ts) + wire types (types.ts)
  lib/        models, avatar letter, localStorage, event→ChatItem mapping
  state/      useFunkyStore — reducer + async actions for the backend flow
  components/ Sidebar, SessionTabs, Conversation, ChatMessage, Composer,
              CreateAgentModal, Mascot, Avatar, TypingIndicator, …
  styles.css  the Paper skin: tokens, pixel borders, hard shadows, animations
  App.tsx     the shell
```

## Design

Recreates the **Paper** skin from the design reference (pixel borders, hard offset
shadows, no rounded corners; Press Start 2P for UI labels, VT323 for body). The
two alternate skins (Arcade, Midnight) are not implemented; the token set in
`styles.css` (`:root`) is the single place to retheme.
