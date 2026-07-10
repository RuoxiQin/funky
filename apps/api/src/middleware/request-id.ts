// apps/api/src/middleware/request-id.ts
import { createMiddleware } from "hono/factory";
import { v7 as uuidv7 } from "uuid";

export const requestId = () =>
  createMiddleware(async (c, next) => {
    const id = uuidv7();
    c.set("requestId", id);
    c.header("request-id", id);
    await next();
  });
