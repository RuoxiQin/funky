<img width="2103" height="748" alt="funky_github" src="https://github.com/user-attachments/assets/3433c331-58d6-48bd-aa05-8d605d8fc8ce" />

# Funky

The durable runtime for agent swarms.

Define an agent, give it a sandboxed environment, send it work. Funky handles the durability and the infrastructure.

## Quickstart

Requires Docker. No API key needed.

```bash
git clone https://github.com/funkyhq/funky && cd funky
cp .env.example .env        # set FUNKY_AUTH_TOKEN to any long random string
docker compose up --build
```

The stack is up when the `worker` and `api` services are healthy. Then:

```bash
export TOKEN=<your FUNKY_AUTH_TOKEN>
export H="Authorization: Bearer $TOKEN"
export J="content-type: application/json"

# 1. an agent: who it is and what model it uses
AID=$(curl -s -X POST localhost:3000/v1/agents -H "$H" -H "$J" -d '{
  "name": "shell agent",
  "system_prompt": "You are a helpful engineer. Use the sandbox to run commands.",
  "model": { "provider": "anthropic", "model": "claude-sonnet-5" }
}' | jq -r .id)

# 2. an environment: where its commands run
EID=$(curl -s -X POST localhost:3000/v1/environments -H "$H" -H "$J" -d '{
  "name": "basic"
}' | jq -r .id)

# 3. a session: an agent + an environment, with a sandbox and a durable event log
SID=$(curl -s -X POST localhost:3000/v1/sessions -H "$H" -H "$J" \
  -d "{\"agent\":\"$AID\",\"environment_id\":\"$EID\"}" | jq -r .id)

# 4. watch it think (leave this running)
curl -N -H "$H" localhost:3000/v1/sessions/$SID/events/stream &

# 5. give it work
curl -s -X POST localhost:3000/v1/sessions/$SID/messages -H "$H" -H "$J" \
  -d '{"content":"say hello from the sandbox"}'
```

You'll see the agent provision a sandbox, decide to run a command, execute it, and report
back:

```
event: session_provisioned
event: assistant_message      { "tool_calls": [{ "kind": "exec", "cmd": "echo …" }] }
event: tool_result            { "output": "hello from the funky sandbox\n", "exit_code": 0 }
event: assistant_message      { "content": [{"type":"text","text":"I ran a command…"}] }
event: turn_completed
```

> **Prefer a UI?** The `curl` flow above is also a few clicks in the **Funky Console** — the
> browser dev console that ships with the stack. `docker compose up` serves it at
> http://localhost:5173: create an agent, environment, and session, then chat with the agent
> and watch it run commands in its sandbox — with the equivalent `curl` shown alongside. It's
> a thin client over the same REST API (see [`apps/web`](apps/web)).

<img width="1303" height="755" alt="Screenshot 2026-07-16 at 9 30 32 AM" src="https://github.com/user-attachments/assets/612e7f37-2559-41cd-bb1d-b899d212a4c2" />

### Durability

Funky keeps each session's state in Postgres — the append-only event log is the source of
truth, not any worker's memory. A worker holds no session state between turns: it reads the
log, performs the single next step, and appends the result in one conditional-append
transaction. The durable record of what happened lives in the database, so a worker is a
stateless, replaceable unit.

This is not a design aspiration — it is a **tested property, proven by
[`tests/chaos`](tests/chaos)**. That suite crashes a worker at every append boundary, hands
one job to two workers at once, and races a slow worker against lease expiry — asserting each
time that the event log is byte-for-byte identical, that every command ran **exactly once**,
and that the turn still ends in a terminal event. It is required on `main`: a red chaos run
blocks the release.

