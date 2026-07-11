// packages/db/schema/envs.ts
// Environment config = the recipe for a session's sandbox (base image, persistent
// filesystem, egress policy). Single table + archive, NOT versioned: the config is
// consumed once at sandbox provision, so updates only affect future sessions.
// When sessions land they snapshot resolved_env at provision; see configs.ts.

import {
  index, jsonb, pgTable, text, timestamp, uuid,
} from "drizzle-orm/pg-core";

export type PersistentFs = { size_gb: number };
export type EgressPolicy = { allow: string[] }; // domain allowlist; [] = deny all egress

export const envConfigs = pgTable(
  "env_configs",
  {
    id: uuid("id").primaryKey(),              // client-supplied → idempotent create
    namespace: text("namespace").notNull(),
    name: text("name").notNull(),             // display label, non-unique
    description: text("description"),
    metadata: jsonb("metadata").$type<Record<string, string>>().notNull().default({}),

    // ---- the recipe ----
    baseImage: text("base_image").notNull(),  // e.g. "funky/base-python:3.12"
    persistentFs: jsonb("persistent_fs").$type<PersistentFs>().notNull().default({ size_gb: 2 }),
    egress: jsonb("egress").$type<EgressPolicy>().notNull().default({ allow: [] }),

    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
    archivedAt: timestamp("archived_at", { withTimezone: true }),
  },
  (t) => [
    index("env_configs_ns_name").on(t.namespace, t.name),
    index("env_configs_ns").on(t.namespace),
  ],
);
