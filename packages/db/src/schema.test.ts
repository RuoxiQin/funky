// Schema-shape regression tests: assert the Drizzle table definitions in
// schema/configs.ts still match the physical shape the migrations created.
// These run without a database — getTableConfig() reflects the in-memory model,
// so a rename, a dropped NOT NULL, a changed default, or a broken PK/FK/index
// fails here loudly instead of silently drifting from migrations/.

import { getTableConfig, type PgTable } from "drizzle-orm/pg-core";
import { describe, expect, it } from "vitest";
import { agentConfigs, agentConfigVersions, envConfigs, type ModelConfig } from "./schema";

type ColSpec = {
  type: string; // getSQLType() output, e.g. "uuid", "timestamp with time zone"
  notNull: boolean;
  hasDefault?: boolean;
  default?: unknown; // deep-equal check; omit for SQL defaults like now()
  primary?: boolean; // inline single-column primary key
};

function columnsByName(table: PgTable) {
  return new Map(getTableConfig(table).columns.map((c) => [c.name, c]));
}

/** Assert the table has exactly `expected`'s columns, each with the given shape. */
function assertColumns(table: PgTable, expected: Record<string, ColSpec>) {
  const cols = columnsByName(table);
  expect([...cols.keys()].sort(), "column set drifted (added/removed column)").toEqual(
    Object.keys(expected).sort(),
  );
  for (const [name, spec] of Object.entries(expected)) {
    const col = cols.get(name);
    expect(col, `missing column ${name}`).toBeDefined();
    expect(col!.getSQLType(), `${name}.type`).toBe(spec.type);
    expect(col!.notNull, `${name}.notNull`).toBe(spec.notNull);
    if (spec.hasDefault !== undefined) {
      expect(col!.hasDefault, `${name}.hasDefault`).toBe(spec.hasDefault);
    }
    if (spec.default !== undefined) {
      expect(col!.default, `${name}.default`).toEqual(spec.default);
    }
    if (spec.primary !== undefined) {
      expect(col!.primary, `${name}.primary`).toBe(spec.primary);
    }
  }
}

