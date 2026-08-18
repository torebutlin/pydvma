// stores/engine.ts — the app-facing engine facade.
//
// The shell NEVER blocks on pyodide boot (spec §11): it renders immediately,
// the engine boots lazily off the main thread, and any compute requested
// before `ready` is queued and drained once boot completes. This store owns:
//   - `status`   : 'idle' | 'loading' | 'ready' | 'error' (bindable UI state)
//   - `host`     : 'pyodide' | 'native' | null-until-resolved — WHICH engine
//     answered (the browser worker, or a CPython pydvma-serve over the
//     `/engine` socket). Read-only; decided once per session by the client
//     factory in `worker/selectEngine.ts` and surfaced in the UI as
//     provenance, never as a mode the user has to manage.
//   - a FIFO queue of thunks enqueued while not ready
//   - `whenReady()` / `enqueue()` for callers, and `boot()` to kick it off.
//   - `stop()` + the `engineProgress` store: round-11 P7's long-calc progress
//     and its only possible cancel (terminate + reboot). See the P7 block
//     below for why nothing gentler works.
//   - the TRANSPORT-LOST transition: a socket engine can die unasked (a
//     stopped or restarted pydvma-serve), which a Worker cannot. That lands
//     as 'error' with a message naming the cause AND leaves the store
//     re-bootable, so the next `boot()` reconnects instead of the app sitting
//     at a healthy-looking 'ready' over a dead transport.
//
// The underlying EngineClient is injectable so tests can drive the store with
// a fake worker; the default RESOLVES one at boot (`worker/selectEngine.ts`),
// which is where the pyodide-vs-native-host decision lives.
import { get, writable, type Readable } from 'svelte/store';
import { type EngineClient } from '../worker/client';
import {
  resolveEngineClient, type EngineHostKind, type ResolvedEngine,
} from '../worker/selectEngine';

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

// --- session journal (native-engine stage 3) --------------------------------

/**
 * The live engine client that advertised a SESSION JOURNAL, or null when the
 * active engine has none (every pyodide session; a `pydvma-serve` predating
 * stage 3; anything before `boot()` has resolved a client).
 *
 * Module-level for the same reason as `activeEngine` above: the journal
 * helpers are called from `App.svelte` and from `files/autosave.ts`'s sink,
 * neither of which is handed the store. Registered by `boot()` when — and
 * only when — a factory resolves a native client whose greeting carried
 * `journal: true`, and (like `activeEngine`) last writer wins if a second
 * store ever resolves one (`EngineProbe`'s, behind `?engine=1`).
 *
 * Deliberately NOT cleared by a transport loss: the store keeps the same
 * client across a `pydvma-serve` restart and re-boots it (see
 * `handleTransportLost`), so the journal comes back with the reconnect. In
 * the gap, journal calls reject with "engine not connected" — which every
 * caller here already treats as best-effort.
 */
let journalClient: EngineClient | null = null;

/** The serve journal's state, as {@link journalGet} returns it. */
export interface JournalState {
  /** The session document (`.dvma` bytes), or null when nothing is stored. */
  doc: Uint8Array | null;
  /** Captures born server-side since the last document post, oldest first. */
  captures: Uint8Array[];
  /** A PREVIOUS serve run's session, offered for crash recovery, or null. */
  recovered: Uint8Array | null;
}

/**
 * True when the active engine is the native socket AND its greeting
 * advertised a session journal — the one gate every journal path checks.
 * False on pyodide, false against a serve that never advertised the
 * capability, and false before `boot()` has resolved a client.
 */
export function journalAvailable(): boolean {
  return journalClient !== null;
}

/** The active journal client, or a rejection naming why there isn't one. */
function requireJournal(): EngineClient {
  if (!journalClient) throw new Error('no session journal on this engine');
  return journalClient;
}

/**
 * Normalise one wire value into `.dvma` bytes. `frames.ts` decodes a
 * `'bytes'` blob to a `Uint8Array` already, so this is a defensive
 * pass-through that additionally accepts a bare `ArrayBuffer` and maps the
 * journal's "nothing stored" `null` (and an absent key) to null.
 */
function asBytes(v: unknown): Uint8Array | null {
  if (v instanceof Uint8Array) return v;
  if (v instanceof ArrayBuffer) return new Uint8Array(v);
  return null;
}

