// socketClient.test.ts — node coverage for the native /engine websocket
// client, with the socket MOCKED (no real WebSocket, no server involved).
// Mirrors protocol.test.ts's fake-transport pattern, but the fake speaks
// the wire protocol (frames.ts binary frames + JSON control messages)
// instead of raw postMessage.
import { describe, expect, test, vi } from 'vitest';
import { createSocketEngineClient, type EngineWsLike } from '../../src/lib/worker/socketClient';
import { encodeFrame, decodeFrame } from '../../src/lib/worker/frames';

/**
 * Fake WebSocket: records sends and lets the test drive
 * open/greet/reply/text/close from outside, independent of call order.
 */
function makeFakeWs() {
  const sent: unknown[] = [];
  const ws: EngineWsLike = {
    readyState: 0,
    binaryType: 'arraybuffer',
    send(d) { sent.push(d); },
    close() { this.readyState = 3; this.onclose?.(); },
    onopen: null, onmessage: null, onerror: null, onclose: null,
  };
  const open = () => { ws.readyState = 1; ws.onopen?.(); };
  const greet = () =>
    ws.onmessage?.({ data: JSON.stringify({ type: 'engine_ready', v: 1, pydvma: '2.3.0' }) });
  const reply = (frame: ArrayBuffer) => ws.onmessage?.({ data: frame });
  const text = (obj: unknown) => ws.onmessage?.({ data: JSON.stringify(obj) });
  /** The server (or the network) going away WITHOUT the client asking. */
  const serverClose = () => { ws.readyState = 3; ws.onclose?.(); };
  const serverError = () => ws.onerror?.({});
  return { ws, sent, open, greet, reply, text, serverClose, serverError };
}

/** Wire a client to a fresh fake socket and resolve init() through it. */
async function connected() {
  const f = makeFakeWs();
  const client = createSocketEngineClient('ws://x/engine', () => f.ws);
  const initP = client.init('http://x/', [], '0');
  f.open();
  f.greet();
  await initP;
  return { f, client };
}

/** Pull the request id a call actually sent, by decoding sent[i]. */
function sentId(f: ReturnType<typeof makeFakeWs>, i = 0): number {
  return (decodeFrame(f.sent[i] as ArrayBuffer) as any).id;
}

