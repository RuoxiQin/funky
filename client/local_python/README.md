# funky-client-local

The thin **Client** from the [architecture](../../docs/architecture.mmd) behind a
small REST API, for local and Docker Compose use. It wires the four Funky services
together over their generated ConnectRPC clients and exposes them as one JSON/REST
endpoint, so another service can run a whole agent turn without talking to the four
backends directly.

This is the local sibling of [`gcp_python`](../gcp_python): the same orchestration,
but it calls the backends over plain HTTP with no auth (the Cloud Run variant adds
OIDC ID tokens so the backends can be deployed private) and ships no deploy
artifacts.

```
ConfigRegistry   SessionStore   SandboxRuntime   AgentService
       \              |               |              /
        \             |               |             /
                 funky-client-local (this) ── REST ──> your service
```

## The REST API

JSON in, JSON out, snake_case throughout:

| Method & path | Body | Returns |
|---|---|---|
| `GET /health` | — | `{"status": "ok"}` |
| `POST /v1/agents` | `{"name", "model", "system_prompt"}` | `{"id": "agt_..."}` |
| `POST /v1/environments` | `{}` (optional) | `{"id": "env_..."}` |
| `POST /v1/sessions` | `{"agent_id", "environment_id"}` | `{"id": "ses_..."}` |
| `POST /v1/sessions/{id}/messages` | `{"prompt"}` | `{"events": [...]}` |

`messages` runs one agent turn and returns the events it produced.

## Run it

From the repository root:

```bash
buf generate            # regenerate the protobuf/ConnectRPC stubs into gen/python
uv sync                 # create the workspace venv and install the client + deps
uv run funky-client-local-server --host 127.0.0.1 --port 8000
```

It reads the four backend URLs from the environment, each with a localhost default
matching the backends' own ports — `CONFIG_REGISTRY_URL` (`:8080`),
`SESSION_STORE_URL` (`:8081`), `SANDBOX_RUNTIME_URL` (`:8082`),
`AGENT_SERVICE_URL` (`:8083`) — so in Docker Compose you point it at the sibling
services by name:

```bash
CONFIG_REGISTRY_URL=http://config-registry:8080 \
SESSION_STORE_URL=http://session-store:8081 \
SANDBOX_RUNTIME_URL=http://sandbox-runtime:8082 \
AGENT_SERVICE_URL=http://agent-service:8083 \
  funky-client-local-server --host 0.0.0.0 --port 8000
```

Then drive a turn with `curl`:

```bash
# Create an agent -> {"id":"agt_..."}
curl -s -X POST http://127.0.0.1:8000/v1/agents \
  -H 'Content-Type: application/json' \
  -d '{"name":"coder","model":"claude-sonnet-4-6","system_prompt":"Be brief."}'

# Open an environment and a session, then send a message
curl -s -X POST http://127.0.0.1:8000/v1/environments -d '{}'
curl -s -X POST http://127.0.0.1:8000/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"agt_...","environment_id":"env_..."}'
curl -s -X POST http://127.0.0.1:8000/v1/sessions/ses_.../messages \
  -H 'Content-Type: application/json' -d '{"prompt":"List the files in the repo."}'
```

## Test

```bash
uv run pytest client/local_python
```

The tests drive the REST app and the orchestrator against in-memory fakes of the
four services — no backends needed.
