// engine.worker.ts — the pydvma compute engine, running inside a web worker.
//
// This is an ES-MODULE worker (vite.config.ts: `worker: { format: 'es' }`),
// so classic `importScripts()` is unavailable — pyodide is booted through its
// ESM entry (`import { loadPyodide } from 'pyodide'`), NOT importScripts.
//
// Boot sequence (one `init` message):
//   1. loadPyodide({ indexURL: <baseUrl>/pyodide/ })   — vendored runtime
//   2. loadPackage(['numpy','scipy','micropip'])         — prebuilt in the lock
//   3. micropip.install([pydvma, peakutils] under <baseUrl>/pypi/, deps:false)
//      — deps:false keeps install fully offline (no PyPI index lookups)
//   4. pyimport('pydvma.engine') — the ops module ships INSIDE the pydvma
//      wheel installed above, so no separate fetch/write is needed
// Thereafter every `{op, payload}` calls `glue[op](**payload)` and marshals
// the returned dict (arrays -> {shape, data, complex}) back across postMessage.
//
// Protocol (mirrors client.ts):
//   in : { id, op: 'init', payload: { baseUrl, wheels } }
//        { id, op: <glue op>, payload: {...kwargs} }
//   out: { id, ok: true, result }
//        { id, ok: false, error }   — boot failure or op error
//        { type: 'progress', callId, done, total }  — mid-compute, unsolicited
//
// The progress frames are the one break from strict request/response (P7): a
// busy worker cannot RECEIVE, but it can post, so a long CWT reports itself
// scale by scale through the hook installed below. See `progress.ts`.
//
import { loadPyodide, type PyodideInterface } from 'pyodide';
import { createProgressPoster, type ProgressMessage } from './progress';

interface InitPayload {
  baseUrl: string;
  wheels: string[];
  /** pyodide version — used to build the CDN packageBaseUrl for prebuilt wheels. */
  pyodideVersion: string;
}

let pyodide: PyodideInterface | null = null;
let glue: any = null;

/**
 * Mid-compute progress reporter. Armed with the active request id around each
 * op (below) and handed to pydvma.engine once at boot, so pydvma's per-scale
 * `progress_callback` lands here and goes out as a `{type:'progress'}` frame.
 */
const progress = createProgressPoster((m: ProgressMessage) =>
  (self as unknown as Worker).postMessage(m));

/**
 * Boot pyodide, load the numeric stack + micropip, install the pydvma and
 * peakutils wheels, and import `pydvma.engine` (the ops module, riding
 * inside the pydvma wheel). `baseUrl` is the served origin+base
 * from the main thread (the worker has no reliable `import.meta.env.BASE_URL`
 * for absolute asset URLs), so all fetches are absolute: `<baseUrl>pyodide/`
 * and `<baseUrl>pypi/<wheel>`.
 *
 * We vendor only the pyodide RUNTIME locally (wasm, asm.js, stdlib, lock) —
 * the npm package ships no package wheels. So `packageBaseUrl` is pointed at
 * the official jsdelivr CDN (`.../pyodide/v<ver>/full/`), from which
 * `loadPackage(['numpy','scipy','micropip'])` fetches the prebuilt wheels the
 * lock references. Our own pure-python wheels still come from local `/pypi/`.
 */
