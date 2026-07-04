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

export interface EngineClient {
  /** Boot the engine: vendored pyodide at `<baseUrl>pyodide/`, wheels under `<baseUrl>pypi/`. */
  init(baseUrl: string, wheels: string[], pyodideVersion: string): Promise<void>;
  /** Invoke a glue op with keyword-style payload; resolves with the marshalled result. */
  call<T = unknown>(op: string, payload?: Record<string, unknown>): Promise<T>;
  /** Tear down the worker and reject all in-flight calls. */
  dispose(): void;
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
  const worker = workerFactory();
  const pending = new Map<number, { resolve: (v: any) => void; reject: (e: any) => void }>();
  let nextId = 1;
  let disposed = false;

  worker.onmessage = (e: { data: Reply }) => {
    const { id, ok, result, error } = e.data;
    const entry = pending.get(id);
    if (!entry) return; // unknown / already-settled id — ignore
    pending.delete(id);
    if (ok) entry.resolve(result);
    else entry.reject(new Error(error ?? 'engine error'));
  };

  /** Reject every in-flight call with `err` and clear the map. */
  function rejectAll(err: Error) {
    for (const { reject } of pending.values()) reject(err);
    pending.clear();
  }

  worker.onerror = (e: any) => rejectAll(new Error(e?.message ?? 'engine worker crashed'));
  // A reply that fails structured-clone deserialization fires onmessageerror
  // instead of onmessage — without this the matching pending call would leak.
  worker.onmessageerror = () => rejectAll(new Error('engine message deserialization failed'));

  function send<T>(op: string, payload: Record<string, unknown>): Promise<T> {
    if (disposed) return Promise.reject(new Error('engine client disposed'));
    const id = nextId++;
    return new Promise<T>((resolve, reject) => {
      pending.set(id, { resolve, reject });
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
    dispose(): void {
      disposed = true;
      const err = new Error('engine client disposed');
      for (const { reject } of pending.values()) reject(err);
      pending.clear();
      worker.terminate();
    },
  };
}
