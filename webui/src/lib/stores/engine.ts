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
  const queue: Array<() => void> = [];
  const readyWaiters: Array<() => void> = [];
  let booted = false;

  function drain() {
    while (queue.length) queue.shift()!();
    while (readyWaiters.length) readyWaiters.shift()!();
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
      console.error('[engine] boot failed:', err);
      status.set('error');
    }
  }

  /**
   * Resolve once the engine is ready. If already ready, resolves on the next
   * microtask; otherwise parks until `boot()` reaches 'ready'. Never rejects —
   * an errored boot leaves the promise pending (callers gate on `status`).
   */
  function whenReady(): Promise<void> {
    if (get(status) === 'ready') return Promise.resolve();
    return new Promise<void>((resolve) => readyWaiters.push(resolve));
  }

  /**
   * Run a compute op, queueing until ready if boot is still in flight. The
   * shell can call this at any time without awaiting boot; the returned
   * promise settles when the op (eventually) runs.
   */
  function enqueue<T = unknown>(op: string, payload?: Record<string, unknown>): Promise<T> {
    if (get(status) === 'ready') return client.call<T>(op, payload);
    return new Promise<T>((resolve, reject) => {
      queue.push(() => client.call<T>(op, payload).then(resolve, reject));
    });
  }

  return { status, boot, whenReady, enqueue, client };
}

export type EngineStore = ReturnType<typeof createEngineStore>;
