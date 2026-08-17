// protocol.test.ts — node coverage for the engine client + store, with the
// worker MOCKED (no pyodide, no real Worker). Proves the request/response
// correlation, error propagation, and the queue-until-ready behaviour that the
// real @engine e2e cannot cheaply exercise per-branch.
import { expect, test, vi } from 'vitest';
import {
  createEngineClient, type EngineCallEvents, type WorkerLike,
} from '../../src/lib/worker/client';
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
    onmessageerror: null,
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

test('worker onmessageerror (deserialization failure) rejects all pending calls', async () => {
  const { w } = makeFakeWorker();
  const client = createEngineClient(() => w);
  const p1 = client.call('a');
  const p2 = client.call('b');
  w.onmessageerror?.({});
  await expect(p1).rejects.toThrow(/deserialization/);
  await expect(p2).rejects.toThrow(/deserialization/);
});

// ---- store: queue-until-ready ----------------------------------------------

/** Fake EngineClient that resolves init on demand and records op calls. */
function makeFakeClient() {
  let resolveInit!: () => void;
  const initPromise = new Promise<void>((r) => { resolveInit = r; });
  const calls: Array<{ op: string; payload?: any }> = [];
  // The store's observer registration, captured so a test can fire lifecycle
  // events (onTransportLost) the way a real transport would.
  let events: EngineCallEvents = {};
  const client = {
    init: vi.fn(() => initPromise),
    call: vi.fn((op: string, payload?: any) => {
      calls.push({ op, payload });
      return Promise.resolve({ op });
    }),
    observe: vi.fn((next: EngineCallEvents) => { events = next ?? {}; }),
    restart: vi.fn(),
    dispose: vi.fn(),
  };
  return { client, calls, finishInit: resolveInit, events: () => events };
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

// ---- store: boot-error must SETTLE queued/awaiting calls (never hang) -------
// These are the I1 regression tests. On the OLD code (queue held bare thunks,
// enqueue/whenReady returned a never-settled promise while not ready, and drain
// only ran on success) both of these would HANG forever — the awaits below
// would time out. The fix rejects queued items + ready-waiters on boot error
// and rejects immediately once status==='error'.

/** Fake client whose init() can be rejected on demand (to drive boot failure). */
function makeRejectableClient() {
  let rejectInit!: (e: unknown) => void;
  const initPromise = new Promise<void>((_res, rej) => { rejectInit = rej; });
  const client = {
    init: vi.fn(() => initPromise),
    call: vi.fn(() => Promise.resolve('ok')),
    dispose: vi.fn(),
  };
  // Swallow the unhandled rejection on the shared init promise (the store
  // catches it; this bare handle would otherwise warn).
  initPromise.catch(() => {});
  return { client, rejectInit };
}

test('store: a call enqueued BEFORE boot error rejects when boot fails', async () => {
  const { client, rejectInit } = makeRejectableClient();
  const store = createEngineStore(client as any, 'http://x/');

  store.boot();                       // in flight, status 'loading'
  const enqueued = store.enqueue('calc_fft');   // parked in the queue
  const waiting = store.whenReady();            // parked ready-waiter
  expect(client.call).not.toHaveBeenCalled();

  rejectInit(new Error('wheel install blew up'));
  await Promise.resolve();            // let boot's catch run
  await Promise.resolve();

  expect(get(store.status)).toBe('error');
  await expect(enqueued).rejects.toThrow(/engine failed to boot: wheel install blew up/);
  await expect(waiting).rejects.toThrow(/engine failed to boot/);
  expect(client.call).not.toHaveBeenCalled();   // never ran after failure
});

test('store: a call enqueued AFTER boot error rejects immediately', async () => {
  const { client, rejectInit } = makeRejectableClient();
  const store = createEngineStore(client as any, 'http://x/');

  store.boot();
  rejectInit(new Error('boot exploded'));
  await Promise.resolve();
  await Promise.resolve();
  expect(get(store.status)).toBe('error');

  // booted===true, so drain never re-runs — these must reject on their own.
  await expect(store.enqueue('calc_fft')).rejects.toThrow(/engine failed to boot: boot exploded/);
  await expect(store.whenReady()).rejects.toThrow(/engine failed to boot/);
});

// ---- store: transport resolution (Task 8) ----------------------------------
// The store's client is LATE-BOUND when a factory is passed: nothing is
// constructed until boot(), and `host` reports which transport answered.
// Passing a client OBJECT keeps the pre-Task-8 semantics exactly.

test('store: a directly-injected client is the browser worker (host pyodide, bound at once)', () => {
  const { client } = makeFakeClient();
  const store = createEngineStore(client as any, 'http://x/');
  expect(get(store.host)).toBe('pyodide');
  expect(store.client).toBe(client);      // bound before boot, as it always was
  expect(client.observe).toHaveBeenCalled();  // observers wired at construction
});

test('store: an async client factory resolves at boot and host reports the transport', async () => {
  const { client, finishInit } = makeFakeClient();
  const store = createEngineStore(
    async () => ({ client: client as any, host: 'native' as const }), 'http://x/');

  // Nothing is constructed until boot(): no client, no host, no init.
  expect(get(store.host)).toBeNull();
  expect(store.client).toBeNull();
  expect(client.init).not.toHaveBeenCalled();

  store.boot();
  finishInit();
  await store.whenReady();

  expect(get(store.status)).toBe('ready');
  expect(get(store.host)).toBe('native');
  expect(store.client).toBe(client);
  // The store still runs its own init on the resolved client (idempotent on
  // the socket client — it hands back the connection the factory opened).
  expect(client.init).toHaveBeenCalledWith('http://x/', expect.any(Array), expect.any(String));
  // Progress observers are wired to the LATE-BOUND client too.
  expect(client.observe).toHaveBeenCalled();
});

test('store: a factory that throws fails boot exactly like a failed init', async () => {
  const store = createEngineStore(
    async () => { throw new Error('no transport'); }, 'http://x/');
  const enqueued = store.enqueue('calc_fft');   // parked in the queue
  const waiting = store.whenReady();            // parked ready-waiter

  await store.boot();

  expect(get(store.status)).toBe('error');
  expect(get(store.host)).toBeNull();           // never resolved
  await expect(enqueued).rejects.toThrow(/engine failed to boot: no transport/);
  await expect(waiting).rejects.toThrow(/engine failed to boot/);
});

// ---- store: transport-lost recovery (Task 8 carry-over 2) ------------------
// A socket can die on its own (pydvma-serve stopped/restarted) — a worker
// cannot. Without this the store stayed 'ready', the app looked healthy, and
// every calc rejected with a bare "engine not connected" until a reload.

test('store: an unsolicited transport loss errors the store with a clear message', async () => {
  const { client, finishInit, events } = makeFakeClient();
  const store = createEngineStore(client as any, 'http://x/');
  store.boot();
  finishInit();
  await store.whenReady();
  expect(get(store.status)).toBe('ready');

  events().onTransportLost!();

  expect(get(store.status)).toBe('error');
  await expect(store.enqueue('calc_fft')).rejects.toThrow(/engine connection lost/);
  await expect(store.whenReady()).rejects.toThrow(/engine connection lost/);
});

test('store: a transport loss DURING boot settles the queue and does not later go ready', async () => {
  const { client, finishInit, events } = makeFakeClient();
  const store = createEngineStore(client as any, 'http://x/');
  store.boot();                                   // 'loading', init in flight
  const queued = store.enqueue('calc_fft');

  events().onTransportLost!();                    // socket dies mid-boot
  expect(get(store.status)).toBe('error');
  await expect(queued).rejects.toThrow(/engine connection lost/);

  // The superseded boot must NOT resurrect 'ready' when its init resolves.
  finishInit();
  await Promise.resolve();
  await Promise.resolve();
  expect(get(store.status)).toBe('error');
});

test('store: after a transport loss an explicit re-boot recovers', async () => {
  const { client, finishInit, events } = makeFakeClient();
  const store = createEngineStore(client as any, 'http://x/');
  store.boot();
  finishInit();
  await store.whenReady();
  events().onTransportLost!();
  expect(get(store.status)).toBe('error');

  // `booted` was reset, so boot() genuinely runs again (the socket client's
  // init reconnects — its connectPromise was cleared by the same close).
  await store.boot();
  expect(get(store.status)).toBe('ready');
  expect(client.init).toHaveBeenCalledTimes(2);
  await expect(store.enqueue('calc_fft')).resolves.toEqual({ op: 'calc_fft' });
});

test('store: a transport loss does NOT re-run the factory — the session keeps its host', async () => {
  // The client is kept deliberately: re-resolving would let a session that
  // chose the native host slide silently onto the browser engine mid-run
  // (different memory ceiling, different speed, same-looking answers).
  const { client, finishInit, events } = makeFakeClient();
  let factoryCalls = 0;
  const store = createEngineStore(async () => {
    factoryCalls += 1;
    return { client: client as any, host: 'native' as const };
  }, 'http://x/');

  store.boot();
  finishInit();
  await store.whenReady();
  expect(factoryCalls).toBe(1);
  expect(get(store.host)).toBe('native');

  events().onTransportLost!();
  expect(get(store.status)).toBe('error');

  await store.boot();
  expect(factoryCalls).toBe(1);            // resolved once, for the session
  expect(get(store.host)).toBe('native');  // ...and still reported as native
  expect(get(store.status)).toBe('ready');
});

test('store: a stop during a factory-in-flight boot disposes the superseded client', async () => {
  // stop() cannot CANCEL a factory already in flight — it supersedes it and
  // starts a second one. Both eventually resolve a client; exactly one may
  // survive. Left undisposed, the loser would be a live socket, i.e. an
  // orphaned worker subprocess on the server for the rest of the session.
  const made: Array<ReturnType<typeof makeFakeClient>> = [];
  const gates: Array<() => void> = [];
  const store = createEngineStore(() => {
    const f = makeFakeClient();
    made.push(f);
    return new Promise<any>((resolve) => {
      gates.push(() => resolve({ client: f.client as any, host: 'native' as const }));
    });
  }, 'http://x/');

  store.boot();                       // factory #1 called, still in flight
  expect(made.length).toBe(1);
  const stopped = store.stop();       // supersedes it, starts factory #2
  expect(made.length).toBe(2);

  gates[0]();                         // the SUPERSEDED factory finally answers
  gates[1]();
  made[1].finishInit();
  await stopped;

  expect(made[0].client.dispose).toHaveBeenCalled();   // loser released
  expect(made[0].client.init).not.toHaveBeenCalled();  // never used at all
  expect(made[1].client.dispose).not.toHaveBeenCalled();
  expect(store.client).toBe(made[1].client);           // exactly one live client
  expect(get(store.status)).toBe('ready');
  expect(get(store.host)).toBe('native');
});
