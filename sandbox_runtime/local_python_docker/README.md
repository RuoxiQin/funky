# local_python_docker

A fully local [`SandboxRuntime`](../../proto/funky/sandbox/v1/sandbox_runtime.proto)
that runs each sandbox as a long-lived [Docker](https://www.docker.com/)
container — no cloud, no remote provider, just the Docker daemon on your machine.

`CreateSandbox` starts a container from a base image (default
`python:3.12-slim`) and keeps it alive with `tail -f /dev/null`, mints a `sbx_`
id, and returns it; `ExecCommand` runs an argv command inside that container with
`docker exec` and returns its exit code plus separate stdout/stderr bytes;
`DestroySandbox` force-removes the container.

The container's **name is the sandbox id**, so Docker itself is the only state
the runtime keeps — there is no in-memory registry to lose on a restart, and
exec/destroy just ask the daemon for the container by name. Every container is
tagged with a `funky.sandbox=true` label, so any left behind by a crash are easy
to find and reap (`docker ps -a --filter label=funky.sandbox`).

Provisioning the agent's skills onto the container at creation (per the
`CreateSandbox` contract) is a no-op for now: `AgentConfig` carries no skills
field yet. The agent is accepted so this stays the place that will load them once
it does.

## Requirements

A reachable Docker daemon. The runtime connects with `docker.from_env()`, which
honours `DOCKER_HOST` and the usual socket/env setup. The base image is pulled
automatically on first use if it is not already present.

## Run it

From the repository root:

```bash
buf generate            # regenerate the protobuf/ConnectRPC stubs into gen/python
uv sync                 # create the workspace venv and install the backend + deps
uv run funky-sandbox-runtime-docker --image python:3.12-slim --port 8082
```

The server runs on [waitress](https://github.com/Pylons/waitress) (pure Python)
and speaks ConnectRPC over HTTP/1.1 + JSON, so you can poke it with `curl` (note
proto3 JSON uses camelCase field names, e.g. `agentConfig`, `systemPrompt`,
`sandboxId`, `exitCode`):

```bash
# Create a sandbox -> {"sandbox":{"id":"sbx_..."}}
curl -X POST http://127.0.0.1:8082/funky.sandbox.v1.SandboxRuntime/CreateSandbox \
  -H 'Content-Type: application/json' \
  -d '{"agentConfig":{"name":"researcher","model":"gemini-3.5-flash","systemPrompt":"You are a careful research assistant."},"environmentConfig":{}}'

# Run a command in it -> {"stdout":"4\n"}
curl -X POST http://127.0.0.1:8082/funky.sandbox.v1.SandboxRuntime/ExecCommand \
  -H 'Content-Type: application/json' \
  -d '{"sandboxId":"sbx_...","command":["python","-c","print(2 + 2)"]}'

# Tear it down -> {}
curl -X POST http://127.0.0.1:8082/funky.sandbox.v1.SandboxRuntime/DestroySandbox \
  -H 'Content-Type: application/json' -d '{"sandboxId":"sbx_..."}'
```

The running containers are visible to plain Docker:

```bash
docker ps --filter label=funky.sandbox
```

## Test

```bash
uv run pytest sandbox_runtime/local_python_docker
```

The test boots the server on an ephemeral port and drives it through the
generated ConnectRPC client, covering the create → exec → destroy round trip,
stdout/stderr/exit-code capture, and the NOT_FOUND paths (exec/destroy of an
unknown sandbox, and exec after destroy). It needs a running Docker daemon and is
skipped automatically when none is reachable; it uses the small `alpine` image
rather than the `python:3.12-slim` default to keep the pull cheap.
