// apps/api/src/app.ts
// The whole application, network-free. Tests: buildApp(deps) + app.request().
import { Hono } from "hono";
import type { AgentsService, AuthContext } from "@funky/configs";
import { errorHandler, errorResponse } from "./http";
import { auth } from "./middleware/auth";
import { requestId } from "./middleware/request-id";
import { agentRoutes } from "./routes/agents";

export type AppDeps = {
  agents: AgentsService;
  /** null = auth disabled (dev only) */
  authToken: string | null;
  /** liveness of the DB, e.g. () => pool.query("SELECT 1") */
  ping: () => Promise<unknown>;
};

type Env = { Variables: { auth: AuthContext; requestId: string } };

export function buildApp(deps: AppDeps) {
  const app = new Hono<Env>();

  app.use(requestId());

  // unauthenticated by design (k8s probes, load balancers)
  app.get("/healthz", async (c) => {
    await deps.ping();
    return c.json({ status: "ok" });
  });

  app.use("/v1/*", auth(deps.authToken));
  app.route("/v1/agents", agentRoutes(deps.agents));

  app.notFound((c) => errorResponse(c, 404, "not_found_error", "unknown route"));
  app.onError(errorHandler);

  return app;
}
