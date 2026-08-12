// stores/engine.ts — the app-facing engine facade.
//
// The shell NEVER blocks on pyodide boot (spec §11): it renders immediately,
// the engine boots lazily off the main thread, and any compute requested
// before `ready` is queued and drained once boot completes. This store owns:
//   - `status`   : 'idle' | 'loading' | 'ready' | 'error' (bindable UI state)
//   - a FIFO queue of thunks enqueued while not ready
//   - `whenReady()` / `enqueue()` for callers, and `boot()` to kick it off.
//   - `stop()` + the `engineProgress` store: round-11 P7's long-calc progress
//     and its only possible cancel (terminate + reboot). See the P7 block
//     below for why nothing gentler works.
//
// The underlying EngineClient is injectable so tests can drive the store with
// a fake worker; the default lazily spawns the real client.
import { get, writable } from 'svelte/store';
import { createEngineClient, type EngineClient } from '../worker/client';

export type EngineStatus = 'idle' | 'loading' | 'ready' | 'error';

// --- long-calc progress + stop (round-11 P7) --------------------------------

/**
 * How long a calc must run before the UI stops pretending it is instant and
 * shows a determinate bar with a Stop button (Tore, mid-round: "progress bar
 * when it's taking longer than ~3 s, with a stop"). Below it nothing changes —
 * the BusyChip's own 300 ms pulse remains the only signal.
 */
export const LONG_CALC_MS = 3000;

/** The engine call currently reporting progress (at most one — see below). */
export interface EngineProgressState {
  /** Request id — identity across frames; a new call replaces the entry. */
  callId: number;
  /** Glue op ('calc_sono', …) — what a card filters on, never the label. */
  op: string;
  /** Human label for the op ('sonogram', 'damping fit'). */
  label: string;
  done: number;
  total: number;
  /** `Date.now()` of the FIRST frame, i.e. when reporting began. */
  startedAt: number;
}

/**
 * Ops that report mid-compute progress, and the label the UI shows. Adding a
 * calc is one line here PLUS a `progress_callback` on its pydvma function
 * (glue passes the hook to anything that accepts one) — an op with no entry is
 * simply not tracked, so an unlabelled long op never puts up a nameless bar.
 */
export const PROGRESS_LABELS: Record<string, string> = {
  calc_sono: 'sonogram',
  calc_damping: 'damping fit',
};

/**
 * The live progress entry, or null. Deliberately a MODULE-LEVEL singleton
 * rather than per-store state: the app builds exactly one engine store, only
 * one long calc runs at a time (the worker is single-threaded and the protocol
 * is serial), and components too deep to be handed the store — BusyChip, the
 * Sono card, the damping panel — read it directly with no App wiring.
 */
export const engineProgress = writable<EngineProgressState | null>(null);

/**
 * Rejection handed to every call killed by `stop()`. Distinguishable by class
 * OR by `name` (`isEngineStopped`), so a caller can tell "the user stopped
 * this" from a genuine compute failure and stay quiet about it.
 */
/**
 * The stop rejection's message. Exported because it also travels as a bare
 * STRING: `actions.guarded` stores `e.message` in `computeErrors`, so a card
 * showing that slot has only the text to recognise a stop by — and a stop is
 * not an error to shout about in red.
 */
export const ENGINE_STOPPED_MESSAGE = 'calculation stopped';

export class EngineStoppedError extends Error {
  constructor(message = ENGINE_STOPPED_MESSAGE) {
    super(message);
    this.name = 'EngineStopped';
  }
}

/** True for the rejection `stop()` produces (class or duck-typed by name). */
export function isEngineStopped(e: unknown): boolean {
  return e instanceof EngineStoppedError
    || (typeof e === 'object' && e !== null && (e as { name?: string }).name === 'EngineStopped');
}

/**
 * One-shot flag so a stop that kills N queued calls yields ONE notification,
 * not N. `stop()` raises it; the first caller of `consumeEngineStopNotice()`
 * after each stop gets `true` and clears it, every later caller gets `false`.
 */
let stopNoticePending = false;

/** Claim the "tell the user we stopped" notice — true at most once per stop. */
export function consumeEngineStopNotice(): boolean {
  const due = stopNoticePending;
  stopNoticePending = false;
  return due;
}

/** What the long-calc UI needs, or null when nothing should be shown yet. */
export interface LongCalcView {
  label: string;
  done: number;
  total: number;
  /** 0..1, clamped; 0 when `total` is not yet known. */
  fraction: number;
  /** Seconds since the first frame. */
  elapsedS: number;
}

/**
 * Pure 3-second gate: the view model for a progress entry, or null while the
 * calc is still young enough that the UI should stay quiet. `now` is passed in
 * (the component ticks it) so this is directly unit-testable.
 */
export function longCalcView(
  p: EngineProgressState | null,
  now: number,
  thresholdMs: number = LONG_CALC_MS,
): LongCalcView | null {
  if (!p) return null;
  const elapsed = now - p.startedAt;
  if (elapsed < thresholdMs) return null;
  const fraction = p.total > 0 ? Math.min(1, Math.max(0, p.done / p.total)) : 0;
  return { label: p.label, done: p.done, total: p.total, fraction, elapsedS: elapsed / 1000 };
}

/**
 * The engine store that most recently ran a call — the target of the
 * module-level `stopEngine()`. Registered on `enqueue` (not on creation) so
 * that when a second store exists (EngineProbe's, behind `?engine=1`) Stop
 * always hits the one actually computing.
 */
let activeEngine: { stop: () => Promise<void> } | null = null;

