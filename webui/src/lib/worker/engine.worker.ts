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
//   4. write glue.py to the pyodide FS, pyimport('glue')
// Thereafter every `{op, payload}` calls `glue[op](**payload)` and marshals
// the returned dict (arrays -> {shape, data, complex}) back across postMessage.
//
// Protocol (mirrors client.ts):
//   in : { id, op: 'init', payload: { baseUrl, wheels } }
//        { id, op: <glue op>, payload: {...kwargs} }
//   out: { id, ok: true, result }
//        { id, ok: false, error }   — boot failure or op error
//
// `?raw` imports glue.py as a string at build time (Vite feature) so it is
// bundled with the worker and written to the in-memory FS at boot.
import { loadPyodide, type PyodideInterface } from 'pyodide';
// Vite `?raw` suffix yields the file contents as a string (typed via vite/client).
import glueSource from './glue.py?raw';

interface InitPayload {
  baseUrl: string;
  wheels: string[];
  /** pyodide version — used to build the CDN packageBaseUrl for prebuilt wheels. */
  pyodideVersion: string;
}

let pyodide: PyodideInterface | null = null;
let glue: any = null;

/**
 * Boot pyodide, load the numeric stack + micropip, install the pydvma and
 * peakutils wheels, and import glue.py. `baseUrl` is the served origin+base
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
  // Write glue.py into a dedicated dir and put it on sys.path so `import glue`
  // resolves it. (The FS root `/` is NOT on sys.path; writing to `/glue.py`
  // and importing would fail with ModuleNotFoundError.)
  pyodide.FS.mkdirTree('/engine');
  pyodide.FS.writeFile('/engine/glue.py', glueSource);
  const sys = pyodide.pyimport('sys');
  sys.path.append('/engine');
  glue = pyodide.pyimport('glue');
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
    const result = run(op, (payload ?? {}) as Record<string, unknown>);
    (self as unknown as Worker).postMessage({ id, ok: true, result });
  } catch (err) {
    (self as unknown as Worker).postMessage({
      id,
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
};