> **Honest limits — the default `docker` driver.** Each session gets its own isolated
> container on the local Docker daemon (real filesystem, process, and host-network
> isolation). The container outlives the worker *process*, and because a running command
> records its output and exit code inside the container itself, a replacement worker
> re-attaches by idempotency key and finishes the turn — the idempotent `exec` contract
> guarantees a command never runs twice, whatever the driver. Two honest caveats: the
> container lives on **one Docker host**, so re-attach works within that host but not across
> a multi-host worker fleet (that's what the **E2B** driver is for); and a plain container is
> shared-kernel, so for untrusted workloads you'd run it under gVisor/Kata or use E2B's
> microVMs. (There is also an in-process `subprocess` driver with no isolation — it is not a
> production option; it exists only so the offline test suites, including the chaos warranty
> above, run fast and daemon-free.)

### Using a real model

```bash
# in .env
FUNKY_LLM=ai-sdk
ANTHROPIC_API_KEY=sk-ant-...
```
```bash
docker compose up -d --build worker
```
Now the same curl commands drive a real Claude, writing and running its own shell commands.

### The default sandbox (`docker`)

Out of the box, every session gets its own isolated container on the local Docker daemon —
no cloud account, nothing to configure. `docker compose up` does it all: it builds the
[base image](docker/sandbox.Dockerfile), mounts the daemon socket into the worker, and the
worker runs `docker run` per session and executes commands inside via `docker exec`
(docker-out-of-docker — the sandbox containers are siblings of the stack on your host).

The base image is `debian:trixie-slim` (glibc + GNU coreutils, so agent-driven
`pip`/`npm`/`apt install` stays on the happy path) with `git`, `curl`, `python3`, and `node`
preinstalled and a non-root `agent` user. Swap it with `FUNKY_DOCKER_IMAGE`.

> **Security note.** The default mounts `/var/run/docker.sock` into the worker, granting it
> host-daemon access, and sandbox containers are shared-kernel. That's fine for local or
> trusted use; for untrusted workloads use `FUNKY_SANDBOX=e2b` (remote microVMs) or run the
> sandbox containers under a gVisor/Kata runtime.

Running the worker **outside compose** (`pnpm -F worker dev`) uses your host's Docker
directly; build the image once first:
```bash
docker build -f docker/sandbox.Dockerfile -t funky-sandbox:trixie docker/
```

The docker driver reuses the same [ComputeSDK](https://computesdk.com)-based idemKey
protocol as E2B and answers to the **identical conformance suite** as every other driver;
its cases run whenever a Docker daemon is reachable:
```bash
pnpm -F @funky/sandbox test        # runs the docker TCK against a live daemon (else skips)
```

### Using a remote sandbox (E2B)

```bash
# in .env
FUNKY_SANDBOX=e2b
E2B_API_KEY=e2b_...         # from https://e2b.dev
```
```bash
docker compose up -d --build worker
```
Now every session provisions an isolated [E2B](https://e2b.dev) sandbox, through
[ComputeSDK](https://computesdk.com) so further providers can slot in behind the same
driver. The sandbox — not the worker — holds each command's output and exit code, which is
what makes sessions survive worker death: a replacement worker re-attaches by idempotency
key and reads the same files. Unlike the docker driver this is reachable from **any** worker
host, not just one. Idle sandboxes pause after 30 minutes (`FUNKY_E2B_SANDBOX_TIMEOUT_MS`)
and resume on the next command, filesystem intact.

The E2B driver answers to the identical conformance suite as the subprocess driver; it
runs against real sandboxes when a key is present:
```bash
E2B_API_KEY=e2b_... pnpm -F @funky/sandbox test
```

### Tear down

```bash
docker compose down       # stop and remove the containers
docker compose down -v    # ...and also delete the database volume
```

## Local development

Requires Node 22+, pnpm, and Docker (for Postgres).

```bash
pnpm install

# database
docker run -d --name funky-pg \
  -e POSTGRES_USER=funky -e POSTGRES_PASSWORD=funky -e POSTGRES_DB=funky \
  -p 5432:5432 postgres:16
pnpm -F @funky/db migrate

# run the API with hot reload
pnpm dev
```

Useful commands: `pnpm typecheck` · `pnpm -F @funky/db generate` (new migration after schema changes) · `pnpm -F @funky/db exec drizzle-kit studio` (database browser).

## Layout

```
apps/api           HTTP API (Hono): agents, environments, sessions, SSE
apps/worker        the agent runtime — pulls turns off the queue and drives the loop
apps/web           browser dev console (Vite + React); `docker compose` serves it at :5173
packages/sessions  the event log, the reducer, the turn loop, the job queue
packages/configs   agent + environment config domain logic
packages/ports     provider-neutral ports (llm, sandbox) + their drivers
packages/db        Drizzle schema + migrations
```

`apps` are deployable processes; `packages` are libraries. Apps depend on packages, never the reverse.

## Contributing

This is an early-stage, contracts-first project. The best contribution right now is feedback on the interfaces. Open an issue to discuss the protocol, a missing method, or a backend you'd want to plug in.

## License

[Apache 2.0](./LICENSE).
