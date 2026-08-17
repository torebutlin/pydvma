// selectEngine.ts — which engine host answers this session's compute?
//
// Two transports implement `EngineClient`: the pyodide worker (client.ts,
// compute inside the browser on a 32-bit wasm heap) and the native CPython
// host over the `/engine` websocket (socketClient.ts, compute in the
// pydvma-serve process, 64-bit and unbounded). This module owns the ONE
// decision of which one a session gets, so `stores/engine.ts` stays a queue
// and a status and knows nothing about transports.
//
// Stage-1 policy (opt-in): the native engine is used ONLY when the page
// carries `?enginehost=native` (same-origin /engine) or `?enginehost=ws://…`
// (an explicit URL — the cross-origin form the e2e uses to point a vite-served
// page at a spawned pydvma-serve). `?enginehost=pyodide` forces the worker.
// Anything else — and any native connect/greeting failure — falls back to the
// pyodide worker, which is today's behaviour on every deployment.
//
// Stage 2 (Task 10) adds served-by-pydvma-serve auto-detection: the same
// `/config` probe `audio/provider.ts` already uses, consulted only when
// `parseEngineParam` returns null (i.e. the user stated no preference).
import { createEngineClient, type EngineClient } from './client';
import { createSocketEngineClient } from './socketClient';

/** Which transport answered — reported by the engine store's `host`. */
export type EngineHostKind = 'pyodide' | 'native';

/** A live client plus the transport it speaks. */
export interface ResolvedEngine {
  client: EngineClient;
  host: EngineHostKind;
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
    return { client, host: 'native' };
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
 * Falls back to the pyodide worker on any native failure, loudly enough to
 * diagnose from the console but without an error the user has to dismiss:
 * the fallback engine computes the same answers, just slower and with the
 * wasm32 memory ceiling back in play.
 */
export async function resolveEngineClient(): Promise<ResolvedEngine> {
  const choice = parseEngineParam(engineHostParam());
  if (choice && choice.kind === 'native') {
    const url = choice.url === 'same-origin' ? defaultEngineWsUrl() : choice.url;
    const native = await tryNative(url);
    if (native) return native;
    console.warn('[engine-socket] native engine unavailable, using browser engine');
  }
  return { client: createEngineClient(), host: 'pyodide' };
}
