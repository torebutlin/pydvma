// engineProgress.test.ts — long-calc progress routing + Stop (round-11 P7).
//
// Covers the three pieces that make "progress bar after ~3 s, with a stop"
// work, all with the worker MOCKED (no pyodide):
//   1. the CLIENT turning an unsolicited `{type:'progress'}` frame into a
//      labelled event (and dropping frames for settled/unknown ids),
//   2. the STORE routing those into the shared `engineProgress` singleton,
//   3. `stop()` — terminate + reboot — rejecting everything outstanding with
//      a distinguishable `EngineStopped` and coming back up through the normal
//      'loading' lifecycle.
// Plus `longCalcView`, the pure 3 s gate the cards render through.
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { get } from 'svelte/store';
import { createEngineClient, type WorkerLike } from '../../src/lib/worker/client';
import {
  consumeEngineStopNotice,
  createEngineStore,
  ENGINE_STOPPED_MESSAGE,
  EngineStoppedError,
  engineProgress,
  isEngineStopped,
  LONG_CALC_MS,
  longCalcView,
  PROGRESS_LABELS,
  stopEngine,
} from '../../src/lib/stores/engine';

/** Fake worker: records posts, lets the test push replies AND progress frames. */
function makeFakeWorker() {
  const posted: any[] = [];
  const w: WorkerLike = {
    postMessage(m: unknown) { posted.push(m); },
    onmessage: null,
    onerror: null,
    onmessageerror: null,
    terminate: vi.fn(),
  };
  return {
    w,
    posted,
    reply: (r: unknown) => w.onmessage?.({ data: r }),
    progress: (callId: number, done: number, total: number) =>
      w.onmessage?.({ data: { type: 'progress', callId, done, total } }),
  };
}

beforeEach(() => {
  engineProgress.set(null);
  consumeEngineStopNotice();     // clear any pending notice from a prior test
});

// ---- client: progress frames -----------------------------------------------

describe('client: progress frames', () => {
  test('routes a frame to the observer with the op it belongs to', () => {
    const { w, posted, progress } = makeFakeWorker();
    const client = createEngineClient(() => w);
    const seen: any[] = [];
    client.observe({ onProgress: (f) => seen.push(f) });

    client.call('calc_sono', {});
    const id = posted[0].id;
    progress(id, 5, 40);

    expect(seen).toEqual([{ callId: id, op: 'calc_sono', done: 5, total: 40 }]);
  });

  test('a frame for an unknown or already-settled id is dropped', async () => {
    const { w, posted, reply, progress } = makeFakeWorker();
    const client = createEngineClient(() => w);
    const seen: any[] = [];
    client.observe({ onProgress: (f) => seen.push(f) });

    const p = client.call('calc_sono', {});
    const id = posted[0].id;
    reply({ id, ok: true, result: 1 });
    await p;
    progress(id, 9, 10);        // late frame from the worker
    progress(999, 1, 2);        // never-existed id

    expect(seen).toEqual([]);
  });

  test('onSettled fires once per call, on success and on failure', async () => {
    const { w, posted, reply } = makeFakeWorker();
    const client = createEngineClient(() => w);
    const settled: any[] = [];
    client.observe({ onSettled: (s) => settled.push(s) });

    const ok = client.call('calc_sono');
    const bad = client.call('calc_damping');
    const [idOk, idBad] = posted.map((m: any) => m.id);
    reply({ id: idOk, ok: true, result: 1 });
    reply({ id: idBad, ok: false, error: 'boom' });
    await ok;
    await expect(bad).rejects.toThrow(/boom/);

    expect(settled).toEqual([
      { callId: idOk, op: 'calc_sono' },
      { callId: idBad, op: 'calc_damping' },
    ]);
  });

  test('restart rejects in flight with the given reason and keeps the client usable', async () => {
    let made = 0;
    const workers: ReturnType<typeof makeFakeWorker>[] = [];
    const client = createEngineClient(() => {
      const f = makeFakeWorker();
      workers.push(f);
      made += 1;
      return f.w;
    });
    const p = client.call('calc_sono');
    client.restart(new EngineStoppedError());

    await expect(p).rejects.toThrow(/calculation stopped/);
    expect(workers[0].w.terminate).toHaveBeenCalled();
    expect(made).toBe(2);                       // a FRESH worker took its place

    // The replacement is live: a new call posts to it and settles normally.
    const p2 = client.call('calc_fft');
    const id2 = workers[1].posted[0].id;
    workers[1].reply({ id: id2, ok: true, result: 'fine' });
    await expect(p2).resolves.toBe('fine');
  });
});

// ---- store: engineProgress routing -----------------------------------------

/** Store wired to a real client over a fake worker (progress needs both). */
function makeWiredStore() {
  const fakes: ReturnType<typeof makeFakeWorker>[] = [];
  const client = createEngineClient(() => {
    const f = makeFakeWorker();
    fakes.push(f);
    return f.w;
  });
  const store = createEngineStore(client, 'http://x/');
  return { store, fakes, client };
}

