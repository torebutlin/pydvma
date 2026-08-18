// selectEngine.ts — which engine host answers this session's compute?
//
// Two transports implement `EngineClient`: the pyodide worker (client.ts,
// compute inside the browser on a 32-bit wasm heap) and the native CPython
// host over the `/engine` websocket (socketClient.ts, compute in the
// pydvma-serve process, 64-bit and unbounded). This module owns the ONE
// decision of which one a session gets, so `stores/engine.ts` stays a queue
// and a status and knows nothing about transports.
//
// Stage-2 policy (default flip, Task 10): an explicit `?enginehost=` always
// wins — `native` (same-origin /engine), `ws://…`/`wss://…` (an explicit
// URL — the cross-origin form the e2e uses to point a vite-served page at a
// spawned pydvma-serve), or `pyodide` (forces the browser worker). With NO
// param stated, the page auto-detects: served by a `pydvma serve` process
// (the same same-origin `/config` probe `audio/provider.ts` already uses)
// means native by default; anything else (GitHub Pages, plain `vite dev`,
// JupyterLite) stays on the pyodide worker, today's behaviour unchanged.
// Any native connect/greeting failure (including a protocol version
// mismatch — see `socketClient.ts`) falls back to the pyodide worker too, so
// the flip never turns into a hard failure mode.
import { probeServeConfig } from '../audio/provider';
import { createEngineClient, type EngineClient } from './client';
import { createSocketEngineClient } from './socketClient';

/** Which transport answered — reported by the engine store's `host`. */
export type EngineHostKind = 'pyodide' | 'native';

/** A live client plus the transport it speaks. */
export interface ResolvedEngine {
  client: EngineClient;
  host: EngineHostKind;
  /**
   * Set ONLY when `served` auto-detection (no explicit `?enginehost=`)
   * chose native and the connect/greeting then failed — a capability
   * DOWNGRADE the user should know about (the wasm32 memory ceiling is back)
   * rather than the one detection promised, not just a `console.warn` they'd
   * have to open devtools to see. `undefined` in every other case, including
   * an EXPLICIT `?enginehost=native`/URL that fails: there the user asked
   * for a specific host, already knows what they asked for, and the
   * `console.warn` in {@link tryNative}'s catch is enough. `stores/engine.ts`
   * surfaces this as `hostNote`; `App.svelte` raises it as a toast.
   */
  note?: string;
  /**
   * The native host's greeted pydvma release (`SocketEngineClient.
   * pydvmaVersion`), or `undefined` on the pyodide path (no server to
   * report one). Carried through so `stores/engine.ts` can surface it
   * (`EngineProbe`'s `data-engine-version`) and warn on a mismatch against
   * `ENGINE_WHEELS[0]` — see `SUPPORTED_ENGINE_PROTOCOL_VERSION`'s docstring
   * in `socketClient.ts` for why that check warns rather than gates.
   */
  pydvmaVersion?: string;
  /**
   * Whether the native host owns a SESSION JOURNAL (`SocketEngineClient.
   * journalSupported`, from the greeting's `journal` field) — i.e. whether
   * `journal_set`/`journal_get`/`journal_discard_recovered` are answered.
   * `undefined` on the pyodide path (no server, no journal).
   *
   * Capability-gated, never version-gated: a `pydvma-serve` predating the
   * journal speaks the same wire protocol and simply omits the flag, so
   * `stores/engine.ts`'s `journalAvailable()` gates on THIS and the app then
   * behaves exactly as it did before stage 3 (IndexedDB autosave only).
   */
  journal?: boolean;
}

/**
 * What the `?enginehost=` parameter asked for, or `null` when it asked for
 * nothing. `'same-origin'` means "build the URL from the page's own origin"
 * — deliberately NOT resolved here so the decision stays pure and testable
 * in node, where there is no `window` to resolve against.
 *
 * `null` and `{kind:'pyodide'}` are DIFFERENT answers: the first is "the
 * user stated no preference" (Task 10's auto-detection may still choose
 * native), the second is an explicit opt-OUT that must always win.
 */
export type EngineParamChoice =
  | { kind: 'pyodide' }
  | { kind: 'native'; url: string };

