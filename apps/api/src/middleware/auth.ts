// apps/api/src/middleware/auth.ts
// Static-token authenticator (the OSS implementation of the auth port).
// Managed swaps this middleware for key lookup → AuthContext{ns, scopes}.
import { createHash, timingSafeEqual } from "node:crypto";
import { createMiddleware } from "hono/factory";
import type { AuthContext } from "@funky/configs";
import { errorResponse } from "../http";

const STATIC_CONTEXT: AuthContext = { namespace: "default", principal: "token:default" };

/** token === null means FUNKY_AUTH=disabled (dev only; config.ts already warned). */
export const auth = (token: string | null) =>
  createMiddleware(async (c, next) => {
    if (token !== null) {
      const header = c.req.header("authorization") ?? "";
      const presented = header.startsWith("Bearer ") ? header.slice(7) : "";
      if (!timingSafeEq(presented, token)) {
        return errorResponse(c, 401, "authentication_error", "invalid or missing API token");
      }
    }
    c.set("auth", STATIC_CONTEXT);
    await next();
  });

// Hash both sides to equalize length; timingSafeEqual requires equal-length buffers.
function timingSafeEq(a: string, b: string): boolean {
  const ha = createHash("sha256").update(a).digest();
  const hb = createHash("sha256").update(b).digest();
  return timingSafeEqual(ha, hb);
}
