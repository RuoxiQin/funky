// apps/api/src/routes/common.ts
// zod schemas + the validate wrapper shared by every resource's route file.
import { zValidator } from "@hono/zod-validator";
import { z, ZodType } from "zod";
import { errorResponse } from "../http";

// zod v4: record takes explicit key + value schemas (key length enforced there)
export const metadataSchema = z
  .record(z.string().max(64), z.string().max(512))
  .refine((m) => Object.keys(m).length <= 16, "metadata: at most 16 pairs");

export const listQuerySchema = z.object({
  limit: z.coerce.number().int().min(1).max(100).default(20),
  after_id: z.uuid().optional(),
  include_archived: z
    .enum(["true", "false"])
    .default("false")
    .transform((v) => v === "true"),
});

export const validate = <T extends ZodType>(target: "json" | "query", schema: T) =>
  zValidator(target, schema, (result, c) => {
    if (!result.success) {
      const msg = result.error.issues
        .map((i) => `${i.path.map(String).join(".") || "body"}: ${i.message}`)
        .join("; ");
      return errorResponse(c, 400, "invalid_request_error", msg);
    }
  });