/**
 * Interpret a raw `?enginehost=` value. Pure — no `window`, no I/O — so the
 * policy is unit-testable and Task 10 can extend the CALLER with
 * served-detection without this meaning drifting.
 *
 * - `null` / `''`  → `null` (no preference stated)
 * - `'pyodide'`    → the browser worker, explicitly
 * - `'native'`     → the native host at the same origin (`'same-origin'`)
 * - anything else  → the native host at that URL, verbatim
 */
export function parseEngineParam(p: string | null): EngineParamChoice | null {
  if (!p) return null;
  if (p === 'pyodide') return { kind: 'pyodide' };
  if (p === 'native') return { kind: 'native', url: 'same-origin' };
  return { kind: 'native', url: p };
}

/**
 * The resolved engine-host decision — `EngineParamChoice` minus the `null`
 * ("no preference") case, since {@link decideEnginePolicy} always resolves
 * one by folding in `served`. `'same-origin'` is still the unresolved
 * sentinel (see {@link EngineParamChoice}).
 */
export type EnginePolicy = NonNullable<EngineParamChoice>;

/**
 * Stage-2 policy, pure and unit-testable without `window`: an explicit
 * `?enginehost=` (as parsed by {@link parseEngineParam}) always wins, in
 * EITHER direction — `pyodide` forces the browser worker even when the page
 * is served by `pydvma serve`, and an explicit native URL is honoured even
 * when detection says not-served (the e2e's cross-origin form). Only when
 * `param` states no preference does `served` decide: served-by-`pydvma
 * serve` defaults to the native host at the same origin, anything else
 * (Pages, plain `vite dev`, JupyterLite) stays on pyodide.
 *
 * `served` must be computed LAZILY by the caller — only probe `/config` when
 * `param` is null — this function itself has no opinion on that; the rule
 * lives in {@link resolveEngineClient}.
 */
export function decideEnginePolicy(param: string | null, served: boolean): EnginePolicy {
  return parseEngineParam(param) ?? (served ? { kind: 'native', url: 'same-origin' } : { kind: 'pyodide' });
}

/**
 * Same-origin `/engine` websocket URL — the mirror of `audio/provider.ts`'s
 * `defaultBridgeWsUrl()` (which points at `/ws`, the acquisition bridge).
 * Both endpoints are served by the same `pydvma-serve` process.
 */
