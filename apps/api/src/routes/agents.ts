// apps/api/src/routes/agents.ts
// Thin: validate shapes → call service → status code. No Drizzle imports here, ever.
import { Hono } from "hono";
import { zValidator } from "@hono/zod-validator";
import { z, ZodType } from "zod";
import type { AgentsService, AuthContext } from "@funky/configs";
import { errorResponse } from "../http";

type Env = { Variables: { auth: AuthContext; requestId: string } };

// ------------------------------------------------------------ zod schemas

const modelSchema = z
  .object({
    provider: z.enum([
      "anthropic",
      "openai",
      "google",
      "xai",
      "openrouter",
      "togetherai",
      "fireworks",
      "baseten",
    ]),
    model: z.string().min(1),
    max_tokens: z.number().int().min(1).optional(),
    temperature: z.number().min(0).max(2).optional(),
  })
  .strict();

// zod v4: record takes explicit key + value schemas (key length enforced there)
const metadataSchema = z
  .record(z.string().max(64), z.string().max(512))
  .refine((m) => Object.keys(m).length <= 16, "metadata: at most 16 pairs");

const createSchema = z
  .object({
    id: z.uuid().optional(),
    name: z.string().min(1).max(256),
    description: z.string().max(2048).nullish(),
    metadata: metadataSchema.optional(),
    system_prompt: z.string().min(1).max(100_000),
    model: modelSchema,
    tool_policy: z.record(z.string(), z.unknown()).optional(),
  })
  .strict();

const updateSchema = createSchema
  .omit({ id: true })
  .partial()
  .strict()
  .refine((o) => Object.keys(o).length > 0, "at least one field is required");

const listQuerySchema = z.object({
  limit: z.coerce.number().int().min(1).max(100).default(20),
  after_id: z.uuid().optional(),
  include_archived: z
    .enum(["true", "false"])
    .default("false")
    .transform((v) => v === "true"),
});

const versionsQuerySchema = z.object({
  limit: z.coerce.number().int().min(1).max(100).default(20),
  after_version: z.coerce.number().int().min(1).optional(),
});

const validate = <T extends ZodType>(target: "json" | "query", schema: T) =>
  zValidator(target, schema, (result, c) => {
    if (!result.success) {
      const msg = result.error.issues
        .map((i) => `${i.path.map(String).join(".") || "body"}: ${i.message}`)
        .join("; ");
      return errorResponse(c, 400, "invalid_request_error", msg);
    }
  });

// ---------------------------------------------------------------- routes

export function agentRoutes(agents: AgentsService) {
  const r = new Hono<Env>();

  // 1. create
  r.post("/", validate("json", createSchema), async (c) => {
    const { agent, created } = await agents.create(c.get("auth"), c.req.valid("json"));
    return c.json(agent, created ? 201 : 200);
  });

  // 2. list
  r.get("/", validate("query", listQuerySchema), async (c) => {
    const q = c.req.valid("query");
    const page = await agents.list(c.get("auth"), {
      limit: q.limit,
      afterId: q.after_id,
      includeArchived: q.include_archived,
    });
    return c.json(page);
  });

  // 3. retrieve
  r.get("/:id", async (c) => {
    return c.json(await agents.get(c.get("auth"), c.req.param("id")));
  });

  // 4. update (label fields mutate identity; behavior fields mint a version)
  r.post("/:id", validate("json", updateSchema), async (c) => {
    return c.json(await agents.update(c.get("auth"), c.req.param("id"), c.req.valid("json")));
  });

  // 5. archive (idempotent, permanent)
  r.post("/:id/archive", async (c) => {
    return c.json(await agents.archive(c.get("auth"), c.req.param("id")));
  });

  // 6. list versions
  r.get("/:id/versions", validate("query", versionsQuerySchema), async (c) => {
    const q = c.req.valid("query");
    const page = await agents.listVersions(c.get("auth"), c.req.param("id"), {
      limit: q.limit,
      afterVersion: q.after_version,
    });
    return c.json(page);
  });

  // 7. retrieve version
  r.get("/:id/versions/:version", async (c) => {
    const version = Number(c.req.param("version"));
    if (!Number.isInteger(version) || version < 1) {
      return errorResponse(c, 400, "invalid_request_error", "version: must be a positive integer");
    }
    return c.json(await agents.getVersion(c.get("auth"), c.req.param("id"), version));
  });

  return r;
}
