# Funky

Spin up agent swarms on demand. Define an agent (system prompt + model), give it a sandboxed environment, send it work — Funky handles the durability and the infrastructure.

> **Status: early development.** The agent config API is functional. Environments, sessions, and the agent runtime are in active development.

## Quickstart

Requires Docker.

```bash
git clone https://github.com/funkyhq/funky && cd funky
cp .env.example .env        # set FUNKY_AUTH_TOKEN to any long random string
docker compose up --build
```

The stack is up when `api` reports listening on port 3000. Try it:

```bash
export TOKEN=<your FUNKY_AUTH_TOKEN>

# health
curl -s localhost:3000/healthz

# create an agent
curl -s -X POST localhost:3000/v1/agents \
  -H "Authorization: Bearer $TOKEN" \
  -H "content-type: application/json" \
  -d '{
    "name": "data cruncher",
    "system_prompt": "You are a data analyst.",
    "model": { "provider": "anthropic", "model": "claude-sonnet-5" }
  }'

# list agents
curl -s -H "Authorization: Bearer $TOKEN" localhost:3000/v1/agents
```

Tear down with `docker compose down` (add `-v` to also delete the database).

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
apps/api           HTTP API (Hono)
packages/configs   agent config domain logic
packages/db        Drizzle schema + migrations
```

`apps` are deployable processes; `packages` are libraries. Apps depend on packages, never the reverse.

## Roadmap

- [x] Agent configs (versioned, archive-only) — create/update/list/archive + version history
- [ ] Environment configs
- [ ] Sessions & event log
- [ ] Agent runtime worker (the loop)
- [ ] Sandboxed execution
- [ ] SDKs (TypeScript, Python)

## Contributing

This is an early-stage, contracts-first project. The best contribution right now is feedback on the interfaces. Open an issue to discuss the protocol, a missing method, or a backend you'd want to plug in.

## License

[Apache 2.0](./LICENSE).