/**
 * Post the session document to the serve journal (`journal_set`), replacing
 * whatever it held. Called by the autosave sink on every persisted autosave
 * (`files/autosave.ts`), so it is best-effort by construction: the sink
 * already swallows a rejection (a socket closed mid-write, a serve stopped).
 */
export async function journalSet(doc: Uint8Array): Promise<void> {
  await requireJournal().call('journal_set', { doc });
}

/**
 * Read the serve journal (`journal_get`): the stored document, any captures
 * born server-side since it was posted, and a previous run's recovered
 * session if one was adopted at serve start.
 */
export async function journalGet(): Promise<JournalState> {
  const res = await requireJournal().call<Record<string, unknown>>('journal_get');
  const captures = Array.isArray(res?.captures) ? res.captures : [];
  return {
    doc: asBytes(res?.doc),
    // filter(Boolean) can't narrow, hence the explicit reduce-style walk: a
    // malformed entry is dropped rather than surfacing as a null capture.
    captures: captures.map(asBytes).filter((b): b is Uint8Array => b !== null),
    recovered: asBytes(res?.recovered),
  };
}

/**
 * Dismiss the crash-recovery offer server-side
 * (`journal_discard_recovered`), which also deletes its spill file so it is
 * never offered again.
 */
export async function journalDiscardRecovered(): Promise<void> {
  await requireJournal().call('journal_discard_recovered');
}

/**
 * Subscribe to server-initiated journal updates — a notebook
 * `Session.push` changing the document under the app. Returns the
 * unsubscribe callable, or **null** when nothing was subscribed because the
 * active engine has no journal (or a transport that cannot report one).
 *
 * `null` rather than a no-op unsubscribe DELIBERATELY: a caller that latches
 * "already subscribed" on a truthy return would otherwise capture the no-op
 * forever and never subscribe again once a journal engine does come up.
 *
 * The module-level facade over `SocketEngineClient.onJournalUpdate`, which
 * is per-CLIENT (see its docstring in `worker/socketClient.ts`): App.svelte
 * imports this one stable name instead of reaching for the live client.
 */
export function onJournalUpdate(cb: () => void): (() => void) | null {
  return journalClient?.onJournalUpdate?.(cb) ?? null;
}

/** Wheel filenames the worker micropip-installs (served from /pypi/). */
export const ENGINE_WHEELS = ['pydvma-2.3.0-py3-none-any.whl', 'PeakUtils-1.3.5-py3-none-any.whl'];

/**
 * Parse the pydvma release a wheel filename embeds
 * (`'pydvma-2.3.0-py3-none-any.whl'` -> `'2.3.0'`), or `null` if it doesn't
 * match that shape. Exported so {@link warnOnPydvmaVersionMismatch} is
 * testable without constructing a real `ENGINE_WHEELS`-shaped array.
 */
export function pydvmaVersionFromWheelFilename(filename: string): string | null {
  const m = /^pydvma-([^-]+)-/.exec(filename);
  return m ? m[1] : null;
}

/**
 * `console.warn` when the native host's greeted pydvma release differs from
 * `ENGINE_WHEELS[0]`'s -- the release this webui BUNDLE was built against.
 * Called from `boot()` right after a factory resolves a native client (see
 * `SocketEngineClient.pydvmaVersion` / `ResolvedEngine.pydvmaVersion`).
 *
 * DELIBERATELY diagnostic only, never fatal -- unlike
 * `socketClient.ts`'s `SUPPORTED_ENGINE_PROTOCOL_VERSION`, which gates the
 * connection HARD on a wire-protocol mismatch. A pydvma PATCH-level skew is
 * a legitimate, working configuration (an editable `pydvma` install paired
 * with an unrebuilt webui bundle, or `pydvma serve` upgraded a patch ahead
 * of a cached bundle) as long as the wire protocol still matches -- the fat
 * wheel normally ships the UI and `pydvma serve` together (see CLAUDE.md's
 * release notes), so the common case is an exact match and this never
 * fires. No-ops when either version is unknown (a wheel filename that
 * doesn't parse, or no greeted version at all) or they already match.
 */
