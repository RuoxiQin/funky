// apps/api/src/routes/sessions.ts
// Thin: validate shapes → call service → status code. No Drizzle imports here, ever.
// The one place that deviates from the thin pattern is the SSE stream, which drives the
// in-process fan-out (see ../sse.ts); even there the log stays the source of truth.
import { Hono } from "hono";
import { streamSSE } from "hono/streaming";
import { z } from "zod";
import type { AuthContext } from "@funky/configs";
import type { EventStore, SessionsService } from "@funky/sessions";
import type { EventBus } from "../sse";
import { runSseStream } from "../sse";
import { listQuerySchema, metadataSchema, validate } from "./common";

type Env = { Variables: { auth: AuthContext; requestId: string } };

export type SessionRoutesDeps = {
  sessions: SessionsService;
  store: EventStore;
  bus: EventBus;
};

// ------------------------------------------------------------ zod schemas

// A bare uuid string ("latest version, resolved now") OR an explicit { id, version }.
const agentRefSchema = z.union([
  z.uuid(),
  z.object({ id: z.uuid(), version: z.number().int().min(1) }).strict(),
]);

const createSchema = z
  .object({
    id: z.uuid().optional(),
    agent: agentRefSchema,
    environment_id: z.uuid(),
    title: z.string().max(256).nullish(),
    metadata: metadataSchema.optional(),
  })
  .strict();

const messageSchema = z
  .object({
    content: z.string().min(1).max(100_000),
  })
  .strict();

const eventsQuerySchema = z.object({
  after_seq: z.coerce.number().int().min(0).default(0),
  limit: z.coerce.number().int().min(1).max(500).default(100),
});

// ---------------------------------------------------------------- routes

export function sessionRoutes(deps: SessionRoutesDeps) {
  const { sessions, store, bus } = deps;
  const r = new Hono<Env>();

  // 1. create (client-supplied id → idempotent). status = "provisioning".
  r.post("/", validate("json", createSchema), async (c) => {
    const { session, created } = await sessions.create(c.get("auth"), c.req.valid("json"));
    return c.json(session, created ? 201 : 200);
  });

  // 2. list
  r.get("/", validate("query", listQuerySchema), async (c) => {
    const q = c.req.valid("query");
    const page = await sessions.list(c.get("auth"), {
      limit: q.limit,
      afterId: q.after_id,
      includeArchived: q.include_archived,
    });
    return c.json(page);
  });

  // 3. retrieve
  r.get("/:id", async (c) => {
    return c.json(await sessions.get(c.get("auth"), c.req.param("id")));
  });

  // 4. archive (idempotent, permanent; blocks new messages, keeps the sandbox)
  r.post("/:id/archive", async (c) => {
    return c.json(await sessions.archive(c.get("auth"), c.req.param("id")));
  });

  // 5. send message — the money path (append user_message + enqueue turn, one tx)
  r.post("/:id/messages", validate("json", messageSchema), async (c) => {
    const { content } = c.req.valid("json");
    const result = await sessions.sendMessage(c.get("auth"), c.req.param("id"), content);
    return c.json(result, 202);
  });

  // 6. paginated event log
  r.get("/:id/events", validate("query", eventsQuerySchema), async (c) => {
    const q = c.req.valid("query");
    const page = await sessions.getEvents(c.get("auth"), c.req.param("id"), {
      afterSeq: q.after_seq,
      limit: q.limit,
    });
    return c.json(page);
  });

  // 7. SSE — replay from the cursor, then live off the fan-out
  r.get("/:id/events/stream", async (c) => {
    const ctx = c.get("auth");
    const id = c.req.param("id");
    // Existence + tenancy check up front so a 404 gets the normal JSON envelope, not a
    // half-opened stream.
    await sessions.get(ctx, id);

    // Start cursor: Last-Event-ID (browser EventSource sends it on reconnect), else the
    // explicit ?after_seq, else 0.
    const lastEventId = c.req.header("Last-Event-ID");
    const afterSeq = c.req.query("after_seq");
    let cursor = 0;
    if (lastEventId !== undefined && /^\d+$/.test(lastEventId)) cursor = Number(lastEventId);
    else if (afterSeq !== undefined && /^\d+$/.test(afterSeq)) cursor = Number(afterSeq);

    // Stops nginx/Caddy from buffering the stream (works locally, mysteriously buffers
    // behind a proxy without it). streamSSE sets the text/event-stream headers itself.
    c.header("X-Accel-Buffering", "no");
    return streamSSE(c, (stream) =>
      runSseStream(stream, { store, bus, namespace: ctx.namespace, sessionId: id, cursor }),
    );
  });

  return r;
}
