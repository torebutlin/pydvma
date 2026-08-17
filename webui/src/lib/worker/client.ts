// client.ts — main-thread client for the pydvma engine worker.
//
// Owns the worker lifecycle and the request/response correlation: each `call`
// gets a monotonic id, its resolve/reject is parked in a Map, and the worker's
// reply (`{ id, ok, result | error }`) is routed back by id. Two concurrent
// calls therefore resolve to their own results regardless of completion order.
//
// The worker is injectable (`WorkerLike` + a factory) so protocol.test.ts can
// drive the client against a fake postMessage pair in node — no real Worker,
// no pyodide. In the app, the default factory spawns the real ES-module worker.

/** The slice of the DOM Worker API the client depends on (postMessage + events). */
export interface WorkerLike {
  postMessage(message: unknown): void;
  onmessage: ((e: { data: any }) => void) | null;
  onerror: ((e: any) => void) | null;
  /** Fired when an inbound message fails to deserialize (structured clone). */
  onmessageerror: ((e: any) => void) | null;
  terminate(): void;
}

/** Wire message the worker sends back for a given request id. */
interface Reply {
  id: number;
  ok: boolean;
  result?: unknown;
  error?: string;
}

/** A mid-call progress frame, with the op name resolved from the pending map. */
export interface ProgressFrame {
  callId: number;
  /** Glue op the frame belongs to (e.g. 'calc_sono') — the label's source. */
  op: string;
  done: number;
  total: number;
}

/**
 * Optional observers for call lifecycle events (P7). `onProgress` fires for
 * every frame the worker posts mid-compute (already throttled worker-side);
 * `onSettled` fires exactly once per call when it resolves, rejects, or is
 * torn down — the signal to clear any progress it was reporting.
 */
export interface EngineCallEvents {
  onProgress?: (frame: ProgressFrame) => void;
  onSettled?: (info: { callId: number; op: string }) => void;
  /**
   * The transport went away WITHOUT anyone asking — the peer died, not
   * `restart`/`dispose`. Fired after the in-flight calls have been rejected,
   * so an observer sees a settled world.
   *
   * Only a socket transport can do this (a stopped or restarted
   * `pydvma-serve`); THIS worker client never fires it, because a Worker
   * that dies takes the page's own process context with it and surfaces as
   * `onerror` instead. The store maps it to a clear 'engine connection lost'
   * error — without it the store stays 'ready', the app looks healthy, and
   * every calc rejects with a bare "engine not connected" until a reload.
   */
  onTransportLost?: () => void;
}

export interface EngineClient {
  /** Boot the engine: vendored pyodide at `<baseUrl>pyodide/`, wheels under `<baseUrl>pypi/`. */
  init(baseUrl: string, wheels: string[], pyodideVersion: string): Promise<void>;
  /** Invoke a glue op with keyword-style payload; resolves with the marshalled result. */
  call<T = unknown>(op: string, payload?: Record<string, unknown>): Promise<T>;
  /**
   * Register lifecycle observers (replaces any previous registration).
   * OPTIONAL on purpose: progress reporting is an extra, so a minimal
   * hand-rolled client (a test stub, a future non-worker transport) stays a
   * valid `EngineClient` without it — the store calls it defensively and
   * simply gets no progress frames.
   */
  observe?(events: EngineCallEvents): void;
  /**
   * Hard stop: reject every in-flight call with `reason` and tear down the
   * underlying transport (worker termination, socket close — whatever the
   * implementation uses). The client stays usable but not connected — the
   * caller must `init` again. For the pyodide worker client this is the
   * only way to interrupt a synchronous compute: a busy worker never reads
   * a cancel message, so `restart` terminates it and spawns a fresh one in
   * its place; a socket-transport client instead just closes the socket
   * (the server treats that as cancel-and-kill of the in-flight op).
   */
  restart(reason: Error): void;
  /** Tear down the worker and reject all in-flight calls. */
  dispose(reason?: Error): void;
}