async function boot({ baseUrl, wheels, pyodideVersion }: InitPayload): Promise<void> {
  const base = baseUrl.endsWith('/') ? baseUrl : baseUrl + '/';
  pyodide = await loadPyodide({
    indexURL: base + 'pyodide/',
    packageBaseUrl: `https://cdn.jsdelivr.net/pyodide/v${pyodideVersion}/full/`,
  });
  await pyodide.loadPackage(['numpy', 'scipy', 'micropip']);
  const micropip = pyodide.pyimport('micropip');
  // Install BOTH vendored wheels in a SINGLE call with deps disabled. This is
  // load-bearing for the offline goal: the pydvma wheel declares
  // `Requires-Dist: peakutils` (and matplotlib), so with the default
  // deps=True micropip would resolve those from LIVE PyPI *before* our local
  // peakutils install runs — boot then dies with "Can't fetch metadata for
  // 'peakutils'" whenever pypi.org is unreachable. deps=false stops ALL index
  // lookups; the numpy/scipy/micropip runtime deps are already satisfied by
  // the loadPackage above, and matplotlib is imported only lazily by pydvma
  // (never on the `import pydvma` + analysis/datastructure/container path this
  // worker uses), so nothing else is needed. If a future compute path pulls a
  // package not loaded here, add it to the loadPackage([...]) list — from the
  // pyodide CDN, never PyPI.
  const wheelUrls = wheels.map((w) => base + 'pypi/' + w);
  await micropip.install.callKwargs(wheelUrls, { deps: false });
  // Engine ops ship INSIDE the pydvma wheel installed above (stage 0 of the
  // native-engine design) — no more ?raw bundling, no FS write, and the ops
  // can never be newer or older than the pydvma they call. Dev-loop note:
  // editing pydvma/engine.py needs `cd webui && npm run vendor:wheels` before
  // the browser sees it — vite no longer re-reads the source, since it's not
  // bundled anymore. When testing the BUILT app, hard-reload after a
  // rebuild: the wheel keeps the same filename, so an HTTP-cached copy can
  // silently keep serving stale ops.
  try {
    glue = pyodide.pyimport('pydvma.engine');
  } catch (e) {
    throw new Error('pydvma.engine is missing from the installed wheel — rebuild the vendored '
      + 'engine wheel: cd webui && npm run vendor:wheels. Original: '
      + (e instanceof Error ? e.message : String(e)));
  }
  // Install the progress hook ONCE (not per call): glue keeps it in a module
  // global and passes it to any pydvma function that accepts a
  // `progress_callback`, while the per-call ARMING below is what scopes the
  // frames to a request id. Guarded not because an older bundled glue could
  // lack it (there is no bundled glue any more — the wheel and the ops
  // module are always the same version) but as cheap insurance against a
  // hypothetical wheel/ops mismatch, e.g. a stale cached wheel with an
  // older pydvma.engine that predates this hook.
  const install = glue.set_progress_hook;
  if (install) {
    try {
      install(progress.postProgress);
    } finally {
      if (typeof install.destroy === 'function') install.destroy();
    }
  }
}

/**
 * Run one compute op. `glue[op]` is a PyProxy callable; we invoke it with the
 * payload's values as keyword args via `callKwargs`, then `toJs` the result so
 * nested dicts become plain objects and numpy arrays become Float64Array.
 * `create_proxies: false` guarantees no lingering PyProxy leaks; we destroy
 * the top-level result proxy explicitly.
 */
function run(op: string, payload: Record<string, unknown>): unknown {
  if (!pyodide || !glue) throw new Error('engine not initialised');
  const fn = glue[op];
  if (fn == null) throw new Error(`unknown op: ${op}`);
  // fn's try/finally wraps the callKwargs too: a Python op that RAISES throws
  // out of callKwargs, so if it sat outside the try the fn proxy would leak.
  try {
    // Pass kwargs: callKwargs takes (...positional, kwargsObject).
    const resultProxy = fn.callKwargs(payload);
    try {
      return resultProxy.toJs({
        dict_converter: Object.fromEntries,
        create_proxies: false,
      });
    } finally {
      if (resultProxy && typeof resultProxy.destroy === 'function') resultProxy.destroy();
    }
  } finally {
    if (typeof fn.destroy === 'function') fn.destroy();
  }
}

self.onmessage = async (e: MessageEvent) => {
  const { id, op, payload } = e.data ?? {};
  try {
    if (op === 'init') {
      await boot(payload as InitPayload);
      (self as unknown as Worker).postMessage({ id, ok: true, result: null });
      return;
    }
    // Arm progress for THIS id: the Python hook reports only (done, total), so
    // the id it belongs to is worker state. Disarmed in the finally so a frame
    // can never be attributed to the wrong (or a settled) call.
    progress.arm(id);
    let result: unknown;
    try {
      result = run(op, (payload ?? {}) as Record<string, unknown>);
    } finally {
      progress.disarm();
    }
    (self as unknown as Worker).postMessage({ id, ok: true, result });
  } catch (err) {
    (self as unknown as Worker).postMessage({
      id,
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
};
