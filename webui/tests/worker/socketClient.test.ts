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
});
