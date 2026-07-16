// Runs the sandbox TCK against the subprocess driver. computesdk / container drivers
// add their own <driver>.test.ts calling the same runSandboxTck().
import { randomUUID } from "node:crypto";
import { expect, it } from "vitest";
import { SubprocessDriver } from "./drivers/subprocess";
import { runSandboxTck } from "./tck";

runSandboxTck("subprocess", () => new SubprocessDriver());

it("fails closed for limited network policies", async () => {
  const driver = new SubprocessDriver();
  await expect(
    driver.provision(
      { network: { type: "limited", allowed_hosts: ["api.example.com"] } },
      randomUUID(),
    ),
  ).rejects.toThrow("subprocess driver does not support limited network policies");
});
