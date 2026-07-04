// protocol.test.ts — node coverage for the engine client + store, with the
// worker MOCKED (no pyodide, no real Worker). Proves the request/response
// correlation, error propagation, and the queue-until-ready behaviour that the
// real @engine e2e cannot cheaply exercise per-branch.
import { expect, test, vi } from 'vitest';
import { createEngineClient, type WorkerLike } from '../../src/lib/worker/client';
import { createEngineStore } from '../../src/lib/stores/engine';
import { get } from 'svelte/store';

/**
 * Fake worker: records posted messages and lets the test reply on demand,
 * so completion order can be controlled independently of call order.
 */
function makeFakeWorker() {
  const posted: any[] = [];
  const w: WorkerLike = {
    postMessage(m: unknown) { posted.push(m); },
    onmessage: null,
    onerror: null,
    terminate: vi.fn(),
  };
  const reply = (r: unknown) => w.onmessage?.({ data: r });
  return { w, posted, reply };
}

test('concurrent calls resolve to their own results (id matching)', async () => {
  const { w, posted, reply } = makeFakeWorker();
  const client = createEngineClient(() => w);

  const p1 = client.call<number>('calc_a');
  const p2 = client.call<number>('calc_b');
  expect(posted.map((m) => m.op)).toEqual(['calc_a', 'calc_b']);
  const [id1, id2] = posted.map((m) => m.id);
  expect(id1).not.toBe(id2);

  // Reply out of order: second call first, then first.
  reply({ id: id2, ok: true, result: 222 });
  reply({ id: id1, ok: true, result: 111 });

  await expect(p1).resolves.toBe(111);
  await expect(p2).resolves.toBe(222);
});

test('error reply rejects only its own call', async () => {
  const { w, posted, reply } = makeFakeWorker();
  const client = createEngineClient(() => w);

  const pOk = client.call('good');
  const pErr = client.call('bad');
  const [idOk, idErr] = posted.map((m) => m.id);

  reply({ id: idErr, ok: false, error: 'boom' });
  reply({ id: idOk, ok: true, result: 'fine' });

  await expect(pErr).rejects.toThrow(/boom/);
  await expect(pOk).resolves.toBe('fine');
});

test('worker onerror rejects all pending calls', async () => {
  const { w } = makeFakeWorker();
  const client = createEngineClient(() => w);
  const p1 = client.call('a');
  const p2 = client.call('b');
  w.onerror?.({ message: 'crashed' });
  await expect(p1).rejects.toThrow(/crashed/);
  await expect(p2).rejects.toThrow(/crashed/);
});

test('dispose terminates worker and rejects in-flight calls', async () => {
  const { w } = makeFakeWorker();
  const client = createEngineClient(() => w);
  const p = client.call('a');
  client.dispose();
  await expect(p).rejects.toThrow(/disposed/);
  expect(w.terminate).toHaveBeenCalled();
  await expect(client.call('b')).rejects.toThrow(/disposed/);
});

test('unknown reply id is ignored (no throw)', () => {
  const { w, reply } = makeFakeWorker();
  createEngineClient(() => w);
  expect(() => reply({ id: 999, ok: true, result: 1 })).not.toThrow();
});

// ---- store: queue-until-ready ----------------------------------------------

/** Fake EngineClient that resolves init on demand and records op calls. */
function makeFakeClient() {
  let resolveInit!: () => void;
  const initPromise = new Promise<void>((r) => { resolveInit = r; });
  const calls: Array<{ op: string; payload?: any }> = [];
  const client = {
    init: vi.fn(() => initPromise),
    call: vi.fn((op: string, payload?: any) => {
      calls.push({ op, payload });
      return Promise.resolve({ op });
    }),
    dispose: vi.fn(),
  };
  return { client, calls, finishInit: resolveInit };
}

test('store: calls before ready are queued and drained in FIFO order on ready', async () => {
  const { client, calls, finishInit } = makeFakeClient();
  const store = createEngineStore(client as any, 'http://x/');

  expect(get(store.status)).toBe('idle');
  store.boot(); // do NOT await — boot is in flight
  expect(get(store.status)).toBe('loading');

  // Enqueue two ops while loading — neither should reach the client yet.
  const e1 = store.enqueue('first');
  const e2 = store.enqueue('second');
  expect(client.call).not.toHaveBeenCalled();

  // Finish boot -> ready -> queue drains in order.
  finishInit();
  await Promise.resolve(); // let init().then run
  await Promise.resolve();
  await Promise.all([e1, e2]);

  expect(get(store.status)).toBe('ready');
  expect(calls.map((c) => c.op)).toEqual(['first', 'second']);
});

test('store: whenReady resolves after boot completes', async () => {
  const { client, finishInit } = makeFakeClient();
  const store = createEngineStore(client as any, 'http://x/');
  let resolved = false;
  const wr = store.whenReady().then(() => { resolved = true; });
  store.boot();
  expect(resolved).toBe(false);
  finishInit();
  await Promise.resolve();
  await Promise.resolve();
  await wr;
  expect(resolved).toBe(true);
});

test('store: after ready, enqueue calls the client immediately', async () => {
  const { client, finishInit } = makeFakeClient();
  const store = createEngineStore(client as any, 'http://x/');
  store.boot();
  finishInit();
  await store.whenReady();
  await store.enqueue('calc_fft', { fs: 1000 });
  expect(client.call).toHaveBeenCalledWith('calc_fft', { fs: 1000 });
});

test('store: init failure sets status to error', async () => {
  const client = {
    init: vi.fn(() => Promise.reject(new Error('boot failed'))),
    call: vi.fn(),
    dispose: vi.fn(),
  };
  const store = createEngineStore(client as any, 'http://x/');
  await store.boot();
  expect(get(store.status)).toBe('error');
});
