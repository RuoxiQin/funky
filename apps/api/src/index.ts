// apps/api/src/index.ts — the ONLY file that touches process.env or the network.
import "dotenv/config"; // dev convenience; production containers inject env directly
import { serve } from "@hono/node-server";
import { Pool } from "pg";
import { createDb } from "@funky/db";
import { AgentsService } from "@funky/configs";
import { buildApp } from "./app";
import { loadConfig } from "./config";
import { config } from "dotenv";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// repo root .env, resolved from this file's location (cwd-independent)
config({ path: resolve(dirname(fileURLToPath(import.meta.url)), "../../../.env") });

const cfg = loadConfig();

const pool = new Pool({
  connectionString: cfg.databaseUrl,
  max: cfg.dbPoolMax,
});

const db = createDb(pool);

const app = buildApp({
  agents: new AgentsService(db),
  authToken: cfg.authToken,
  ping: () => pool.query("SELECT 1"),
});

const server = serve({ fetch: app.fetch, port: cfg.port }, (info) => {
  console.log(`funky-api listening on http://localhost:${info.port}`);
});

// Graceful shutdown: stop accepting → close connections → release the pool.
async function shutdown(signal: string) {
  console.log(`${signal} received, shutting down`);
  server.close(async () => {
    await pool.end();
    process.exit(0);
  });
  // safety net: force-exit if close hangs (stuck keep-alives)
  setTimeout(() => process.exit(1), 10_000).unref();
}

process.on("SIGTERM", () => void shutdown("SIGTERM"));
process.on("SIGINT", () => void shutdown("SIGINT"));
