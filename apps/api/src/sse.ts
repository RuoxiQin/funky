// apps/api/src/sse.ts — Phase F: one LISTEN client, many streams.
//
// Rule 2: the log IS the stream. The worker appends events and fires a NOTIFY on
// 'funky_events' carrying only the pointer `${sessionId}:${seq}`. This process holds ONE
// dedicated pg.Client LISTENing on that channel and fans the wake-ups out to open SSE
// streams in memory. A wake-up carries NO data — every stream re-reads session_events
// from its own cursor. So reconnect-and-resume is free, a dropped NOTIFY delays a stream
// (never loses an event), and the 8KB NOTIFY limit never matters.

import type { Client } from "pg";
import { type EventStore, toApiEvent } from "@funky/sessions";
import type { SSEStreamingApi } from "hono/streaming";

/** Every SSE stream waits on the fan-out for a session; the callback is a bare wake-up. */
type Waker = () => void;

export class EventBus {
  private readonly subs = new Map<string, Set<Waker>>();

  /** `client` MUST be a dedicated pg.Client — never a pooled connection (the pool recycles
   *  it and the listener silently goes deaf). The app owns the client's lifecycle. */
  constructor(private readonly client: Client) {}

  /** Called once at boot: LISTEN funky_events; on notify, parse `${sessionId}:${seq}` and
   *  wake every subscriber registered for that sessionId. */
  async start(): Promise<void> {
    this.client.on("notification", (msg) => {
      if (msg.channel !== "funky_events" || !msg.payload) return;
      const sep = msg.payload.indexOf(":");
      const sessionId = sep === -1 ? msg.payload : msg.payload.slice(0, sep);
      const wakers = this.subs.get(sessionId);
      if (!wakers) return;
      // A waker only flips a flag; it must not throw, but guard anyway so one bad stream
      // can't starve the others.
      for (const wake of wakers) {
        try {
          wake();
        } catch {
          /* a stream's waker never throws; ignore if it somehow does */
        }
      }
    });
    await this.client.query("listen funky_events");
  }

  /** Register a wake-up for a session; returns the unsubscribe. Every subscribe() MUST be
   *  paired with its unsubscribe() on disconnect (see runSseStream's cleanup). */
  subscribe(sessionId: string, wake: Waker): () => void {
    let wakers = this.subs.get(sessionId);
    if (!wakers) {
      wakers = new Set();
      this.subs.set(sessionId, wakers);
    }
    wakers.add(wake);
    return () => {
      const current = this.subs.get(sessionId);
      if (!current) return;
      current.delete(wake);
      if (current.size === 0) this.subs.delete(sessionId);
    };
  }

  /** Total live subscribers across all sessions — introspection + leak detection in tests. */
  subscriberCount(): number {
    let n = 0;
    for (const wakers of this.subs.values()) n += wakers.size;
    return n;
  }
}

const HEARTBEAT_MS = 15_000;

export type SseStreamOpts = {
  store: EventStore;
  bus: EventBus;
  namespace: string;
  sessionId: string;
  /** Start emitting events strictly after this seq (0 = from the beginning). */
  cursor: number;
  /** Test seam: override the heartbeat / safety-net interval. Defaults to 15s. */
  heartbeatMs?: number;
};

/** Drive one SSE stream: replay from the cursor, then go live off the fan-out. Returns
 *  when the client disconnects (streamSSE closes the stream afterwards). */
export async function runSseStream(stream: SSEStreamingApi, opts: SseStreamOpts): Promise<void> {
  const { store, bus, namespace, sessionId } = opts;
  const heartbeatMs = opts.heartbeatMs ?? HEARTBEAT_MS;
  let cursor = opts.cursor;

  // --- wake coordination: idle until a NOTIFY fan-out or the heartbeat tick ---
  let notified = false;
  let wakeResolve: (() => void) | null = null;
  const signal = () => {
    notified = true;
    const r = wakeResolve;
    wakeResolve = null;
    r?.();
  };

  // Subscribe FIRST, then replay. This closes the replay-then-live race: an event that
  // lands during the replay read still flips `notified`, so the live loop drains it. The
  // dedupe (`seq <= cursor`) makes an overlap harmless.
  const unsub = bus.subscribe(sessionId, signal);

  let stopped = false;
  const cleanup = () => {
    if (stopped) return;
    stopped = true;
    unsub();
    signal(); // break any in-progress idle wait so the loop exits promptly
  };
  stream.onAbort(cleanup); // client disconnect → drop the subscription, no leak

  const flush = async () => {
    for (;;) {
      const { events, hasMore } = await store.readPage(namespace, sessionId, cursor, 500);
      for (const e of events) {
        if (e.seq <= cursor) continue; // dedupe
        await stream.writeSSE({
          id: String(e.seq), // `id:` = seq → Last-Event-ID resume works for free
          event: e.type,
          data: JSON.stringify(toApiEvent(e)),
        });
        cursor = e.seq;
      }
      if (!hasMore) break;
    }
  };

  const waitForWakeOrTimeout = (ms: number): Promise<"wake" | "timeout"> => {
    if (notified) {
      notified = false;
      return Promise.resolve("wake");
    }
    return new Promise<"wake" | "timeout">((resolve) => {
      const timer = setTimeout(() => {
        wakeResolve = null;
        resolve("timeout");
      }, ms);
      timer.unref?.();
      wakeResolve = () => {
        clearTimeout(timer);
        notified = false;
        resolve("wake");
      };
    });
  };

  try {
    await flush(); // REPLAY
    // LIVE: wake on NOTIFY; on each heartbeat tick emit a comment (keeps proxies from
    // killing an idle stream) and re-read as a cheap safety net for a dropped NOTIFY.
    while (!stream.aborted && !stopped) {
      const reason = await waitForWakeOrTimeout(heartbeatMs);
      if (stream.aborted || stopped) break;
      if (reason === "wake") {
        await flush();
        continue;
      }
      await stream.write(":hb\n\n");
      await flush();
    }
  } finally {
    cleanup();
  }
}