export function warnOnPydvmaVersionMismatch(actual: string | null | undefined): void {
  if (!actual) return;
  const expected = pydvmaVersionFromWheelFilename(ENGINE_WHEELS[0]);
  if (expected && actual !== expected) {
    console.warn(
      `[engine] native engine reports pydvma ${actual}, this webui build expects ${expected} `
      + '-- the wire protocol still matches (see SUPPORTED_ENGINE_PROTOCOL_VERSION in '
      + 'worker/socketClient.ts), but results may differ from what this bundle assumes.',
    );
  }
}

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
 * Create the engine store. `boot()` transitions idle -> loading -> ready|error
 * and, on ready, drains every queued thunk in FIFO order. Calling `boot()`
 * more than once is a no-op while a boot has succeeded or is in flight.
 *
 * `clientSource` is either:
 *
 *  - an `EngineClient` OBJECT — bound immediately, `host` reads 'pyodide'
 *    from the start. Every test and every pre-Task-8 caller takes this path
 *    and its semantics are unchanged; or
 *  - an async FACTORY (the default, `resolveEngineClient`) — nothing is
 *    constructed until `boot()`, which resolves it ONCE and reports the
 *    transport that answered through `host`. A session that never computes
 *    therefore never spawns a worker and never opens a socket.
 *
 * `host` is null until a factory resolves; `client` is likewise null until
 * then (a getter, not a captured value — see the returned object).
 */
