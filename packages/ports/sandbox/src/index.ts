// packages/ports/sandbox — public surface.
// The worker (Phase E) imports the port; the entrypoint selects a driver by config.

export type { ExecEvent, Executor, SandboxDriver, SandboxHandle } from "./port";
export { SandboxUnavailableError } from "./port";
// SubprocessDriver is NOT a production sandbox option (see makeSandbox / SandboxConfig): it
// runs commands in the worker's own container with no isolation. It stays exported purely as
// the fast, offline in-process driver the test suites — including the chaos warranty — run
// against; production sandboxes are `docker` (local containers) or `e2b` (remote).
export { SubprocessDriver } from "./drivers/subprocess";
export { ComputeSdkDriver, type ComputeSdkDriverOptions, type ComputeProvider } from "./drivers/computesdk";
export { dockerProvider, type DockerProviderOptions } from "./drivers/docker";
export { runSandboxTck } from "./tck";

import { e2b } from "@computesdk/e2b";
import { ComputeSdkDriver } from "./drivers/computesdk";
import { dockerProvider } from "./drivers/docker";
import type { SandboxDriver } from "./port";

export type SandboxConfig =
  | { driver: "docker"; image: string }
  | { driver: "e2b"; apiKey: string; sandboxTimeoutMs?: number };

/** Build a production driver from config. `docker` (the zero-account default) gives each
 *  session a real, isolated container from a base image on the local daemon; `e2b`
 *  provisions an isolated remote sandbox per session via ComputeSDK. Both share
 *  ComputeSdkDriver's idemKey protocol — further providers slot in here without touching
 *  callers. (The in-process SubprocessDriver is test-only; it is not selectable here.) */
export function makeSandbox(cfg: SandboxConfig): SandboxDriver {
  switch (cfg.driver) {
    case "docker":
      return new ComputeSdkDriver({
        providerName: "docker",
        provider: dockerProvider({ image: cfg.image }),
      });
    case "e2b":
      return new ComputeSdkDriver({
        providerName: "e2b",
        provider: e2b({ apiKey: cfg.apiKey }),
        sandboxTimeoutMs: cfg.sandboxTimeoutMs,
      });
    default: {
      const never: never = cfg;
      throw new Error(`unknown sandbox driver: ${JSON.stringify(never)}`);
    }
  }
}
