// socketClient.ts — EngineClient over the /engine websocket (native host).
//
// Same contract as worker/client.ts (id-correlated request/response +
// unsolicited progress), different transport: binary frames per frames.ts
// to a CPython pydvma-serve. init() connects and waits for the engine_ready
// greeting; restart() closes the socket (the server treats close as
// cancel-and-kill of the in-flight op) and the store's re-boot reconnects.
import type { EngineCallEvents, EngineClient } from './client';
import { decodeFrame, encodeFrame } from './frames';

/**
 * The WebSocket slice this client depends on. Structurally identical to
 * `audio/bridge.ts`'s `WsLike` (same injectable-socket pattern for tests),
 * but declared locally so worker/ carries no dependency on the audio
 * domain's module.
 */
export interface EngineWsLike {
  readyState: number;
  binaryType: string;
  send(data: string | ArrayBufferLike | ArrayBufferView): void;
  close(code?: number, reason?: string): void;
  onopen: ((ev?: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onerror: ((ev?: unknown) => void) | null;
  onclose: ((ev?: unknown) => void) | null;
}

/** Default factory: a real browser WebSocket (overridable for tests). */
function defaultWsFactory(url: string): EngineWsLike {
  const ws = new WebSocket(url) as unknown as EngineWsLike;
  ws.binaryType = 'arraybuffer';
  return ws;
}

/**
 * How long `init()` waits for the `engine_ready` greeting before giving up.
 * A silent peer -- the classic trap is `?enginehost=` pointed at `/ws`
 * instead of `/engine` by a one-character slip, which accepts the socket
 * and then says nothing until commanded -- would otherwise hang `init()`
 * forever, since nothing here ever settles on its own without SOME message
 * arriving. Injectable via `init()`'s `opts` for tests.
 */
const DEFAULT_GREETING_TIMEOUT_MS = 5000;

/**
 * The wire protocol version this client speaks -- must match the greeting's
 * `v` exactly (additive growth is not assumed; see `engine_host.py`'s
 * `ENGINE_PROTOCOL_VERSION`). A mismatch is rejected rather than tolerated,
 * so a client talking to a server from a different pydvma release fails
 * loudly at connect time instead of exchanging frames neither side decodes
 * the way the other expects. `resolveEngineClient`'s `tryNative` turns this
 * rejection into the ordinary silent pyodide fallback, same as any other
 * native-connect failure.
 *
 * DECISION: this is the ONLY version gated hard. The greeting also carries
 * `pydvma` (the server's `pydvma.datastructure.VERSION`, e.g. `'2.3.0'`) --
 * that one is surfaced (`pydvmaVersion` below, plus a `console.info` at
 * connect) and compared against `stores/engine.ts`'s `ENGINE_WHEELS[0]`
 * (the release this webui BUNDLE was built against), but a mismatch there
 * only `console.warn`s, it never rejects the connection. A patch-level skew
 * is a LEGITIMATE working configuration -- an editable `pydvma` install
 * paired with an unrebuilt webui bundle, or `pydvma serve` upgraded a patch
 * ahead of a cached bundle -- as long as the WIRE PROTOCOL (this constant)
 * still matches; the fat wheel normally ships the UI and `pydvma serve`
 * together (see CLAUDE.md's release notes), so the common case is an exact
 * match and the warn never fires.
 */
const SUPPORTED_ENGINE_PROTOCOL_VERSION = 1;

interface Pending { op: string; resolve: (v: any) => void; reject: (e: any) => void }

/**
 * `EngineClient` plus the extras the socket transport carries that a Worker
 * has no equivalent for:
 *
 *  - `pydvmaVersion` — the native host's own `pydvma` release (the
 *    greeting's `pydvma` field); `null` before any greeting has arrived
 *    (never connected, or connected but not yet greeted);
 *  - `journalSupported` — whether this server owns a session journal (the
 *    greeting's `journal` field, `false` unless it is exactly `true`), i.e.
 *    whether `journal_set`/`journal_get`/`journal_discard_recovered` ops are
 *    answered here. Capability-gated rather than version-gated: a serve that
 *    predates the journal greets with the SAME protocol version and simply
 *    omits the flag, so the app must gate on this and never on `v`.
 *  - `onJournalUpdate` — see {@link EngineClient.onJournalUpdate}; declared
 *    non-optional here because the socket transport always provides it.
 *
 * None of these belong in the shared `EngineClient` shape as required
 * members: they are meaningless for the pyodide worker client, which has no
 * server release to report and no server-side journal.
 * `resolveEngineClient`'s `tryNative` reads them off THIS type to carry them
 * into `ResolvedEngine`.
 */
export interface SocketEngineClient extends EngineClient {
  readonly pydvmaVersion: string | null;
  readonly journalSupported: boolean;
  onJournalUpdate(cb: () => void): () => void;
}

/**
 * Create an engine client over the native `/engine` websocket. Pass a
 * `wsFactory` to inject a fake socket (tests); omit it to connect a real
 * `WebSocket`. Mirrors `createEngineClient`'s id-correlated pending map,
 * but unlike a Worker a socket can go away on its own (server crash,
 * network drop) — so this client also tracks `connected` and reacts to an
 * unsolicited close the same way a deliberate `restart`/`dispose` would.
 */
export function createSocketEngineClient(
  url: string,
  wsFactory: (url: string) => EngineWsLike = defaultWsFactory,
): SocketEngineClient {
  const pending = new Map<number, Pending>();
  let nextId = 1;
  let ws: EngineWsLike | null = null;
  let connected = false;
  let disposed = false;
  let events: EngineCallEvents = {};
  // The native host's own pydvma release, from the greeting's `pydvma`
  // field -- null until the first greeting arrives. Surfaced (not gated;
  // see SUPPORTED_ENGINE_PROTOCOL_VERSION's docstring) via the
  // `pydvmaVersion` getter below.
  let pydvmaVersion: string | null = null;
  // Whether the greeted server owns a session journal (stage 3) -- false
  // until a greeting says otherwise, and re-read on every greeting so a
  // reconnect to a DIFFERENT server (a serve restarted without the journal)
  // cannot leave a stale `true` behind.
  let journalSupported = false;
  /**
   * Subscribers to server-initiated journal updates (`{"type":"journal"}`
   * text frames — a notebook `Session.push`). Per-INSTANCE, not module-level:
   * this client is instance-based (a second one exists whenever `EngineProbe`
   * is mounted under `?engine=1`), so module-scoped subscribers would receive
   * another connection's pushes. `stores/engine.ts` re-exports a module-level
   * `onJournalUpdate` facade over the ACTIVE client so `App.svelte` still has
   * one stable import. Survives `restart()` + reconnect deliberately (the
   * socket is replaced, this client object is not), and is dropped only by
   * the terminal `dispose()`.
   */
  const journalSubs = new Set<() => void>();
  // The in-flight init()'s reject, live only while a connect is awaiting its
  // greeting. init() is NOT in `pending` (it has no request id yet), so
  // rejectAll() can't reach it -- restart()/dispose() must settle it
  // separately, and BEFORE detaching the socket's onclose/onerror handlers
  // that would otherwise be its only path to ever settling.
  let initReject: ((e: Error) => void) | null = null;
  // The current connect attempt, kept around for as long as it is either
  // still in flight OR successfully connected -- so a second init() call
  // (Task 8 calls init() twice: a native-host probe, then the store's own
  // boot()) reuses it instead of opening a second socket, which server-side
  // means a second orphaned worker subprocess. Cleared whenever the
  // connection actually ends (failure, unsolicited close, restart, dispose)
  // so the NEXT init() genuinely reconnects rather than replaying a dead
  // promise forever.
  let connectPromise: Promise<void> | null = null;

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
    // finish() already deletes each entry it settles, so by here `pending`
    // is normally already empty -- this is defensive parity with
    // client.ts's rejectAll, in case a reject handler above re-enters and
    // adds something mid-loop.
    pending.clear();
  }

  /** Steady-state onclose: the server (or network) went away unasked. */
  function handleUnsolicitedClose() {
    connected = false;
    connectPromise = null; // let a subsequent init() actually reconnect
    ws = null;
    rejectAll(new Error('native engine connection closed'));
    // AFTER rejectAll, so the observer sees a settled world (and any progress
    // entry has already been cleared by the onSettled each rejection fires).
    // A Worker cannot do this to you; a socket can, so the store needs telling
    // or it stays 'ready' over a dead transport. Deliberately NOT fired by
    // restart()/dispose(): those are the caller's own doing.
    events.onTransportLost?.();
  }

  /** A binary frame is always a reply: `{id, ok, result | error}`. */
  function handleBinary(data: ArrayBuffer | Uint8Array) {
    let reply: { id: number; ok: boolean; result?: unknown; error?: string };
    try {
      reply = decodeFrame(data) as typeof reply;
    } catch (e) {
      // A corrupt/truncated frame must not wedge the client -- drop it and
      // keep serving whatever else is pending (mirrors engine_host.py's own
      // per-frame try/except: one bad frame must not kill the connection).
      console.warn('[engine-socket] undecodable frame', e);
      return;
    }
    const entry = finish(reply.id);
    if (!entry) return; // unknown / already-settled id -- ignore
    if (reply.ok) entry.resolve(reply.result);
    else entry.reject(new Error(reply.error ?? 'engine error'));
  }

  /** A text frame is either progress, a server-side decode error, or noise. */
  function handleText(text: string) {
    let msg: any;
    try {
      msg = JSON.parse(text);
    } catch (e) {
      console.warn('[engine-socket] unparseable text frame', text, e);
      return;
    }
    if (msg?.type === 'progress') {
      const entry = pending.get(msg.callId);
      if (entry) {
        events.onProgress?.({ callId: msg.callId, op: entry.op, done: msg.done, total: msg.total });
      }
      return; // unknown/settled callId -- ignore silently
    }
    if (msg?.type === 'journal') {
      // The serve process's session document changed under us -- a notebook
      // `Session.push` (the app's OWN journal_set posts are silent, so this
      // is never an echo of our own write). Carries no payload by design:
      // subscribers re-read the journal with `journal_get`. Iterate a COPY
      // so a subscriber that unsubscribes itself from inside the callback
      // cannot mutate the set mid-iteration.
      for (const cb of [...journalSubs]) {
        try {
          cb();
        } catch (e) {
          // One broken subscriber must not silence the rest, nor wedge the
          // socket's message pump.
          console.warn('[engine-socket] journal subscriber failed', e);
        }
      }
      return;
    }
    if (msg?.type === 'error') {
      // The server couldn't decode an inbound frame at all, so it carries no
      // id to correlate -- nothing in `pending` can be resolved/rejected
      // from this alone. Surface it for diagnosis and otherwise ignore.
      console.warn('[engine-socket] server error', msg.message);
      return;
    }
    // A stray engine_ready (or anything else) outside init -- ignore rather
    // than throw; the greeting is only meaningful once, during init().
  }

  /** Route one onmessage event's data, whatever shape it arrived in. */
  function handleMessage(data: unknown) {
    if (typeof data === 'string') {
      handleText(data);
      return;
    }
    if (data instanceof ArrayBuffer || data instanceof Uint8Array) {
      handleBinary(data);
      return;
    }
    // This client always sets binaryType='arraybuffer', so a Blob here would
    // mean something bypassed that (a hand-rolled fake, a future browser
    // quirk) -- warn rather than throw so one weird frame doesn't wedge us.
    console.warn('[engine-socket] unexpected message data type', data);
  }

  /**
   * Open one socket and resolve once its greeting arrives. Factored out of
   * `init()` so the `connectPromise` dedup wrapper is the only place that
   * decides WHETHER to start a new attempt; this only knows how to run one.
   */
  function doConnect(opts?: { greetingTimeoutMs?: number }): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      // Defensive: every termination path below nulls `ws`, so a live one
      // here should never happen -- but if some future change forgets to,
      // this must not leak a second socket alongside it (server-side, a
      // second live socket = a second orphaned worker subprocess).
      if (ws) {
        const stale = ws;
        stale.onopen = null;
        stale.onmessage = null;
        stale.onerror = null;
        stale.onclose = null;
        stale.close();
        ws = null;
      }

      const sock = wsFactory(url);
      sock.binaryType = 'arraybuffer';
      ws = sock;
      let settled = false;
      let timeoutHandle: ReturnType<typeof setTimeout> | undefined;

      const settleReject = (err: Error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeoutHandle);
        initReject = null;
        reject(err);
      };
      // Live for the duration of this connect attempt only -- cleared on
      // any settle path (including the greeting arriving), so a
      // restart()/dispose() after that point falls through to the normal
      // `pending`-map rejection instead of double-settling this promise.
      initReject = settleReject;

