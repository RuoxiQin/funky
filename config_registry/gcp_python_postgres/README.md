# gcp_python_postgres

A [`ConfigRegistry`](../../proto/funky/registry/v1/config_registry.proto) backed
by a **GCP Cloud SQL (Postgres)** database. It reaches the instance through the
[Cloud SQL Python Connector](https://github.com/GoogleCloudPlatform/cloud-sql-python-connector)
with the async [`asyncpg`](https://github.com/MagicStack/asyncpg) driver, and
maps rows with the [SQLAlchemy](https://www.sqlalchemy.org/) ORM for readability.

Two tables mirror the JSONL backend's two files:

- `agents` — one row per agent config: its `agt_` id and the `AgentConfig` (as
  `JSONB`).
- `environments` — one row per environment config: its `env_` id and the
  `EnvironmentConfig` (as `JSONB`).

Configs are write-once specs: `CreateAgent` / `CreateEnvironment` persist a
config under a freshly minted id and return it; `GetAgent` / `GetEnvironment`
resolve an id back to the stored config (or `NOT_FOUND`).

The server is async end to end: the generated `ConfigRegistryASGIApplication`
served on [uvicorn](https://www.uvicorn.org/), an async store over a SQLAlchemy
async engine, and asyncpg under the connector.

## Configure

The server reads the Cloud SQL connection from the environment:

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `INSTANCE_CONNECTION_NAME` | yes | — | `project:region:instance` |
| `DB_USER` | yes | — | database user |
| `DB_NAME` | yes | — | database name |
| `DB_PASS` | no | _(empty)_ | password (omit when using IAM auth) |
| `DB_IP_TYPE` | no | `public` | `public`, `private`, or `psc` |
| `DB_IAM_AUTH` | no | `false` | use IAM database authentication |

The connector authenticates with [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials),
so `gcloud auth application-default login` (or a service-account key /
Workload Identity in deployment) must be in place.

## Run it

From the repository root:

```bash
buf generate            # regenerate the protobuf/ConnectRPC stubs into gen/python
uv sync                 # create the workspace venv and install the backend + deps

gcloud auth application-default login   # credentials for the Cloud SQL connector

export INSTANCE_CONNECTION_NAME="my-project:us-central1:my-instance"
export DB_USER="funky" DB_NAME="funky" DB_PASS="..."
uv run funky-config-registry-postgres --port 8080
```

It speaks ConnectRPC over HTTP/1.1 + JSON, so you can poke it with `curl` (proto3
JSON uses camelCase field names, e.g. `systemPrompt`):

```bash
# Create an agent -> {"id":"agt_..."}
curl -X POST http://127.0.0.1:8080/funky.registry.v1.ConfigRegistry/CreateAgent \
  -H 'Content-Type: application/json' \
  -d '{"config":{"name":"researcher","model":"gemini-3.5-flash","systemPrompt":"You are a careful research assistant."}}'

# Resolve it back
curl -X POST http://127.0.0.1:8080/funky.registry.v1.ConfigRegistry/GetAgent \
  -H 'Content-Type: application/json' -d '{"id":"agt_..."}'

# Environments work the same way (config is empty for now)
curl -X POST http://127.0.0.1:8080/funky.registry.v1.ConfigRegistry/CreateEnvironment \
  -H 'Content-Type: application/json' -d '{"config":{}}'

# Resolve it back
curl -X POST http://127.0.0.1:8080/funky.registry.v1.ConfigRegistry/GetEnvironment \
  -H 'Content-Type: application/json' -d '{"id":"env_..."}'
```

## Test

```bash
uv run pytest config_registry/gcp_python_postgres
```

The test boots the server on an ephemeral port and drives it through the
generated ConnectRPC client, covering the agent and environment round trips, that
the two id spaces stay separate, and the NOT_FOUND paths. Because the ORM is
engine-agnostic it runs against an **in-process SQLite** database by default — no
Cloud SQL instance needed. To run the identical suite against a real Postgres,
point it at a disposable async URL:

```bash
FUNKY_CONFIG_REGISTRY_TEST_DATABASE_URL="postgresql+asyncpg://user:pass@localhost/funky_test" \
  uv run pytest config_registry/gcp_python_postgres
```

## Deploy to Cloud Run

The [`Dockerfile`](./Dockerfile) builds a self-contained image: it runs
`buf generate` and installs this backend from the committed lockfile, then serves
on `$PORT` bound to all interfaces (Cloud Run's contract).

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
trigger; `$REPO_NAME` / `$COMMIT_SHA` are Cloud Build built-ins. To run it by
hand from the repository root, supply the built-ins the trigger would inject:

```bash
gcloud builds submit \
  --config config_registry/gcp_python_postgres/cloudbuild.yaml \
  --substitutions=REPO_NAME=funky,COMMIT_SHA=manual
```

**Or build locally** and push (Cloud Run is linux/amd64):

```bash
# From the repository root.
IMAGE="REGION-docker.pkg.dev/PROJECT/REPO/funky-config-registry-postgres"
docker build -f config_registry/gcp_python_postgres/Dockerfile --platform linux/amd64 -t "$IMAGE" .
docker push "$IMAGE"
```

Then deploy the image:

```bash
gcloud run deploy funky-config-registry-postgres \
  --image "$IMAGE" --region REGION \
  --service-account funky-runtime@PROJECT.iam.gserviceaccount.com \
  --set-env-vars INSTANCE_CONNECTION_NAME=PROJECT:REGION:INSTANCE,DB_USER=funky,DB_NAME=funky \
  --set-secrets DB_PASS=funky-db-pass:latest
```

The connector authenticates as the Cloud Run service account, so grant it
`roles/cloudsql.client` — no `gcloud auth ...` and no Cloud SQL proxy sidecar are
needed. For IAM database auth, drop `DB_PASS` and set `DB_IAM_AUTH=true`. For a
private-IP instance, set `DB_IP_TYPE=private` and give the service [Direct VPC
egress](https://cloud.google.com/run/docs/configuring/vpc-direct-vpc) (or a
Serverless VPC Access connector) onto the instance's network.
