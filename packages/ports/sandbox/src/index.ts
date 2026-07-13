// packages/ports/sandbox — public surface.
// The worker (Phase E) imports the port; the entrypoint selects a driver by config.

export type { ExecEvent, Executor, SandboxDriver, SandboxHandle } from "./port";
export { SandboxUnavailableError } from "./port";
export { SubprocessDriver } from "./drivers/subprocess";
export { runSandboxTck } from "./tck";

import type { SandboxDriver } from "./port";
import { SubprocessDriver } from "./drivers/subprocess";

export type SandboxConfig = { driver: "subprocess" };

/** Build a driver from config. Only `subprocess` exists in v1; container / computesdk
 *  drivers slot in here later without touching callers. */
export function makeSandbox(cfg: SandboxConfig): SandboxDriver {
  switch (cfg.driver) {
    case "subprocess":
      return new SubprocessDriver();
    default: {
      const never: never = cfg.driver;
      throw new Error(`unknown sandbox driver: ${never}`);
    }
  }
}