      /** A failure path: settle + release the socket, optionally forcing it shut. */
      const giveUp = (err: Error, forceClose: boolean) => {
        settleReject(err);
        if (ws === sock) { ws = null; connected = false; }
        if (forceClose) {
          sock.onclose = null;
          sock.close();
        }
      };

      const timeoutMs = opts?.greetingTimeoutMs ?? DEFAULT_GREETING_TIMEOUT_MS;
      timeoutHandle = setTimeout(() => {
        giveUp(new Error('native engine greeting timed out — is the URL an /engine endpoint?'), true);
      }, timeoutMs);

      sock.onerror = () => giveUp(new Error('native engine connect failed'), false);
      sock.onclose = () => giveUp(new Error('native engine connection closed before greeting'), false);
      sock.onmessage = (e: { data: unknown }) => {
        if (typeof e.data !== 'string') return; // the greeting is always text
        let msg: any;
        try {
          msg = JSON.parse(e.data);
        } catch (err) {
          console.warn('[engine-socket] unparseable text frame during connect', e.data, err);
          return;
        }
        if (msg?.type !== 'engine_ready') return;
        if (settled) return;
        // Version gate: a greeting whose `v` doesn't match what this client
        // speaks is treated as a connect FAILURE, not a successful connect to
        // an incompatible peer -- same `giveUp` path a bad URL or a dead
        // socket takes, so `tryNative`'s catch turns it into the ordinary
        // silent pyodide fallback (see the constant's docstring above).
        if (msg.v !== SUPPORTED_ENGINE_PROTOCOL_VERSION) {
          giveUp(
            new Error(
              `native engine protocol v${msg.v} unsupported (this client speaks v${SUPPORTED_ENGINE_PROTOCOL_VERSION}) — falling back to browser engine`,
            ),
            true,
          );
          return;
        }
        settled = true;
        clearTimeout(timeoutHandle);
        initReject = null;
        connected = true;
        // Surface the native host's own pydvma release -- diagnostic only
        // (see SUPPORTED_ENGINE_PROTOCOL_VERSION's docstring: unlike `v`
        // above, this is never gated). `typeof` guards a greeting from an
        // older/odd server that omits or mistypes the field.
        pydvmaVersion = typeof msg.pydvma === 'string' ? msg.pydvma : null;
        // Session-journal capability (stage 3), strict-true only: an absent
        // or non-boolean field means "this server has no journal", which is
        // exactly what a pre-journal serve of the same protocol version
        // sends. See SocketEngineClient's docstring.
        journalSupported = msg.journal === true;
        if (pydvmaVersion) console.info('[engine-socket] native engine: pydvma ' + pydvmaVersion);
        // Steady-state handlers take over only now that init is done.
        sock.onmessage = (ev: { data: unknown }) => handleMessage(ev.data);
        sock.onclose = () => handleUnsolicitedClose();
        // The init-time onerror above would otherwise sit here as a dead
        // settleReject closure (settled is already true, so it's a silent
        // no-op) -- replace it with a visible diagnostic instead.
        sock.onerror = (ev?: unknown) => console.warn('[engine-socket] socket error', ev);
        resolve();
      };
      sock.onopen = () => { /* wait for the engine_ready greeting */ };
    });
  }

  return {
    /** The native host's greeted pydvma release, or null pre-greeting. */
    get pydvmaVersion(): string | null { return pydvmaVersion; },

    /** Whether the greeted server answers journal ops (false pre-greeting). */
    get journalSupported(): boolean { return journalSupported; },

    onJournalUpdate(cb: () => void): () => void {
      journalSubs.add(cb);
      return () => { journalSubs.delete(cb); };
    },

    // baseUrl/wheels/pyodideVersion are pyodide-worker concerns (vendored
    // engine assets + wheel install) -- meaningless for a CPython host over
    // a socket, so they're accepted (to satisfy the EngineClient shape) and
    // ignored. `opts.greetingTimeoutMs` overrides the connect+greeting
    // deadline (tests only; production callers get the default).
    init(
      _baseUrl?: string,
      _wheels?: string[],
      _pyodideVersion?: string,
      opts?: { greetingTimeoutMs?: number },
    ): Promise<void> {
      if (disposed) return Promise.reject(new Error('engine client disposed'));
      // In-flight OR already connected: Task 8 calls init() twice (a
      // native-host probe, then the store's own boot()) -- both must
      // resolve off the SAME connection, not spawn a second socket.
      if (connectPromise) return connectPromise;
      const attempt = doConnect(opts);
      connectPromise = attempt;
      // Only clear connectPromise for what turns out to be a FAILED
      // attempt, and only if nothing newer has already replaced it
      // (restart()/dispose() may themselves have reset connectPromise by
      // the time this runs). Attached AFTER the assignment above:
      // doConnect's executor runs synchronously, so wiring this from
      // *inside* doConnect (before `connectPromise = attempt` had even
      // executed) would risk a same-tick failure being silently
      // overwritten right back to the dead promise by that assignment.
      attempt.catch(() => {
        if (connectPromise === attempt) connectPromise = null;
      });
      return attempt;
    },

    call<T = unknown>(op: string, payload: Record<string, unknown> = {}): Promise<T> {
      if (disposed) return Promise.reject(new Error('engine client disposed'));
      if (!connected || !ws) return Promise.reject(new Error('engine not connected'));
      const id = nextId++;
      const sock = ws;
      return new Promise<T>((resolve, reject) => {
        pending.set(id, { op, resolve, reject });
        let frame: ArrayBuffer;
        try {
          frame = encodeFrame({ id, op, payload: payload ?? {} });
        } catch (e) {
          // encodeFrame throws BY DESIGN on a payload carrying a typed array
          // it doesn't recognise (frames.ts) -- without this, the pending
          // entry above would leak forever: never sent, never replied-to,
          // never settled. finish() removes it and fires onSettled; the
          // rethrow settles THIS promise the same as calling reject(e)
          // would (resolve/reject haven't fired yet, so a throw inside the
          // executor rejects it).
          finish(id);
          throw e;
        }
        sock.send(frame);
      });
    },

    observe(next: EngineCallEvents): void {
      events = next ?? {};
    },

    restart(reason: Error): void {
      if (disposed) return;
      connected = false;
      connectPromise = null; // invalidate whether pending or already resolved
      // Settle a still-pending init() FIRST: its only settlement paths are
      // the socket's own onclose/onerror/onmessage closures, which we are
      // about to detach/close below -- without this, restarting mid-boot
      // (the store's Stop button while the greeting hasn't arrived yet)
      // would leave that init() promise permanently unsettled.
      initReject?.(reason);
      rejectAll(reason);
      const old = ws;
      ws = null;
      if (old) {
        // Detach onclose FIRST: this close is deliberate, not unsolicited --
        // without detaching, handleUnsolicitedClose would fire too and
        // double-reject (harmless on an already-empty pending map, but it
        // would also stomp state a caller may have already moved past, e.g.
        // a fresh socket from a subsequent init()).
        old.onclose = null;
        old.close();
      }
    },

    dispose(reason?: Error): void {
      disposed = true;
      connected = false;
      connectPromise = null;
      // Terminal: nothing can arrive on this client again, so drop the
      // journal subscribers too (restart() deliberately keeps them -- see
      // `journalSubs`).
      journalSubs.clear();
      const err = reason ?? new Error('engine client disposed');
      initReject?.(err); // see restart() -- same reasoning, terminal instead
      rejectAll(err);
      const old = ws;
      ws = null;
      if (old) {
        old.onclose = null;
        old.close();
      }
    },
  };
}