export function defaultEngineWsUrl(): string {
  if (typeof window === 'undefined') return 'ws://127.0.0.1:8760/engine';
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/engine`;
}

/** The page's raw `?enginehost=` value, or null off-browser / unset. */
function engineHostParam(): string | null {
  if (typeof window === 'undefined') return null;
  return new URLSearchParams(window.location.search).get('enginehost');
}

/**
 * Would this session's engine be the NATIVE host? The SAME decision
 * {@link resolveEngineClient} makes — an explicit `?enginehost=` first, then
 * the lazy `/config` served probe — but without constructing or connecting
 * anything.
 *
 * Exists for `App.svelte`'s boot-time session-journal check, which has a
 * chicken-and-egg problem: the journal lives on the native engine, but
 * whether the engine IS native is only knowable once one has been resolved,
 * and resolving it means `boot()` — which on the pyodide path costs a
 * multi-second wasm boot the shell deliberately defers until the first
 * compute. Asking this first keeps that deferral intact: only a session
 * that was going to be native anyway boots eagerly (a socket connect and a
 * greeting), and Pages / `vite dev` / JupyterLite answer `false` here and
 * boot nothing.
 *
 * Costs one extra same-origin `/config` probe when (and only when) no
 * `?enginehost=` param is stated — the same cheap request
 * {@link resolveEngineClient} and `audio/provider.ts`'s `selectProvider`
 * each already make, and skipped entirely when a param decides it.
 */
export async function willUseNativeEngine(): Promise<boolean> {
  const param = engineHostParam();
  const served = param ? false : await probeServeConfig();
  return decideEnginePolicy(param, served).kind === 'native';
}

/**
 * Try the native host: connect and wait for the `engine_ready` greeting
 * (`init` does both), returning null on any failure so the caller can fall
 * back. The greeting check is what makes the probe meaningful — a wrong URL
 * that still accepts a socket (`/ws` instead of `/engine`, one character out)
 * connects happily and then says nothing, so `socketClient`'s greeting
 * timeout is the real gate here. That timeout is its built-in default: it is
 * reachable only through `init`'s optional 4th argument, which the
 * `EngineClient` interface does not declare, so production callers take the
 * default by construction (tests reach it via the client directly).
 *
 * The socket client's `init` is IDEMPOTENT — it hands back the same
 * `connectPromise` while connected — so the engine store's own
 * `client.init(baseUrl, ENGINE_WHEELS, PYODIDE_VERSION)` on this same client
 * moments later resolves off THIS connection instead of opening a second
 * socket (which server-side would mean a second orphaned worker subprocess).
 * Nothing here needs to defend against that second call.
 */
async function tryNative(url: string): Promise<ResolvedEngine | null> {
  // baseUrl / wheels / pyodideVersion are pyodide-worker concerns; the socket
  // client accepts and ignores them (see its init docstring).
  const client = createSocketEngineClient(url);
  try {
    await client.init('', [], '');
    // client.pydvmaVersion / .journalSupported are populated by the greeting
    // client.init() just awaited above — see SocketEngineClient's docstring
    // in socketClient.ts.
    return {
      client,
      host: 'native',
      pydvmaVersion: client.pydvmaVersion ?? undefined,
      journal: client.journalSupported,
    };
  } catch (e) {
    console.warn('[engine-socket] native engine probe failed:', e);
    client.dispose();
    return null;
  }
}

/**
 * Resolve this session's engine client — the default `clientSource` of
 * `createEngineStore`. Called ONCE, from `boot()`, so a session that never
 * computes never opens a socket and never spawns a worker.
 *
 * The `/config` served-ness probe ({@link probeServeConfig} — the SAME
 * function `audio/provider.ts`'s `selectProvider` uses to detect the bridge)
 * runs ONLY when the page states no `?enginehost=` preference — an explicit
 * param short-circuits {@link decideEnginePolicy} before `served` is ever
 * consulted, so a page with an explicit param (the e2e's cross-origin form,
 * a forced `?enginehost=pyodide`) pays no probe at all. A no-param served
 * deployment pays exactly the one EXTRA probe beyond what `selectProvider`
 * already makes for the acquisition backend (both target the same
 * same-origin `/config`, so the two requests are cheap and independent); a
 * no-param vite dev server gets a fast `false` (no `/config` route) and
 * stays on pyodide.
 *
 * Deliberately `probeServeConfig`, NOT `fetchServeConfig`: a `pydvma serve`
 * session started without `--settings` (the ordinary case) publishes an
 * EMPTY `/config` document, which `fetchServeConfig` collapses to `null` for
 * its own (unrelated) "anything worth prefilling Setup from" purpose. Using
 * that as the served-ness signal here would silently keep every
 * unset-settings bridge session on pyodide — caught by the served-mode e2e
 * below, which spawns the mock driver with no `--settings` (as real users
 * commonly do).
 *
 * Falls back to the pyodide worker on any native failure, loudly enough to
 * diagnose from the console but without an error the user has to dismiss:
 * the fallback engine computes the same answers, just slower and with the
 * wasm32 memory ceiling back in play.
 */
export async function resolveEngineClient(): Promise<ResolvedEngine> {
  const param = engineHostParam();
  const served = param ? false : await probeServeConfig();
  const policy = decideEnginePolicy(param, served);
  if (policy.kind === 'native') {
    const url = policy.url === 'same-origin' ? defaultEngineWsUrl() : policy.url;
    const native = await tryNative(url);
    if (native) return native;
    console.warn('[engine-socket] native engine unavailable, using browser engine');
    // A user-facing notice ONLY for the auto-detected case: `policy.kind ===
    // 'native'` with no explicit `param` is reachable ONLY when `served` was
    // true (decideEnginePolicy), i.e. detection promised native on the
    // user's behalf and then failed to deliver it -- see ResolvedEngine.note.
    // An explicit `?enginehost=` failure stays console-only: the user asked
    // for a specific host and the console.warn above already told them why
    // it didn't work.
    const note = !param
      ? 'native engine unavailable — using browser engine (see console)'
      : undefined;
    return { client: createEngineClient(), host: 'pyodide', note };
  }
  return { client: createEngineClient(), host: 'pyodide' };
}
