// Tests for the createDb() factory and the `tables` re-export. These stay
// offline: a pg Pool connects lazily, and Drizzle builds SQL synchronously, so
// we can assert wiring and rendered SQL without a running Postgres.

import { Pool } from "pg";
import { describe, expect, it } from "vitest";
import { createDb, tables, type Db } from "./client";
import { agentConfigs, agentConfigVersions, envConfigs } from "./schema";

const DUMMY_URL = "postgres://user:pass@localhost:5432/funky_test";

describe("createDb", () => {
  it("returns a Drizzle query builder without opening a connection", async () => {
    const pool = new Pool({ connectionString: DUMMY_URL });
    try {
      const db: Db = createDb(pool);
      expect(typeof db.select).toBe("function");
      expect(typeof db.insert).toBe("function");
      expect(typeof db.update).toBe("function");
      expect(typeof db.transaction).toBe("function");
    } finally {
      await pool.end(); // no queries ran, so the pool never actually connected
    }
  });

  it("renders schema tables into SQL", async () => {
    const pool = new Pool({ connectionString: DUMMY_URL });
    try {
      const db = createDb(pool);
      const identity = db.select().from(agentConfigs).toSQL();
      expect(identity.sql).toMatch(/from "agent_configs"/);

      const versions = db.select().from(agentConfigVersions).toSQL();
      expect(versions.sql).toMatch(/from "agent_config_versions"/);

      const envs = db.select().from(envConfigs).toSQL();
      expect(envs.sql).toMatch(/from "env_configs"/);
    } finally {
      await pool.end();
    }
  });
});

describe("tables", () => {
  it("re-exports all schema tables by their identifiers", () => {
    expect(tables.agentConfigs).toBe(agentConfigs);
    expect(tables.agentConfigVersions).toBe(agentConfigVersions);
    expect(tables.envConfigs).toBe(envConfigs);
    expect(Object.keys(tables).sort()).toEqual(
      ["agentConfigVersions", "agentConfigs", "envConfigs"].sort(),
    );
  });
});
