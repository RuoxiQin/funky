# gcp_python_modal

A [`SandboxRuntime`](../../proto/funky/sandbox/v1/sandbox_runtime.proto) that runs
each sandbox as a [**Modal Sandbox**](https://modal.com/docs/guide/sandbox) — a
container in Modal's cloud — while the service itself deploys to **GCP Cloud Run**.
The Cloud Run service is a thin front door: it holds no sandbox state and just
translates SandboxRuntime RPCs into Modal API calls, the same way the
[`gcp_python_postgres`](../../session_store/gcp_python_postgres) SessionStore is a
Cloud Run service in front of Cloud SQL.

`CreateSandbox` starts a Modal Sandbox from a base image (default
`python:3.12-slim`) with no entrypoint command, so it stays alive idle until it is
destroyed or its timeout elapses, and returns its Modal object id; `ExecCommand`
runs an argv command inside that Sandbox and returns its exit code plus separate
stdout/stderr; `DestroySandbox` terminates it.

The Sandbox's **Modal object id (`sb-…`) is the sandbox id**, so Modal itself is
the only state the runtime keeps — there is no in-memory registry to lose on a
restart, and the service can scale out across Cloud Run instances without sticky
routing. exec/destroy resolve a sandbox by asking Modal for it by id
(`Sandbox.from_id`); a Sandbox Modal no longer has, or one that has already
finished (terminated or timed out), reads as `NOT_FOUND`.

Provisioning the agent's skills onto the Sandbox at creation (per the
`CreateSandbox` contract) is a no-op for now: `AgentConfig` carries no skills
field yet. The agent is accepted so this stays the place that will load them once
it does.

## Configure

Modal authentication is the SDK's own — set a token pair in the environment (or
`~/.modal.toml`, written by `modal token new`):

| Variable | Required | Meaning |
|---|---|---|
| `MODAL_TOKEN_ID` | yes | Modal token id |
| `MODAL_TOKEN_SECRET` | yes | Modal token secret |

The runtime's own knobs are namespaced `FUNKY_` (kept clear of Modal's reserved
`MODAL_` config namespace); each also has a CLI flag that overrides it:

| Variable | Flag | Default | Meaning |
|---|---|---|---|
| `FUNKY_MODAL_APP_NAME` | `--app-name` | `funky-sandboxes` | Modal App the sandboxes are created under |
| `FUNKY_MODAL_IMAGE` | `--image` | `python:3.12-slim` | base image (registry reference) sandboxes run |
| `FUNKY_SANDBOX_TIMEOUT` | `--timeout` | `3600` | maximum lifetime of a sandbox, in seconds |

## Run it

From the repository root:

```bash
buf generate            # regenerate the protobuf/ConnectRPC stubs into gen/python
uv sync                 # create the workspace venv and install the backend + deps

modal token new         # or export MODAL_TOKEN_ID / MODAL_TOKEN_SECRET
uv run funky-sandbox-runtime-modal --port 8082
```

The server runs on [waitress](https://github.com/Pylons/waitress) (pure Python —
the Modal SDK is synchronous, so this is a sync WSGI stack like the Docker
backend) and speaks ConnectRPC over HTTP/1.1 + JSON, so you can poke it with
`curl` (note proto3 JSON uses camelCase field names, e.g. `agentConfig`,
`systemPrompt`, `sandboxId`, `exitCode`):

```bash
# Create a sandbox -> {"sandbox":{"id":"sb-..."}}
curl -X POST http://127.0.0.1:8082/funky.sandbox.v1.SandboxRuntime/CreateSandbox \
  -H 'Content-Type: application/json' \
  -d '{"agentConfig":{"name":"researcher","model":"gemini-3.5-flash","systemPrompt":"You are a careful research assistant."},"environmentConfig":{}}'

# Run a command in it -> {"stdout":"4\n"}
curl -X POST http://127.0.0.1:8082/funky.sandbox.v1.SandboxRuntime/ExecCommand \
  -H 'Content-Type: application/json' \
  -d '{"sandboxId":"sb-...","command":["python","-c","print(2 + 2)"]}'

# Tear it down -> {}
curl -X POST http://127.0.0.1:8082/funky.sandbox.v1.SandboxRuntime/DestroySandbox \
  -H 'Content-Type: application/json' -d '{"sandboxId":"sb-..."}'
```

