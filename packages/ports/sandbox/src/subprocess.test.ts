// Runs the sandbox TCK against the subprocess driver. computesdk / container drivers
// add their own <driver>.test.ts calling the same runSandboxTck().
import { SubprocessDriver } from "./drivers/subprocess";
import { runSandboxTck } from "./tck";

runSandboxTck("subprocess", () => new SubprocessDriver());
