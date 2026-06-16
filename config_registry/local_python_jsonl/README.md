# local_python_jsonl

A fully local [`ConfigRegistry`](../../proto/funky/registry/v1/config_registry.proto)
that stores configs in two append-only JSONL files — no database, no cloud.

- `agents.jsonl` — one line per agent config
- `environments.jsonl` — one line per environment config

Each line is an envelope `{"id": ..., "config": {...}}`, where `config` is the
proto3 JSON form of the spec. Configs are write-once: `Create*` appends a line
and returns its id; `Get*` resolves an id back to the stored config.

## Run it

From the repository root:

```bash
buf generate            # regenerate the protobuf/ConnectRPC stubs into gen/python
uv sync                 # create the workspace venv and install the backend + deps
uv run funky-config-registry-jsonl --data-dir ./data --port 8080
```

The server runs on [waitress](https://github.com/Pylons/waitress) (pure Python,
fully local) and speaks ConnectRPC over HTTP/1.1 + JSON, so you can poke it with
`curl` (note proto3 JSON uses camelCase field names, e.g. `systemPrompt`):

```bash
# Create an agent -> {"id":"agt_..."}
curl -X POST http://127.0.0.1:8080/funky.registry.v1.ConfigRegistry/CreateAgent \
  -H 'Content-Type: application/json' \
  -d '{"config":{"name":"researcher","model":"gemini-3.5-flash","systemPrompt":"You are a careful research assistant."}}'

# Resolve it back
curl -X POST http://127.0.0.1:8080/funky.registry.v1.ConfigRegistry/GetAgent \
  -H 'Content-Type: application/json' \
  -d '{"id":"agt_..."}'

# Environments work the same way (config is empty for now)
curl -X POST http://127.0.0.1:8080/funky.registry.v1.ConfigRegistry/CreateEnvironment \
  -H 'Content-Type: application/json' -d '{"config":{}}'
```

The written files are human-readable:

```bash
cat data/agents.jsonl data/environments.jsonl
```

## Test

```bash
uv run pytest config_registry/local_python_jsonl
```

The test boots the server on an ephemeral port and drives it through the
generated ConnectRPC client, covering the agent and environment round trips and
the NOT_FOUND path.