export function createEngineStore(
  clientSource: EngineClient | (() => Promise<ResolvedEngine>) = resolveEngineClient,
  baseUrl: string = defaultBaseUrl(),
) {
  /** Late-bound when `clientSource` is a factory; resolved once in boot(). */
  let client: EngineClient | null =
    typeof clientSource === 'function' ? null : clientSource;
  /**
   * Which transport is answering: 'pyodide' | 'native', or null while a
   * factory has not resolved yet. A directly-injected client is always the
   * browser worker as far as this store is concerned.
   */
  const host = writable<EngineHostKind | null>(
    typeof clientSource === 'function' ? null : 'pyodide');
  /**
   * A one-time, user-facing notice from the factory resolution (currently
   * only "auto-detected native, then failed to connect" — see
   * `ResolvedEngine.note`'s docstring in `worker/selectEngine.ts`), or
   * `null` when there is nothing to say. Set at most once per store
   * lifetime (the factory branch in `boot()` below runs only the FIRST time
   * `client` resolves), so `App.svelte` can raise it as a single toast with
   * no de-duplication of its own. A directly-injected client (every test,
   * every pre-Task-10 caller) never sets this.
   */
  const hostNote = writable<string | null>(null);
  /**
   * The native host's greeted pydvma release (`ResolvedEngine.
   * pydvmaVersion`), or `null` on the pyodide path / before a factory
   * resolves. Surfaced so `EngineProbe`'s status element can carry
   * `data-engine-version` for e2e/diagnosis; the store also uses it (right
   * below) to `warnOnPydvmaVersionMismatch` once at resolution time.
   */
  const pydvmaVersion = writable<string | null>(null);
  const status = writable<EngineStatus>('idle');
  // Each queued item carries its own `reject` so a boot FAILURE can settle it
  // (not just a boot success draining it). Without this, a compute call
  // enqueued during boot would hang forever if boot then errors.
  interface QueueItem { run: () => void; reject: (e: unknown) => void; }
  const queue: QueueItem[] = [];
  const readyWaiters: Array<{ resolve: () => void; reject: (e: unknown) => void }> = [];
  let booted = false;
  /**
   * Why the store is in 'error', for callers that arrive AFTER the failure —
   * `drain()` never re-runs, so nothing else would ever tell them. Two
   * writers, and they leave `booted` in DIFFERENT states on purpose:
   *
   *  - `boot()` on a failed init/factory: `booted` stays true, so the failure
   *    is terminal until something explicitly stops or re-boots the store;
   *  - `handleTransportLost()`: `booted` is cleared, because the engine was
   *    fine and the connection was not — a re-boot is a reconnect, and is
   *    expected to succeed.
   *
   * Cleared at the top of every `boot()` so a recovery starts clean.
   */
  let bootError: Error | null = null;
  /** In-flight `stop()`, so concurrent Stop clicks share one terminate+reboot. */
  let stopping: Promise<void> | null = null;
  /**
   * Identity of the CURRENT boot attempt. `boot()` captures it before its
   * awaits and re-checks it after, so an attempt that has been superseded
   * mid-flight — by `stop()`, or by a transport loss landing between the
   * client resolving and its init settling — can never resurrect 'ready'
   * over state the newer path has already moved past. Nulled (not just
   * replaced) by a transport loss, which supersedes without starting a
   * replacement.
   */
  let bootToken: object | null = null;

  /**
   * Wire client lifecycle observers -> the shared `engineProgress` store and
   * the store's own transport-lost handling. Called once per client: at
   * construction for a directly-injected one, and right after a factory
   * resolves one in `boot()`. (`observe` is optional on EngineClient — a stub
   * client just gets no bar and no transport-lost handling.)
   */
  function wireObserve() {
    // Mid-compute frames -> `engineProgress`. Only ops in PROGRESS_LABELS are
    // tracked; an unlabelled op's frames are ignored (it has opted out, or is
    // a future calc whose label has not been added yet).
    client?.observe?.({
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
      onTransportLost: handleTransportLost,
    });
  }

  /**
   * The transport died unasked (a socket only — see `EngineCallEvents`).
   *
   * Left alone, the store would sit at 'ready' over a dead connection: the
   * app looks healthy, the Stop button is the only re-boot path anyone can
   * reach, and every calc rejects with a bare "engine not connected" until
   * the user reloads. Instead this mirrors `stop()`'s reset — 'error' with a
   * message that names the cause, and `booted` cleared so a subsequent
   * `boot()` genuinely runs again. Recovery is therefore free on the normal
   * path: every compute entry point already calls the idempotent
   * `engine.boot()` first, which now re-runs and (for the socket client)
   * reconnects, since its own `connectPromise` was cleared by the same close.
   *
   * The resolved `client` is KEPT — the factory is not re-run, so a session
   * that chose the native host stays on it across a serve restart rather
   * than silently sliding onto the browser engine mid-session.
   */
  function handleTransportLost() {
    const s = get(status);
    // Only meaningful while we believe we have an engine. From 'idle' there
    // is nothing to lose, and from 'error' the story is already told.
    if (s !== 'ready' && s !== 'loading') return;
    bootToken = null;            // supersede any boot still in flight
    booted = false;              // ...and let the next boot() actually run
    bootError = new Error('engine connection lost — pydvma-serve stopped or restarted');
    console.error('[engine] transport lost:', bootError.message);
    status.set('error');
    // Anything parked (only possible from 'loading') would otherwise hang:
    // drain() never runs for a boot that has been superseded.
    failAll(bootError);
  }

  // A directly-injected client is observable from the start, exactly as
  // before Task 8; a factory-resolved one is wired inside boot() instead.
  if (client) wireObserve();

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
    bootError = null;              // a re-boot after a failure starts clean
    const token = {};
    bootToken = token;
    status.set('loading');
    try {
      if (client === null) {
        // First boot on the factory path: pick a transport (which for the
        // native host means connecting and getting its greeting) and keep
        // whatever answered for the rest of the session.
        const resolved = await (clientSource as () => Promise<ResolvedEngine>)();
        if (bootToken !== token) { resolved.client.dispose(); return; }
        client = resolved.client;
        // Session journal (stage 3): only a native client whose greeting
        // advertised one. Anything else NULLS the handle, so
        // `journalAvailable()` is false and every journal path in the app is
        // a no-op — Pages/JupyterLite behave exactly as before. Assigned in
        // both directions (not just set on success) so the last resolution
        // wins symmetrically, as `activeEngine` does — and assigned BEFORE
        // `host.set` below, whose subscribers (`whenResolved`) read it the
        // moment they wake.
        journalClient = (resolved.host === 'native' && resolved.journal) ? client : null;
        host.set(resolved.host);
        hostNote.set(resolved.note ?? null);
        pydvmaVersion.set(resolved.pydvmaVersion ?? null);
        if (resolved.host === 'native') warnOnPydvmaVersionMismatch(resolved.pydvmaVersion);
        wireObserve();
      }
      // Idempotent on the socket client (it hands back the connection the
      // factory just opened); the real work on the pyodide worker.
      await client.init(baseUrl, ENGINE_WHEELS, PYODIDE_VERSION);
      // A boot superseded mid-flight (stop(), or a transport loss) must not
      // report ready over state the newer path has already moved past.
      if (bootToken !== token) return;
      status.set('ready');
      drain();
    } catch (err) {
      // A boot killed BY a stop is not a boot failure: `stop()` rejects the
      // in-flight init when it terminates the worker, and is already booting a
      // replacement. Claiming 'error' here would fight that reboot (and reject
      // everything queued behind it with a bogus "failed to boot").
      if (isEngineStopped(err)) return;
      if (bootToken !== token) return;   // superseded — see above
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
   * Resolve once the client factory has ANSWERED — i.e. `host` is known and
   * (for a native client) its socket is already connected and greeted —
   * without waiting for the rest of `boot()`. Yields the resolved host, or
   * null when boot failed before ever resolving one.
   *
   * Distinct from {@link whenReady} on purpose, and the difference is the
   * whole point: on the pyodide path `boot()` continues into a multi-second
   * wasm+wheel install, so a caller that only needs to know WHICH engine
   * answered (App.svelte's session-journal gate) must not be parked behind
   * that — otherwise the degraded case, where native was expected and the
   * browser engine answered instead, is exactly the one that stalls the
   * shell's own restore flow. On the native path there is nothing left to
   * wait for anyway: the factory's `init` already opened the socket and took
   * the greeting, and the store's own `init` is idempotent over it.
   *
   * Never hangs: a boot that errors settles this too (with whatever host had
   * been recorded, normally null). A directly-injected client is 'pyodide'
   * from construction, so this resolves immediately.
   */
  function whenResolved(): Promise<EngineHostKind | null> {
    const known = get(host);
    if (known !== null) return Promise.resolve(known);
    if (get(status) === 'error') return Promise.resolve(null);
    return new Promise<EngineHostKind | null>((resolve) => {
      let settled = false;
      const unsubs: Array<() => void> = [];
      const done = (v: EngineHostKind | null) => {
        if (settled) return;
        settled = true;
        // Deferred: a svelte store fires its callback synchronously ON
        // subscribe, so `unsubs` may not hold this subscription yet.
        queueMicrotask(() => { for (const u of unsubs) u(); });
        resolve(v);
      };
      unsubs.push(host.subscribe((v) => { if (v !== null) done(v); }));
      unsubs.push(status.subscribe((s) => { if (s === 'error') done(get(host)); }));
    });
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
    // `client!` throughout: both paths run only in states boot() can reach
    // ONLY after it has bound a client ('ready' here; drain() for the queued
    // thunk). TS cannot narrow a closed-over `let` across the call boundary.
    if (s === 'ready') return client!.call<T>(op, payload);
    if (s === 'error') return Promise.reject(bootError ?? new Error('engine failed to boot'));
    return new Promise<T>((resolve, reject) => {
      queue.push({ run: () => client!.call<T>(op, payload).then(resolve, reject), reject });
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
    // `?.` for the factory path before its first boot: there is nothing to
    // restart yet, and the boot() below will resolve a client normally.
    // NB that path is superseded, not CANCELLED: a factory already in flight
    // keeps running, so the boot() below starts a SECOND one and two clients
    // eventually exist. The loser is the one whose `bootToken` check fails,
    // and that check disposes it — which is what keeps a stop() mid-connect
    // from leaving a live socket (server-side: an orphaned worker subprocess)
    // behind for the rest of the session.
    // For the SOCKET client, restart() closes the socket (the server reads
    // that as cancel-and-kill of the in-flight op) and clears its
    // `connectPromise`, so the boot() below genuinely RECONNECTS rather than
    // replaying a dead promise — the socket twin of terminating the worker.
    client?.restart(err);
    // Back through the normal lifecycle: 'idle' -> boot() -> 'loading' ->
    // 'ready', so the BusyChip's "starting engine…" state covers the reboot
    // and anything enqueued meanwhile queues and drains as usual.
    booted = false;
    bootError = null;
    bootToken = null;              // supersede any boot still in flight
    status.set('idle');
    await boot();
  }

  const store = {
    status,
    /** 'pyodide' | 'native', or null until a client factory has resolved. */
    host: { subscribe: host.subscribe } as Readable<EngineHostKind | null>,
    /** One-time user-facing notice from factory resolution, or null. See above. */
    hostNote: { subscribe: hostNote.subscribe } as Readable<string | null>,
    /** The native host's greeted pydvma release, or null. See above. */
    pydvmaVersion: { subscribe: pydvmaVersion.subscribe } as Readable<string | null>,
    boot,
    whenReady,
    whenResolved,
    enqueue,
    stop,
    /**
     * The bound client, or null before `boot()` resolves a factory. A GETTER,
     * not a captured value: on the factory path the client does not exist at
     * construction time.
     */
    get client(): EngineClient | null { return client; },
  };
  return store;
}

export type EngineStore = ReturnType<typeof createEngineStore>;
