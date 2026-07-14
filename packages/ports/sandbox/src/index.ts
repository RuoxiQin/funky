// packages/ports/sandbox — public surface.
// The worker (Phase E) imports the port; the entrypoint selects a driver by config.

export type { ExecEvent, Executor, SandboxDriver, SandboxHandle } from "./port";
export { SandboxUnavailableError } from "./port";
export { SubprocessDriver } from "./drivers/subprocess";
export { ComputeSdkDriver, type ComputeSdkDriverOptions, type ComputeProvider } from "./drivers/computesdk";
export { runSandboxTck } from "./tck";

import { e2b } from "@computesdk/e2b";
import { ComputeSdkDriver } from "./drivers/computesdk";
import { SubprocessDriver } from "./drivers/subprocess";
import type { SandboxDriver } from "./port";

export type SandboxConfig =
  | { driver: "subprocess" }
  | { driver: "e2b"; apiKey: string; sandboxTimeoutMs?: number };

/** Build a driver from config. `subprocess` is the zero-setup dev default (commands run
 *  in the worker's own container); `e2b` provisions an isolated remote sandbox per
 *  session via ComputeSDK — further providers slot in here without touching callers. */
export function makeSandbox(cfg: SandboxConfig): SandboxDriver {
  switch (cfg.driver) {
    case "subprocess":
      return new SubprocessDriver();
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
