// packages/configs/src/util.ts
// Pure helpers shared by the resource services. Internal — not exported from index.ts.

/** Key-order-insensitive deep equality for jsonb columns. */
export function jsonEq(a: unknown, b: unknown): boolean {
  return JSON.stringify(sortKeys(a)) === JSON.stringify(sortKeys(b));
}

function sortKeys(x: unknown): unknown {
  if (Array.isArray(x)) return x.map(sortKeys);
  if (x && typeof x === "object") {
    return Object.fromEntries(
      Object.entries(x as Record<string, unknown>)
        .sort(([k1], [k2]) => k1.localeCompare(k2))
        .map(([k, v]) => [k, sortKeys(v)]),
    );
  }
  return x;
}

/** Postgres unique_violation (two same-id creates raced; loser hits the PK). */
export function isUniqueViolation(err: unknown): boolean {
  if (typeof err !== "object" || err === null) return false;
  if ((err as { code?: unknown }).code === "23505") return true;
  // drizzle v1 wraps driver errors (DrizzleQueryError) with the pg error as `cause`
  return isUniqueViolation((err as { cause?: unknown }).cause);
}