describe('createSocketEngineClient', () => {
  test('init resolves on greeting; call round-trips a frame by id', async () => {
    const { f, client } = await connected();
    const p = client.call<{ n: number }>('calc_fft', { fs: 8000 });
    const req = decodeFrame(f.sent[0] as ArrayBuffer) as any;
    expect(req.op).toBe('calc_fft');
    f.reply(encodeFrame({ id: req.id, ok: true, result: { n: 1 } }));
    await expect(p).resolves.toEqual({ n: 1 });
  });

  test('two concurrent calls resolve to their own results regardless of completion order', async () => {
    const { f, client } = await connected();
    const p1 = client.call<number>('calc_a');
    const p2 = client.call<number>('calc_b');
    const id1 = sentId(f, 0);
    const id2 = sentId(f, 1);
    expect(id1).not.toBe(id2);

    // Reply out of order: second call first, then first.
    f.reply(encodeFrame({ id: id2, ok: true, result: 222 }));
    f.reply(encodeFrame({ id: id1, ok: true, result: 111 }));

    await expect(p1).resolves.toBe(111);
    await expect(p2).resolves.toBe(222);
  });

  test('progress reaches observers with op resolved; unknown callId ignored; onSettled fires once', async () => {
    const { f, client } = await connected();
    const progress: unknown[] = [];
    const settled: unknown[] = [];
    client.observe?.({
      onProgress: (fr) => progress.push(fr),
      onSettled: (info) => settled.push(info),
    });
    const p = client.call('calc_sono', {});
    const id = sentId(f, 0);

    f.text({ type: 'progress', callId: 999999, done: 1, total: 4 }); // unknown id
    f.text({ type: 'progress', callId: id, done: 1, total: 4 });
    expect(progress).toEqual([{ callId: id, op: 'calc_sono', done: 1, total: 4 }]);

    f.reply(encodeFrame({ id, ok: true, result: 'ok' }));
    await p;
    expect(settled).toEqual([{ callId: id, op: 'calc_sono' }]);
  });

  test('error reply rejects with the error message', async () => {
    const { f, client } = await connected();
    const p = client.call('bad');
    const id = sentId(f, 0);
    f.reply(encodeFrame({ id, ok: false, error: 'boom' }));
    await expect(p).rejects.toThrow('boom');
  });

  test('uncorrelatable server error text frames are dropped but warned', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { f, client } = await connected();
    const p = client.call('a');
    const id = sentId(f, 0);

    f.text({ type: 'error', message: 'undecodable engine frame: bad' });
    expect(warn).toHaveBeenCalled();

    // The stray error frame rejected nothing -- the real reply still resolves it.
    f.reply(encodeFrame({ id, ok: true, result: 'fine' }));
    await expect(p).resolves.toBe('fine');
    warn.mockRestore();
  });

  test('restart closes the socket and rejects in-flight with reason; init reconnects via a fresh socket', async () => {
    const factories: ReturnType<typeof makeFakeWs>[] = [];
    const client = createSocketEngineClient('ws://x/engine', () => {
      const f = makeFakeWs();
      factories.push(f);
      return f.ws;
    });
    const initP = client.init('http://x/', [], '0');
    factories[0].open();
    factories[0].greet();
    await initP;

    const p = client.call('calc_fft', {});
    client.restart(new Error('stopped'));
    await expect(p).rejects.toThrow('stopped');
    expect(factories[0].ws.readyState).toBe(3); // socket actually closed

    const init2 = client.init('http://x/', [], '0');
    expect(factories.length).toBe(2); // factory called again -- fresh socket
    factories[1].open();
    factories[1].greet();
    await expect(init2).resolves.toBeUndefined();
  });

  test('unsolicited close rejects in-flight calls; a later call() rejects not-connected', async () => {
    const { f, client } = await connected();
    const p = client.call('a');
    f.serverClose(); // server/network went away -- NOT client-initiated
    await expect(p).rejects.toThrow(/closed/);
    await expect(client.call('b')).rejects.toThrow(/not connected/);
  });

  test('unsolicited close announces onTransportLost, AFTER settling in-flight calls', async () => {
    // The store maps this to a clear 'engine connection lost' error; without
    // it the app sits at 'ready' over a dead socket and every calc rejects
    // with a bare "engine not connected" until a reload. Order matters: the
    // observer must see a settled world (each rejection's onSettled has
    // already cleared any progress the call was reporting).
    const { f, client } = await connected();
    const order: string[] = [];
    client.observe?.({
      onSettled: () => order.push('settled'),
      onTransportLost: () => order.push('lost'),
    });
    const p = client.call('a');
    f.serverClose();
    await expect(p).rejects.toThrow(/closed/);
    expect(order).toEqual(['settled', 'lost']);
  });

  test('a DELIBERATE restart/dispose does NOT announce onTransportLost', async () => {
    // It is the caller's own doing -- the store is already driving that path
    // (Stop -> restart -> re-boot) and must not also see a transport-lost.
    const a = await connected();
    const lost: string[] = [];
    a.client.observe?.({ onTransportLost: () => lost.push('restart') });
    a.client.restart(new Error('stop'));
    expect(lost).toEqual([]);

    const b = await connected();
    b.client.observe?.({ onTransportLost: () => lost.push('dispose') });
    b.client.dispose();
    expect(lost).toEqual([]);
  });

  test('dispose is terminal: in-flight rejected, socket closed, later init/call reject', async () => {
    const { f, client } = await connected();
    const p = client.call('a');
    client.dispose(new Error('shutting down'));
    await expect(p).rejects.toThrow('shutting down');
    expect(f.ws.readyState).toBe(3);
    await expect(client.call('b')).rejects.toThrow(/disposed/);
    await expect(client.init('http://x/', [], '0')).rejects.toThrow(/disposed/);
  });

  test('typed-array payload values pass through the codec intact', async () => {
    const { f, client } = await connected();
    const time_data = new Float64Array([1, 2, 3.5, -Infinity]);
    const p = client.call('calc_fft', { time_data });
    const req = decodeFrame(f.sent[0] as ArrayBuffer) as any;
    expect(req.payload.time_data).toBeInstanceOf(Float64Array);
    expect(Array.from(req.payload.time_data as Float64Array)).toEqual([1, 2, 3.5, -Infinity]);
    f.reply(encodeFrame({ id: req.id, ok: true, result: null }));
    await p;
  });

  test('init rejects when the socket errors before open', async () => {
    const f = makeFakeWs();
    const client = createSocketEngineClient('ws://x/engine', () => f.ws);
    const initP = client.init('http://x/', [], '0');
    f.serverError();
    await expect(initP).rejects.toThrow();
  });

  test('restart() while init is pending rejects the init promise; a second init() then succeeds', async () => {
    const factories: ReturnType<typeof makeFakeWs>[] = [];
    const client = createSocketEngineClient('ws://x/engine', () => {
      const f = makeFakeWs();
      factories.push(f);
      return f.ws;
    });
    const initP = client.init('http://x/', [], '0'); // no open/greet -- still awaiting the greeting
    client.restart(new Error('stopped mid-boot'));
    await expect(initP).rejects.toThrow('stopped mid-boot');

    // Recovery: a second init() reconnects via a FRESH factory socket.
    const init2 = client.init('http://x/', [], '0');
    expect(factories.length).toBe(2);
    factories[1].open();
    factories[1].greet();
    await expect(init2).resolves.toBeUndefined();
  });

  test('dispose() while init is pending rejects the init promise; later init() rejects (terminal)', async () => {
    const f = makeFakeWs();
    const client = createSocketEngineClient('ws://x/engine', () => f.ws);
    const initP = client.init('http://x/', [], '0'); // still awaiting the greeting
    client.dispose(new Error('shutting down'));
    await expect(initP).rejects.toThrow('shutting down');
    await expect(client.init('http://x/', [], '0')).rejects.toThrow(/disposed/);
  });

  // ---- init() idempotency (Task 8 calls init() twice: probe, then boot) ----

  test('idempotency (a): concurrent double init() shares ONE connection attempt', async () => {
    const factories: ReturnType<typeof makeFakeWs>[] = [];
    const client = createSocketEngineClient('ws://x/engine', () => {
      const f = makeFakeWs();
      factories.push(f);
      return f.ws;
    });
    const p1 = client.init('http://x/', [], '0');
    const p2 = client.init('http://x/', [], '0');
    expect(factories.length).toBe(1); // ONE factory call for both

    factories[0].open();
    factories[0].greet();
    await expect(p1).resolves.toBeUndefined();
    await expect(p2).resolves.toBeUndefined();
  });

  test('idempotency (b): sequential init() after already connected does not open a second socket', async () => {
    let factoryCalls = 0;
    const f = makeFakeWs();
    const client = createSocketEngineClient('ws://x/engine', () => {
      factoryCalls += 1;
      return f.ws;
    });
    const init1 = client.init('http://x/', [], '0');
    f.open();
    f.greet();
    await init1;
    expect(factoryCalls).toBe(1);

    const init2 = client.init('http://x/', [], '0');
    await expect(init2).resolves.toBeUndefined();
    expect(factoryCalls).toBe(1); // still just the one socket
  });

  test('idempotency (c): init() after an unsolicited close reconnects via a fresh socket', async () => {
    const factories: ReturnType<typeof makeFakeWs>[] = [];
    const client = createSocketEngineClient('ws://x/engine', () => {
      const f = makeFakeWs();
      factories.push(f);
      return f.ws;
    });
    const init1 = client.init('http://x/', [], '0');
    factories[0].open();
    factories[0].greet();
    await init1;

    factories[0].serverClose(); // unsolicited -- server/network went away

    const init2 = client.init('http://x/', [], '0');
    expect(factories.length).toBe(2); // fresh socket, not the dead one
    factories[1].open();
    factories[1].greet();
    await expect(init2).resolves.toBeUndefined();
  });

  // ---- greeting deadline ----

  // ---- protocol version gate (Task 10) ----

  test('greeting with an unsupported protocol version rejects init() and closes the socket', async () => {
    const f = makeFakeWs();
    const client = createSocketEngineClient('ws://x/engine', () => f.ws);
    const initP = client.init('http://x/', [], '0');
    f.open();
    f.ws.onmessage?.({ data: JSON.stringify({ type: 'engine_ready', v: 2, pydvma: '2.3.0' }) });
    await expect(initP).rejects.toThrow(/unsupported/);
    expect(f.ws.readyState).toBe(3); // client gave up and closed it
  });

  test('greeting with the supported protocol version (v:1) still resolves init()', async () => {
    // Not a new behaviour -- `connected()`'s helper already greets with v:1
    // and every other test in this file relies on it resolving. This pins
    // it explicitly so the version gate above can never silently start
    // rejecting the happy path too.
    const { client } = await connected();
    expect(client).toBeTruthy();
  });

  test('greeting deadline: init() rejects if the greeting never arrives, and closes the socket', async () => {
    const f = makeFakeWs();
    const client = createSocketEngineClient('ws://x/engine', () => f.ws);
    const initP = client.init('http://x/', [], '0', { greetingTimeoutMs: 5 });
    f.open(); // connects fine, but the peer stays silent (e.g. /ws not /engine)
    await expect(initP).rejects.toThrow(/greeting timed out/);
    expect(f.ws.readyState).toBe(3); // client gave up and closed it
  });

  test('greeting deadline: the timer is cleared on success (no late rejection or close)', async () => {
    vi.useFakeTimers();
    try {
      const f = makeFakeWs();
      const client = createSocketEngineClient('ws://x/engine', () => f.ws);
      const initP = client.init('http://x/', [], '0', { greetingTimeoutMs: 50 });
      f.open();
      f.greet();
      await initP;

      vi.advanceTimersByTime(10_000); // long past the deadline
      expect(f.ws.readyState).toBe(1); // never force-closed
    } finally {
      vi.useRealTimers();
    }
  });

  // ---- send hygiene ----

  test('call() with an unencodable payload rejects and still fires onSettled (no pending-map leak)', async () => {
    const { client } = await connected();
    const settled: Array<{ callId: number; op: string }> = [];
    client.observe?.({ onSettled: (info) => settled.push(info) });
    const bad = new Int32Array([1, 2, 3]);
    await expect(client.call('calc_fft', { time_data: bad } as any)).rejects.toThrow();
    expect(settled).toHaveLength(1);
    expect(settled[0].op).toBe('calc_fft');
  });

  // ---- late-close ordering: a stale socket must never affect its replacement ----

  /** Like makeFakeWs, but close() fires onclose asynchronously (a microtask
   *  later), mirroring how a real WebSocket's close event is never synchronous. */
  function makeDeferredCloseWs() {
    const sent: unknown[] = [];
    const ws: EngineWsLike = {
      readyState: 0,
      binaryType: 'arraybuffer',
      send(d) { sent.push(d); },
      close() {
        this.readyState = 3;
        queueMicrotask(() => this.onclose?.());
      },
      onopen: null, onmessage: null, onerror: null, onclose: null,
    };
    const open = () => { ws.readyState = 1; ws.onopen?.(); };
    const greet = () =>
      ws.onmessage?.({ data: JSON.stringify({ type: 'engine_ready', v: 1, pydvma: '2.3.0' }) });
    return { ws, sent, open, greet };
  }

  test('a stale socket\'s late onclose cannot reject or null out the socket that replaced it', async () => {
    const factories: ReturnType<typeof makeDeferredCloseWs>[] = [];
    const client = createSocketEngineClient('ws://x/engine', () => {
      const f = makeDeferredCloseWs();
      factories.push(f);
      return f.ws;
    });

    const init1 = client.init('http://x/', [], '0');
    factories[0].open();
    factories[0].greet();
    await init1;

    client.restart(new Error('stopped')); // detaches old.onclose, then closes it (deferred)
    const init2 = client.init('http://x/', [], '0'); // pre-greeting -- pending
    expect(factories.length).toBe(2);

    // Flush the deferred onclose microtask from the FIRST (now-stale) socket.
    await Promise.resolve();
    await Promise.resolve();

    // A call right now should fail as "not connected" (init2 hasn't greeted
    // yet) rather than with the stale socket's close error -- proves the
    // late close didn't corrupt state via the new attempt.
    await expect(client.call('x')).rejects.toThrow(/not connected/);

    // The new socket is unaffected: greeting it still resolves init2.
    factories[1].open();
    factories[1].greet();
    await expect(init2).resolves.toBeUndefined();
  });

  // ---- onSettled fires on restart/dispose teardown (the store clears progress off it) ----

  test('onSettled fires for every in-flight call when restart() tears down', async () => {
    const { client } = await connected();
    const settled: Array<{ callId: number; op: string }> = [];
    client.observe?.({ onSettled: (info) => settled.push(info) });
    const p1 = client.call('a');
    const p2 = client.call('b');
    client.restart(new Error('stopped'));
    await Promise.allSettled([p1, p2]);
    expect(settled.map((s) => s.op).sort()).toEqual(['a', 'b']);
  });

  test('onSettled fires for every in-flight call when dispose() tears down', async () => {
    const { client } = await connected();
    const settled: Array<{ callId: number; op: string }> = [];
    client.observe?.({ onSettled: (info) => settled.push(info) });
    const p1 = client.call('a');
    const p2 = client.call('b');
    client.dispose(new Error('bye'));
    await Promise.allSettled([p1, p2]);
    expect(settled.map((s) => s.op).sort()).toEqual(['a', 'b']);
  });

  // ---- unparseable text frames (steady-state and during the greeting wait) ----

  test('unparseable text frames are warned and ignored, in both steady-state and during connect', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

    // Steady state:
    const { f, client } = await connected();
    const p = client.call('a');
    const id = sentId(f, 0);
    f.ws.onmessage?.({ data: '{not json' });
    expect(warn).toHaveBeenCalled();
    f.reply(encodeFrame({ id, ok: true, result: 'fine' }));
    await expect(p).resolves.toBe('fine');

    // During init (pre-greeting):
    warn.mockClear();
    const f2 = makeFakeWs();
    const client2 = createSocketEngineClient('ws://x/engine', () => f2.ws);
    const initP = client2.init('http://x/', [], '0');
    f2.open();
    f2.ws.onmessage?.({ data: '{also not json' });
    expect(warn).toHaveBeenCalled();
    f2.greet();
    await expect(initP).resolves.toBeUndefined();

    warn.mockRestore();
  });
});