The running sandboxes are visible in the [Modal dashboard](https://modal.com/apps)
under the configured App, or with the CLI:

```bash
modal app list
```

## Test

```bash
uv run pytest sandbox_runtime/gcp_python_modal
```

The test boots the server on an ephemeral port and drives it through the
generated ConnectRPC client, covering the create → exec → destroy round trip,
stdout/stderr/exit-code capture, and the NOT_FOUND paths (exec/destroy of an
unknown sandbox, and exec after destroy). Because each created sandbox is a real
container in Modal's cloud (and costs a little), the suite is **skipped unless
Modal is reachable with configured credentials** — the same way the Docker
backend's suite is skipped without a reachable daemon. It uses the
`python:3.12-slim` default image and a short timeout so any straggler self-terminates.

## Deploy to Cloud Run

The [`Dockerfile`](./Dockerfile) builds a self-contained image: it runs
`buf generate` and installs this backend from the committed lockfile, then serves
on `$PORT` bound to all interfaces (Cloud Run's contract). The sandboxes run in
Modal, so the service needs Modal credentials at runtime but no GCP data services
of its own.

> **The build context must be the repository root, not this directory.** The
> backend resolves `funky-protos` from the uv workspace, and `buf generate` reads
> `buf.gen.yaml`, `buf.yaml`, and `proto/` — all at the repo root. Building with
> the package directory as the context fails with
> `read buf.gen.yaml: file does not exist`.

**Cloud Build / Cloud Run trigger** — [`cloudbuild.yaml`](./cloudbuild.yaml) is the
config a Cloud Run continuous-deployment trigger generates (build → push to
Artifact Registry → deploy), with one fix: the Docker build context is the
repository root (`.`), not the package directory. The `_AR_*`, `_SERVICE_NAME`,
and `_DEPLOY_REGION` substitutions carry defaults in the file and are set by the
trigger; `$REPO_NAME` / `$COMMIT_SHA` are Cloud Build built-ins. To run it by hand
from the repository root, supply the built-ins the trigger would inject:

```bash
gcloud builds submit \
  --config sandbox_runtime/gcp_python_modal/cloudbuild.yaml \
  --substitutions=REPO_NAME=funky,COMMIT_SHA=manual
```

**Or build locally** and push (Cloud Run is linux/amd64):

```bash
# From the repository root.
IMAGE="REGION-docker.pkg.dev/PROJECT/REPO/funky-sandbox-runtime-modal"
docker build -f sandbox_runtime/gcp_python_modal/Dockerfile --platform linux/amd64 -t "$IMAGE" .
docker push "$IMAGE"
```

Then deploy the image, supplying the Modal token as Cloud Run secrets:

```bash
gcloud run deploy funky-sandbox-runtime-modal \
  --image "$IMAGE" --region REGION \
  --set-secrets MODAL_TOKEN_ID=modal-token-id:latest,MODAL_TOKEN_SECRET=modal-token-secret:latest \
  --set-env-vars FUNKY_MODAL_APP_NAME=funky-sandboxes
```

Create those secrets once from a Modal token pair (`modal token new` prints them,
or read them from `~/.modal.toml`):

```bash
printf '%s' "$MODAL_TOKEN_ID"     | gcloud secrets create modal-token-id     --data-file=-
printf '%s' "$MODAL_TOKEN_SECRET" | gcloud secrets create modal-token-secret --data-file=-
```

No Cloud SQL connector, VPC egress, or sidecar is needed — the only outbound
dependency is Modal's API over the public internet.