function indexSummaries(table: PgTable) {
  return getTableConfig(table)
    .indexes.map((i) => ({
      name: i.config.name ?? "", // named indexes only here; guard the type anyway
      columns: i.config.columns.map((c) => (c as { name?: string }).name),
      unique: i.config.unique,
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

// ---------------------------------------------------------------- agent_configs

describe("agent_configs", () => {
  it("has the expected table name", () => {
    expect(getTableConfig(agentConfigs).name).toBe("agent_configs");
  });

  it("columns match the migration", () => {
    assertColumns(agentConfigs, {
      id: { type: "uuid", notNull: true, primary: true },
      namespace: { type: "text", notNull: true },
      name: { type: "text", notNull: true },
      description: { type: "text", notNull: false },
      metadata: { type: "jsonb", notNull: true, hasDefault: true, default: {} },
      latest_version: { type: "integer", notNull: true, hasDefault: true, default: 1 },
      created_at: { type: "timestamp with time zone", notNull: true, hasDefault: true },
      updated_at: { type: "timestamp with time zone", notNull: true, hasDefault: true },
      archived_at: { type: "timestamp with time zone", notNull: false },
    });
  });

  it("uses an inline primary key on id (no composite PK, no FKs)", () => {
    const cfg = getTableConfig(agentConfigs);
    expect(cfg.primaryKeys, "identity uses an inline PK, not a composite one").toHaveLength(0);
    expect(cfg.foreignKeys, "identity table references nothing").toHaveLength(0);
  });

  it("has the two namespace lookup indexes, both non-unique", () => {
    // name is a display label, not a reference — the (namespace, name) index must
    // stay non-unique so duplicate names within a namespace are allowed.
    expect(indexSummaries(agentConfigs)).toEqual([
      { name: "agent_configs_ns", columns: ["namespace"], unique: false },
      { name: "agent_configs_ns_name", columns: ["namespace", "name"], unique: false },
    ]);
  });
});

// -------------------------------------------------------- agent_config_versions

describe("agent_config_versions", () => {
  it("has the expected table name", () => {
    expect(getTableConfig(agentConfigVersions).name).toBe("agent_config_versions");
  });

  it("columns match the migration", () => {
    assertColumns(agentConfigVersions, {
      agent_config_id: { type: "uuid", notNull: true },
      version: { type: "integer", notNull: true },
      namespace: { type: "text", notNull: true },
      system_prompt: { type: "text", notNull: true },
      model: { type: "jsonb", notNull: true },
      tool_policy: { type: "jsonb", notNull: true, hasDefault: true, default: {} },
      created_at: { type: "timestamp with time zone", notNull: true, hasDefault: true },
      created_by: { type: "text", notNull: false },
    });
  });

  it("has the composite primary key (agent_config_id, version)", () => {
    const pks = getTableConfig(agentConfigVersions).primaryKeys;
    expect(pks).toHaveLength(1);
    expect(pks[0]?.columns.map((c) => c.name)).toEqual(["agent_config_id", "version"]);
  });

  it("references agent_configs.id via agent_config_id", () => {
    const fks = getTableConfig(agentConfigVersions).foreignKeys;
    expect(fks, "exactly one foreign key").toHaveLength(1);
    const ref = fks[0]!.reference();
    expect(ref.columns.map((c) => c.name)).toEqual(["agent_config_id"]);
    expect(ref.foreignColumns.map((c) => c.name)).toEqual(["id"]);
    expect(getTableConfig(ref.foreignTable).name).toBe("agent_configs");
  });
});

// ----------------------------------------------------------------- env_configs

describe("env_configs", () => {
  it("has the expected table name", () => {
    expect(getTableConfig(envConfigs).name).toBe("env_configs");
  });

  it("columns match the migration", () => {
    assertColumns(envConfigs, {
      id: { type: "uuid", notNull: true, primary: true },
      namespace: { type: "text", notNull: true },
      name: { type: "text", notNull: true },
      description: { type: "text", notNull: false },
      metadata: { type: "jsonb", notNull: true, hasDefault: true, default: {} },
      base_image: { type: "text", notNull: true },
      persistent_fs: { type: "jsonb", notNull: true, hasDefault: true, default: { size_gb: 2 } },
      egress: { type: "jsonb", notNull: true, hasDefault: true, default: { allow: [] } },
      created_at: { type: "timestamp with time zone", notNull: true, hasDefault: true },
      updated_at: { type: "timestamp with time zone", notNull: true, hasDefault: true },
      archived_at: { type: "timestamp with time zone", notNull: false },
    });
  });

  it("uses an inline primary key on id (no composite PK, no FKs)", () => {
    const cfg = getTableConfig(envConfigs);
    expect(cfg.primaryKeys, "envs use an inline PK, not a composite one").toHaveLength(0);
    expect(cfg.foreignKeys, "env table references nothing (yet — sessions later)").toHaveLength(0);
  });

  it("has the two namespace lookup indexes, both non-unique", () => {
    // name is a display label, not a reference — the (namespace, name) index must
    // stay non-unique so duplicate names within a namespace are allowed.
    expect(indexSummaries(envConfigs)).toEqual([
      { name: "env_configs_ns", columns: ["namespace"], unique: false },
      { name: "env_configs_ns_name", columns: ["namespace", "name"], unique: false },
    ]);
  });
});

// ------------------------------------------------------------------ ModelConfig

describe("ModelConfig", () => {
  it("constrains provider to the supported union", () => {
    const model: ModelConfig = {
      provider: "anthropic",
      model: "claude-sonnet-5",
      maxTokens: 1024,
      temperature: 0.7,
    };
    expect(model.provider).toBe("anthropic");

    // Compile-time guard: an unsupported provider must not type-check. Types are
    // stripped at runtime, so this line is inert then; `tsc --noEmit` enforces it.
    // @ts-expect-error "cohere" is not a member of the provider union
    const unsupported: ModelConfig = { provider: "cohere", model: "x" };
    void unsupported;
  });
});