/** Boot the store to 'ready' against the fake worker's init reply. */
async function bootReady(s: ReturnType<typeof makeWiredStore>) {
  const boot = s.store.boot();
  s.fakes[0].reply({ id: s.fakes[0].posted[0].id, ok: true, result: null });
  await boot;
  return s;
}

describe('store: engineProgress', () => {
  test('a labelled op raises an entry; later frames keep startedAt', async () => {
    const s = await bootReady(makeWiredStore());
    const f = s.fakes[0];
    s.store.enqueue('calc_sono');
    const id = f.posted[1].id;

    f.progress(id, 1, 40);
    const first = get(engineProgress)!;
    expect(first).toMatchObject({
      callId: id, op: 'calc_sono', label: PROGRESS_LABELS.calc_sono, done: 1, total: 40,
    });

    f.progress(id, 20, 40);
    const second = get(engineProgress)!;
    expect(second.done).toBe(20);
    // The elapsed clock (and so the 3 s gate) measures from the FIRST frame.
    expect(second.startedAt).toBe(first.startedAt);
  });

  test('an unlabelled op is not tracked (no nameless bar)', async () => {
    const s = await bootReady(makeWiredStore());
    const f = s.fakes[0];
    s.store.enqueue('calc_fft');
    f.progress(f.posted[1].id, 1, 10);
    expect(get(engineProgress)).toBeNull();
  });

  test('settling the call clears the entry', async () => {
    const s = await bootReady(makeWiredStore());
    const f = s.fakes[0];
    const p = s.store.enqueue('calc_damping');
    const id = f.posted[1].id;
    f.progress(id, 2, 8);
    expect(get(engineProgress)).not.toBeNull();
    f.reply({ id, ok: true, result: {} });
    await p;
    expect(get(engineProgress)).toBeNull();
  });

  test('a settling call does not clear a NEWER call\'s entry', async () => {
    const s = await bootReady(makeWiredStore());
    const f = s.fakes[0];
    const first = s.store.enqueue('calc_sono');
    const second = s.store.enqueue('calc_damping');
    const [idA, idB] = [f.posted[1].id, f.posted[2].id];
    f.progress(idB, 1, 5);                 // the second call is the live one
    f.reply({ id: idA, ok: true, result: {} });
    await first;
    expect(get(engineProgress)?.callId).toBe(idB);
    f.reply({ id: idB, ok: true, result: {} });
    await second;
    expect(get(engineProgress)).toBeNull();
  });
});

// ---- store: stop() ----------------------------------------------------------