/**
 * Terminate + reboot whichever engine last ran a call. The Stop button's
 * entry point for components that are not handed the engine store. Resolves
 * once the replacement engine is ready (or has failed to boot); a no-op when
 * nothing has computed yet.
 */
export function stopEngine(): Promise<void> {
  return activeEngine ? activeEngine.stop() : Promise.resolve();
}

/** Wheel filenames the worker micropip-installs (served from /pypi/). */
export const ENGINE_WHEELS = ['pydvma-2.3.0-py3-none-any.whl', 'PeakUtils-1.3.5-py3-none-any.whl'];

/**
 * Vendored pyodide version. Must match the `pyodide` devDependency (and thus
 * the assets staged by scripts/fetch-pyodide.sh). Drives the CDN
 * `packageBaseUrl` the worker uses for prebuilt numpy/scipy/micropip wheels.
 */
export const PYODIDE_VERSION = '0.28.3';

/** Absolute page-relative base so the worker can build absolute asset URLs. */
function defaultBaseUrl(): string {
  const base = (import.meta as any).env?.BASE_URL ?? '/';
  // Resolve against the PAGE URL, never the bare origin: with `base: './'`
  // BASE_URL is RELATIVE, and the app may be served from a sub-path — the
  // deployed GitHub Pages site lives at /pydvma/app/. Resolving './' against
  // the origin dropped that sub-path, so the worker fetched /pyodide/… from
  // the domain root and the engine failed to boot ("Importing a module
  // script failed") on the live site only — every dev/preview/e2e server
  // sits at the root, which is why tests never caught it (they now do:
  // e2e/subpath.spec.ts). document.baseURI resolves ./ to the page's
  // directory in both dev ('/') and built ('./') modes.
  const ref = (typeof document !== 'undefined' && document.baseURI)
    ? document.baseURI
    : (typeof location !== 'undefined' ? location.href : 'http://localhost/');
  return new URL(base, ref).href;
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
  /** In-flight `stop()`, so concurrent Stop clicks share one terminate+reboot. */
  let stopping: Promise<void> | null = null;

  // Mid-compute frames -> the shared `engineProgress` store. Only ops in
  // PROGRESS_LABELS are tracked; an unlabelled op's frames are ignored (it has
  // opted out, or is a future calc whose label has not been added yet).
  // (`observe` is optional on EngineClient — a stub client just gets no bar.)
  client.observe?.({
    onProgress: ({ callId, op, done, total }) => {
      const label = PROGRESS_LABELS[op];
      if (!label) return;
      engineProgress.update((cur) =>
        cur && cur.callId === callId
          // Same call: keep startedAt so the elapsed clock (and the 3 s gate)
          // measures from the FIRST frame, not the latest.
          ? { ...cur, done, total }
          : { callId, op, label, done, total, startedAt: Date.now() });
    },
    onSettled: ({ callId }) => {
      engineProgress.update((cur) => (cur && cur.callId === callId ? null : cur));
    },
  });

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
      // A boot killed BY a stop is not a boot failure: `stop()` rejects the
      // in-flight init when it terminates the worker, and is already booting a
      // replacement. Claiming 'error' here would fight that reboot (and reject
      // everything queued behind it with a bogus "failed to boot").
      if (isEngineStopped(err)) return;
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
    activeEngine = store;          // this store owns the Stop button from now on
    const s = get(status);
    if (s === 'ready') return client.call<T>(op, payload);
    if (s === 'error') return Promise.reject(bootError ?? new Error('engine failed to boot'));
    return new Promise<T>((resolve, reject) => {
      queue.push({ run: () => client.call<T>(op, payload).then(resolve, reject), reject });
    });
  }

  /**
   * Stop whatever is computing, then come back up.
   *
   * There is no gentler option. Pyodide computes SYNCHRONOUSLY inside the
   * worker, so a busy worker never reads a cancel message, and the usual
   * escape hatch — an interrupt buffer — needs `SharedArrayBuffer`, which
   * needs COOP/COEP headers GitHub Pages does not send. So Stop TERMINATES the
   * worker and boots a fresh one (a few seconds, mostly HTTP-cached), which
   * works identically on Pages, the local bridge and JupyterLite.
   *
   * Everything outstanding — the in-flight call and every queued one — rejects
   * with `EngineStoppedError` so each card unwinds instead of hanging, and
   * `consumeEngineStopNotice()` lets the first of them say so exactly once.
   * Resolves when the replacement engine is ready (or has failed to boot).
   */
  // NB not `async`: the guard hands back the SAME promise both times, which an
  // async wrapper would re-wrap into a new one each call.
  function stop(): Promise<void> {
    // Re-entrancy guard: a second Stop while the replacement engine is still
    // booting would terminate THAT worker mid-init and leave two boot paths
    // racing over `status`. Both clicks share one stop instead.
    if (stopping) return stopping;
    stopping = runStop().finally(() => { stopping = null; });
    return stopping;
  }

  async function runStop(): Promise<void> {
    stopNoticePending = true;
    const err = new EngineStoppedError();
    engineProgress.set(null);
    // Queued-but-never-sent calls first, then the worker (whose restart
    // rejects the in-flight one).
    while (queue.length) queue.shift()!.reject(err);
    while (readyWaiters.length) readyWaiters.shift()!.reject(err);
    client.restart(err);
    // Back through the normal lifecycle: 'idle' -> boot() -> 'loading' ->
    // 'ready', so the BusyChip's "starting engine…" state covers the reboot
    // and anything enqueued meanwhile queues and drains as usual.
    booted = false;
    bootError = null;
    status.set('idle');
    await boot();
  }

  const store = { status, boot, whenReady, enqueue, stop, client };
  return store;
}

export type EngineStore = ReturnType<typeof createEngineStore>;
