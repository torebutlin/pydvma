// stores/engine.ts — the app-facing engine facade.
//
// The shell NEVER blocks on pyodide boot (spec §11): it renders immediately,
// the engine boots lazily off the main thread, and any compute requested
// before `ready` is queued and drained once boot completes. This store owns:
//   - `status`   : 'idle' | 'loading' | 'ready' | 'error' (bindable UI state)
//   - a FIFO queue of thunks enqueued while not ready
//   - `whenReady()` / `enqueue()` for callers, and `boot()` to kick it off.
//
// The underlying EngineClient is injectable so tests can drive the store with
// a fake worker; the default lazily spawns the real client.
import { get, writable } from 'svelte/store';
import { createEngineClient, type EngineClient } from '../worker/client';

export type EngineStatus = 'idle' | 'loading' | 'ready' | 'error';

/** Wheel filenames the worker micropip-installs (served from /pypi/). */
export const ENGINE_WHEELS = ['pydvma-1.5.0-py3-none-any.whl', 'PeakUtils-1.3.5-py3-none-any.whl'];

/**
 * Vendored pyodide version. Must match the `pyodide` devDependency (and thus
 * the assets staged by scripts/fetch-pyodide.sh). Drives the CDN
 * `packageBaseUrl` the worker uses for prebuilt numpy/scipy/micropip wheels.
 */
export const PYODIDE_VERSION = '0.28.3';

/** Absolute origin+base so the worker can build absolute asset URLs. */
function defaultBaseUrl(): string {
  const base = (import.meta as any).env?.BASE_URL ?? '/';
  const origin = typeof location !== 'undefined' ? location.origin : '';
  // BASE_URL may be relative ('./') under `base: './'`; resolve against origin.
  return new URL(base, origin || 'http://localhost').href;
}

/**
 * Create the engine store. `client` is injectable for tests; omit it to spawn
 * the real worker client. `boot()` transitions idle -> loading -> ready|error
 * and, on ready, drains every queued thunk in FIFO order. Calling `boot()`
 * more than once is a no-op after the first.
 */
export function createEngineStore(
  client: EngineClient = createEngineClient(),
  baseUrl: string = defaultBaseUrl(),
) {
  const status = writable<EngineStatus>('idle');
  // Each queued item carries its own `reject` so a boot FAILURE can settle it
  // (not just a boot success draining it). Without this, a compute call
  // enqueued during boot would hang forever if boot then errors.
  interface QueueItem { run: () => void; reject: (e: unknown) => void; }
  const queue: QueueItem[] = [];
  const readyWaiters: Array<{ resolve: () => void; reject: (e: unknown) => void }> = [];
  let booted = false;
  /** Error captured on boot failure, so callers arriving AFTER the failure
   *  (when `booted` is already true and drain never re-runs) still get it. */
  let bootError: Error | null = null;

  function drain() {
    while (queue.length) queue.shift()!.run();
    while (readyWaiters.length) readyWaiters.shift()!.resolve();
  }

  /** Reject every queued item and ready-waiter with the boot error. */
  function failAll(err: Error) {
    while (queue.length) queue.shift()!.reject(err);
    while (readyWaiters.length) readyWaiters.shift()!.reject(err);
  }

  async function boot(): Promise<void> {
    if (booted) return;
    booted = true;
    status.set('loading');
    try {
      await client.init(baseUrl, ENGINE_WHEELS, PYODIDE_VERSION);
      status.set('ready');
      drain();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      bootError = new Error('engine failed to boot: ' + msg);
      console.error('[engine] boot failed:', err);
      status.set('error');
      failAll(bootError);          // settle anything queued during boot
    }
  }

  /**
   * Resolve once the engine is ready. If already ready, resolves immediately;
   * if boot has already FAILED, rejects with the boot error; otherwise parks
   * until `boot()` reaches 'ready' (resolve) or errors (reject). Never hangs.
   */
  function whenReady(): Promise<void> {
    const s = get(status);
    if (s === 'ready') return Promise.resolve();
    if (s === 'error') return Promise.reject(bootError ?? new Error('engine failed to boot'));
    return new Promise<void>((resolve, reject) => readyWaiters.push({ resolve, reject }));
  }

  /**
   * Run a compute op, queueing until ready if boot is still in flight. The
   * shell can call this at any time without awaiting boot; the returned
   * promise settles when the op runs (on ready) OR rejects if boot fails —
   * it NEVER hangs. If boot has already errored, it rejects immediately.
   */
  function enqueue<T = unknown>(op: string, payload?: Record<string, unknown>): Promise<T> {
    const s = get(status);
    if (s === 'ready') return client.call<T>(op, payload);
    if (s === 'error') return Promise.reject(bootError ?? new Error('engine failed to boot'));
    return new Promise<T>((resolve, reject) => {
      queue.push({ run: () => client.call<T>(op, payload).then(resolve, reject), reject });
    });
  }

  return { status, boot, whenReady, enqueue, client };
}

export type EngineStore = ReturnType<typeof createEngineStore>;