describe('store: stop', () => {
  test('rejects the in-flight call with EngineStopped and reboots to ready', async () => {
    const s = await bootReady(makeWiredStore());
    const inFlight = s.store.enqueue('calc_sono');
    s.fakes[0].progress(s.fakes[0].posted[1].id, 3, 60);

    const stopped = s.store.stop();
    await expect(inFlight).rejects.toThrow(EngineStoppedError);
    await expect(inFlight).rejects.toThrow(ENGINE_STOPPED_MESSAGE);
    expect(get(engineProgress)).toBeNull();
    expect(s.fakes[0].w.terminate).toHaveBeenCalled();

    // A fresh worker is booting: answer its init and the engine is back.
    expect(get(s.store.status)).toBe('loading');
    const fresh = s.fakes[1];
    expect(fresh.posted[0].op).toBe('init');
    fresh.reply({ id: fresh.posted[0].id, ok: true, result: null });
    await stopped;
    expect(get(s.store.status)).toBe('ready');
  });

  test('rejects calls QUEUED behind the boot too (nothing hangs)', async () => {
    const s = makeWiredStore();
    s.store.boot();                       // in flight — status 'loading'
    const queued = s.store.enqueue('calc_sono');
    const waiting = s.store.whenReady();

    const stopped = s.store.stop();
    await expect(queued).rejects.toThrow(EngineStoppedError);
    await expect(waiting).rejects.toThrow(ENGINE_STOPPED_MESSAGE);
    const fresh = s.fakes[1];
    fresh.reply({ id: fresh.posted[0].id, ok: true, result: null });
    await stopped;
    expect(get(s.store.status)).toBe('ready');
  });

  test('work enqueued DURING the reboot queues and drains when ready', async () => {
    const s = await bootReady(makeWiredStore());
    const stopped = s.store.stop();
    const after = s.store.enqueue('calc_fft');
    const fresh = s.fakes[1];
    expect(fresh.posted.length).toBe(1);           // only init so far
    fresh.reply({ id: fresh.posted[0].id, ok: true, result: null });
    await stopped;
    expect(fresh.posted[1].op).toBe('calc_fft');   // drained on ready
    fresh.reply({ id: fresh.posted[1].id, ok: true, result: 'ok' });
    await expect(after).resolves.toBe('ok');
  });

  test('one stop yields ONE notice, however many calls it killed', async () => {
    const s = await bootReady(makeWiredStore());
    const a = s.store.enqueue('calc_sono');
    const b = s.store.enqueue('calc_damping');
    const stopped = s.store.stop();
    await expect(a).rejects.toThrow(EngineStoppedError);
    await expect(b).rejects.toThrow(EngineStoppedError);

    expect(consumeEngineStopNotice()).toBe(true);
    expect(consumeEngineStopNotice()).toBe(false);   // the second caller stays quiet

    s.fakes[1].reply({ id: s.fakes[1].posted[0].id, ok: true, result: null });
    await stopped;
  });

  test('a second Stop during the reboot is the SAME stop, not a second one', async () => {
    // Two Stop buttons exist (Sono card + damping panel) and the reboot takes
    // seconds — a second click must not terminate the replacement worker
    // mid-init and leave two boot paths racing over `status`.
    const s = await bootReady(makeWiredStore());
    s.store.enqueue('calc_sono').catch(() => {});
    const a = s.store.stop();
    const b = s.store.stop();
    expect(b).toBe(a);
    expect(s.fakes.length).toBe(2);            // exactly one replacement worker

    s.fakes[1].reply({ id: s.fakes[1].posted[0].id, ok: true, result: null });
    await Promise.all([a, b]);
    expect(get(s.store.status)).toBe('ready');
  });

  test('a boot killed by a stop does not leave the engine in error', async () => {
    // Stop while the FIRST boot is still in flight: its init rejects with
    // EngineStopped, and that must not be reported as a boot failure —
    // the stop is already booting a replacement.
    const s = makeWiredStore();
    s.store.boot();
    const stopped = s.store.stop();
    s.fakes[1].reply({ id: s.fakes[1].posted[0].id, ok: true, result: null });
    await stopped;
    expect(get(s.store.status)).toBe('ready');
    // And the engine is genuinely usable again.
    const p = s.store.enqueue('calc_fft');
    const call = s.fakes[1].posted[1];
    s.fakes[1].reply({ id: call.id, ok: true, result: 'ok' });
    await expect(p).resolves.toBe('ok');
  });

  test('stopEngine() targets the store that last ran a call', async () => {
    const a = await bootReady(makeWiredStore());
    const b = await bootReady(makeWiredStore());
    const onB = b.store.enqueue('calc_sono');      // b becomes the active engine

    const stopping = stopEngine();
    await expect(onB).rejects.toThrow(EngineStoppedError);
    expect(a.fakes[0].w.terminate).not.toHaveBeenCalled();
    expect(b.fakes[0].w.terminate).toHaveBeenCalled();

    b.fakes[1].reply({ id: b.fakes[1].posted[0].id, ok: true, result: null });
    await stopping;
  });

  test('isEngineStopped recognises the rejection by class and by name', () => {
    expect(isEngineStopped(new EngineStoppedError())).toBe(true);
    expect(isEngineStopped({ name: 'EngineStopped' })).toBe(true);   // structured-clone copy
    expect(isEngineStopped(new Error('calc_sono blew up'))).toBe(false);
    expect(isEngineStopped(null)).toBe(false);
  });
});

// ---- the 3 s gate -----------------------------------------------------------

describe('longCalcView (the ~3 s gate)', () => {
  const entry = (over: Partial<{ done: number; total: number; startedAt: number }> = {}) => ({
    callId: 1, op: 'calc_sono', label: 'sonogram', done: 10, total: 40, startedAt: 1000, ...over,
  });

  test('nothing to show when no calc is reporting', () => {
    expect(longCalcView(null, 999_999)).toBeNull();
  });

  test('stays silent below the threshold', () => {
    expect(longCalcView(entry(), 1000 + LONG_CALC_MS - 1)).toBeNull();
  });

  test('shows fraction, label and elapsed once past it', () => {
    const v = longCalcView(entry(), 1000 + LONG_CALC_MS + 500)!;
    expect(v).toMatchObject({ label: 'sonogram', done: 10, total: 40, fraction: 0.25 });
    expect(v.elapsedS).toBeCloseTo(3.5, 6);
  });

  test('an unknown total reads as 0 %, never NaN', () => {
    expect(longCalcView(entry({ done: 0, total: 0 }), 9999)!.fraction).toBe(0);
  });

  test('fraction is clamped to 0..1', () => {
    expect(longCalcView(entry({ done: 99, total: 40 }), 9999)!.fraction).toBe(1);
    expect(longCalcView(entry({ done: -5, total: 40 }), 9999)!.fraction).toBe(0);
  });

  test('the threshold is overridable (tests / future per-card tuning)', () => {
    expect(longCalcView(entry(), 1500, 100)).not.toBeNull();
  });
});
