import { drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";

export function createDb(pool: Pool) {
  return drizzle({ client: pool });
}

export type Db = ReturnType<typeof createDb>;

/** A transaction handle — the value drizzle passes to `db.transaction((tx) => …)`.
 *  Callers whose write must be atomic with another (e.g. enqueue a job in the same
 *  transaction that appends the user_message event) take this so both share one tx. */
export type Tx = Parameters<Parameters<Db["transaction"]>[0]>[0];

export * as tables from "./schema";