/** Default factory: the real ES-module worker. Overridable for tests. */
function defaultWorkerFactory(): WorkerLike {
  return new Worker(new URL('./engine.worker.ts', import.meta.url), {
    type: 'module',
  }) as unknown as WorkerLike;
}

/**
 * Create an engine client. Pass a `workerFactory` to inject a fake worker
 * (tests); omit it to spawn the real one. Pending calls are keyed by a
 * monotonic id and settled from `onmessage`; a worker `onerror` (or
 * `dispose`) rejects every outstanding promise so callers never hang.
 */
export function createEngineClient(
  workerFactory: () => WorkerLike = defaultWorkerFactory,
): EngineClient {
  interface Pending { op: string; resolve: (v: any) => void; reject: (e: any) => void }
  const pending = new Map<number, Pending>();
  let nextId = 1;
  let disposed = false;
  let events: EngineCallEvents = {};
  // Mutable so `restart` can swap in a fresh worker without the store (or
  // anything else holding this client) needing a new object.
  let worker = workerFactory();
  attach(worker);

  /** Settle one pending call and announce it, so progress state can clear. */
  function finish(id: number): Pending | undefined {
    const entry = pending.get(id);
    if (!entry) return undefined;
    pending.delete(id);
    events.onSettled?.({ callId: id, op: entry.op });
    return entry;
  }

  /** Reject every in-flight call with `err`, announcing each as settled. */
  function rejectAll(err: Error) {
    for (const id of [...pending.keys()]) finish(id)?.reject(err);
    pending.clear();
  }

  /** Wire the message/error handlers onto a (new) worker. */
  function attach(w: WorkerLike) {
    w.onmessage = (e: { data: Reply | { type?: string; callId?: number; done?: number; total?: number } }) => {
      const data: any = e.data;
      // Unsolicited mid-compute frame (P7) — not a reply, so it must never
      // touch the pending map beyond reading the op it belongs to. A frame for
      // an already-settled id is dropped.
      if (data?.type === 'progress') {
        const entry = pending.get(data.callId);
        if (entry) {
          events.onProgress?.({
            callId: data.callId, op: entry.op, done: data.done, total: data.total,
          });
        }
        return;
      }
      const { id, ok, result, error } = data as Reply;
      const entry = finish(id);
      if (!entry) return; // unknown / already-settled id — ignore
      if (ok) entry.resolve(result);
      else entry.reject(new Error(error ?? 'engine error'));
    };
    w.onerror = (e: any) => rejectAll(new Error(e?.message ?? 'engine worker crashed'));
    // A reply that fails structured-clone deserialization fires onmessageerror
    // instead of onmessage — without this the matching pending call would leak.
    w.onmessageerror = () => rejectAll(new Error('engine message deserialization failed'));
  }

  function send<T>(op: string, payload: Record<string, unknown>): Promise<T> {
    if (disposed) return Promise.reject(new Error('engine client disposed'));
    const id = nextId++;
    return new Promise<T>((resolve, reject) => {
      pending.set(id, { op, resolve, reject });
      worker.postMessage({ id, op, payload });
    });
  }

  return {
    init(baseUrl: string, wheels: string[], pyodideVersion: string): Promise<void> {
      return send<void>('init', { baseUrl, wheels, pyodideVersion });
    },
    call<T = unknown>(op: string, payload: Record<string, unknown> = {}): Promise<T> {
      return send<T>(op, payload);
    },
    observe(next: EngineCallEvents): void {
      events = next ?? {};
    },
    restart(reason: Error): void {
      if (disposed) return;
      const old = worker;
      rejectAll(reason);
      old.terminate();
      // Ids keep counting up across the restart, so a late frame from the dead
      // worker can never collide with a call made on the new one.
      worker = workerFactory();
      attach(worker);
    },
    dispose(reason?: Error): void {
      disposed = true;
      rejectAll(reason ?? new Error('engine client disposed'));
      worker.terminate();
    },
  };
}
