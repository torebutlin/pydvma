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

interface Pending { op: string; resolve: (v: any) => void; reject: (e: any) => void }

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
): EngineClient {
  const pending = new Map<number, Pending>();
  let nextId = 1;
  let ws: EngineWsLike | null = null;
  let connected = false;
  let disposed = false;
  let events: EngineCallEvents = {};

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
  }

  /** Steady-state onclose: the server (or network) went away unasked. */
  function handleUnsolicitedClose() {
    connected = false;
    ws = null;
    rejectAll(new Error('native engine connection closed'));
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
      console.warn('engine socket: undecodable frame', e);
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
    } catch {
      return;
    }
    if (msg?.type === 'progress') {
      const entry = pending.get(msg.callId);
      if (entry) {
        events.onProgress?.({ callId: msg.callId, op: entry.op, done: msg.done, total: msg.total });
      }
      return; // unknown/settled callId -- ignore silently
    }
    if (msg?.type === 'error') {
      // The server couldn't decode an inbound frame at all, so it carries no
      // id to correlate -- nothing in `pending` can be resolved/rejected
      // from this alone. Surface it for diagnosis and otherwise ignore.
      console.warn('engine socket: server error', msg.message);
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
    console.warn('engine socket: unexpected message data type', data);
  }

  return {
    // baseUrl/wheels/pyodideVersion are pyodide-worker concerns (vendored
    // engine assets + wheel install) -- meaningless for a CPython host over
    // a socket, so they're accepted (to satisfy the EngineClient shape) and
    // ignored.
    init(_baseUrl?: string, _wheels?: string[], _pyodideVersion?: string): Promise<void> {
      if (disposed) return Promise.reject(new Error('engine client disposed'));
      return new Promise<void>((resolve, reject) => {
        const sock = wsFactory(url);
        sock.binaryType = 'arraybuffer';
        ws = sock;
        let settled = false;

        sock.onerror = () => {
          if (settled) return;
          settled = true;
          reject(new Error('native engine connect failed'));
        };
        sock.onclose = () => {
          if (settled) return;
          settled = true;
          reject(new Error('native engine connection closed before greeting'));
        };
        sock.onmessage = (e: { data: unknown }) => {
          if (typeof e.data !== 'string') return; // the greeting is always text
          let msg: any;
          try {
            msg = JSON.parse(e.data);
          } catch {
            return;
          }
          if (msg?.type !== 'engine_ready') return;
          // Task 10: version gate lands here (compare msg.v against the
          // client's expected ENGINE_PROTOCOL_VERSION and reject on mismatch).
          settled = true;
          connected = true;
          // Steady-state handlers take over only now that init is done.
          sock.onmessage = (ev: { data: unknown }) => handleMessage(ev.data);
          sock.onclose = () => handleUnsolicitedClose();
          resolve();
        };
        sock.onopen = () => { /* wait for the engine_ready greeting */ };
      });
    },

    call<T = unknown>(op: string, payload: Record<string, unknown> = {}): Promise<T> {
      if (disposed) return Promise.reject(new Error('engine client disposed'));
      if (!connected || !ws) return Promise.reject(new Error('engine not connected'));
      const id = nextId++;
      const sock = ws;
      return new Promise<T>((resolve, reject) => {
        pending.set(id, { op, resolve, reject });
        sock.send(encodeFrame({ id, op, payload: payload ?? {} }));
      });
    },

    observe(next: EngineCallEvents): void {
      events = next ?? {};
    },

    restart(reason: Error): void {
      if (disposed) return;
      connected = false;
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
      rejectAll(reason ?? new Error('engine client disposed'));
      const old = ws;
      ws = null;
      if (old) {
        old.onclose = null;
        old.close();
      }
    },
  };
}
