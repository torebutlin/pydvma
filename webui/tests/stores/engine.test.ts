// engine.test.ts — the store-level surface added by the Task 10 review
// follow-ups: `hostNote` (a one-time user-facing notice from factory
// resolution) and `pydvmaVersion` (the native host's greeted pydvma
// release), plus the pure helpers behind the version-skew warning.
//
// The worker/client transport itself is mocked with a minimal fake — this
// file cares about what `createEngineStore`'s `boot()` does with a resolved
// `ResolvedEngine`, not about a real Worker or socket.
import { describe, expect, test, vi } from 'vitest';
import { get } from 'svelte/store';
import {
  createEngineStore,
  ENGINE_WHEELS,
  journalAvailable,
  journalDiscardRecovered,
  journalGet,
  journalSet,
  onJournalUpdate,
  pydvmaVersionFromWheelFilename,
  warnOnPydvmaVersionMismatch,
} from '../../src/lib/stores/engine';
import type { EngineClient } from '../../src/lib/worker/client';
import type { ResolvedEngine } from '../../src/lib/worker/selectEngine';

function fakeClient(): EngineClient {
  return {
    init: vi.fn().mockResolvedValue(undefined),
    call: vi.fn(),
    observe: vi.fn(),
    restart: vi.fn(),
    dispose: vi.fn(),
  };
}

describe('pydvmaVersionFromWheelFilename', () => {
  test('parses the version out of a standard wheel filename', () => {
    expect(pydvmaVersionFromWheelFilename('pydvma-2.3.0-py3-none-any.whl')).toBe('2.3.0');
  });

  test('null for a filename that does not match the expected shape', () => {
    expect(pydvmaVersionFromWheelFilename('PeakUtils-1.3.5-py3-none-any.whl')).toBeNull();
    expect(pydvmaVersionFromWheelFilename('not-a-wheel-at-all')).toBeNull();
  });
});

describe('warnOnPydvmaVersionMismatch', () => {
  test('warns when the native release differs from ENGINE_WHEELS[0]', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    warnOnPydvmaVersionMismatch('9.9.9');
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain('9.9.9');
    warn.mockRestore();
  });

  test('no warning when the native release matches ENGINE_WHEELS[0]', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const matching = pydvmaVersionFromWheelFilename(ENGINE_WHEELS[0]);
    warnOnPydvmaVersionMismatch(matching);
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  test('no-op for a null/undefined actual version (unknown, nothing to compare)', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    warnOnPydvmaVersionMismatch(null);
    warnOnPydvmaVersionMismatch(undefined);
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe('createEngineStore: hostNote / pydvmaVersion surfaced from factory resolution', () => {
  test('a resolved pydvmaVersion is exposed as a readable; no note when none was set', async () => {
    const resolved: ResolvedEngine = { client: fakeClient(), host: 'native', pydvmaVersion: '2.3.0' };
    const store = createEngineStore(async () => resolved);
    await store.boot();
    expect(get(store.host)).toBe('native');
    expect(get(store.pydvmaVersion)).toBe('2.3.0');
    expect(get(store.hostNote)).toBeNull();
  });

  test('a resolved note (the silent-fallback case) is exposed via hostNote', async () => {
    const note = 'native engine unavailable — using browser engine (see console)';
    const resolved: ResolvedEngine = { client: fakeClient(), host: 'pyodide', note };
    const store = createEngineStore(async () => resolved);
    await store.boot();
    expect(get(store.host)).toBe('pyodide');
    expect(get(store.hostNote)).toBe(note);
  });

  test('boot() warns on a native pydvmaVersion mismatch, exactly once', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const resolved: ResolvedEngine = { client: fakeClient(), host: 'native', pydvmaVersion: '9.9.9' };
    const store = createEngineStore(async () => resolved);
    await store.boot();
    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });

  test('boot() does NOT warn on a native pydvmaVersion match', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const matching = pydvmaVersionFromWheelFilename(ENGINE_WHEELS[0])!;
    const resolved: ResolvedEngine = { client: fakeClient(), host: 'native', pydvmaVersion: matching };
    const store = createEngineStore(async () => resolved);
    await store.boot();
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  test('a pyodide resolution never triggers the version-mismatch warn, even with pydvmaVersion unset', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const resolved: ResolvedEngine = { client: fakeClient(), host: 'pyodide' };
    const store = createEngineStore(async () => resolved);
    await store.boot();
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  test('a directly-injected client (no factory) never sets hostNote/pydvmaVersion', () => {
    // Every pre-Task-10 caller and most tests take this path -- host reads
    // 'pyodide' immediately (see createEngineStore's own docstring) and the
    // factory branch inside boot() never runs at all.
    const store = createEngineStore(fakeClient());
    expect(get(store.host)).toBe('pyodide');
    expect(get(store.hostNote)).toBeNull();
    expect(get(store.pydvmaVersion)).toBeNull();
  });
});

describe('session journal helpers (native-engine stage 3)', () => {
  /**
   * A fake native client that also speaks the journal surface. `call`
   * records every op and answers `journal_get` with `reply`.
   */
  function fakeJournalClient(reply: Record<string, unknown> = {}) {
    const calls: Array<{ op: string; payload?: Record<string, unknown> }> = [];
    const subs = new Set<() => void>();
    const client: EngineClient = {
      init: vi.fn().mockResolvedValue(undefined),
      call: vi.fn(async (op: string, payload?: Record<string, unknown>) => {
        calls.push({ op, payload });
        return op === 'journal_get' ? reply : {};
      }) as EngineClient['call'],
      observe: vi.fn(),
      restart: vi.fn(),
      dispose: vi.fn(),
      onJournalUpdate: (cb: () => void) => {
        subs.add(cb);
        return () => { subs.delete(cb); };
      },
    };
    return { client, calls, push: () => { for (const cb of subs) cb(); } };
  }

  /** Boot a store on a native+journal resolution and hand back the fake. */
  async function bootWithJournal(reply: Record<string, unknown> = {}) {
    const f = fakeJournalClient(reply);
    const resolved: ResolvedEngine = { client: f.client, host: 'native', journal: true };
    const store = createEngineStore(async () => resolved);
    await store.boot();
    return f;
  }

  /** Park the module-level journal handle back on "nothing available". */
  async function clearJournalClient(): Promise<void> {
    const resolved: ResolvedEngine = { client: fakeClient(), host: 'pyodide' };
    await createEngineStore(async () => resolved).boot();
  }

  test('journalAvailable() is false on pyodide, false without the capability, true on native+journal', async () => {
    await createEngineStore(async () => (
      { client: fakeClient(), host: 'pyodide' } as ResolvedEngine)).boot();
    expect(journalAvailable()).toBe(false);

    // Native but the greeting never advertised a journal (a serve predating
    // stage 3) -- the whole point of gating on the capability, not the host.
    await createEngineStore(async () => (
      { client: fakeClient(), host: 'native', journal: false } as ResolvedEngine)).boot();
    expect(journalAvailable()).toBe(false);

    await bootWithJournal();
    expect(journalAvailable()).toBe(true);
    await clearJournalClient();
  });

  test('journalAvailable() is false before any boot has resolved a client', async () => {
    await clearJournalClient();          // known-null starting point
    const store = createEngineStore(async () => (
      { client: fakeClient(), host: 'native', journal: true } as ResolvedEngine));
    expect(journalAvailable()).toBe(false);
    await store.boot();
    expect(journalAvailable()).toBe(true);
    await clearJournalClient();
  });

  test('journalSet posts the doc bytes through the active client', async () => {
    const f = await bootWithJournal();
    const doc = new Uint8Array([1, 2, 3]);
    await journalSet(doc);
    expect(f.calls).toEqual([{ op: 'journal_set', payload: { doc } }]);
    await clearJournalClient();
  });

  test('journalGet normalises the wire result to Uint8Array / null', async () => {
    const f = await bootWithJournal({
      doc: new Uint8Array([7]),
      captures: [new Uint8Array([8]).buffer, new Uint8Array([9])],
      recovered: null,
    });
    const state = await journalGet();
    expect(f.calls[0].op).toBe('journal_get');
    expect(state.doc).toBeInstanceOf(Uint8Array);
    expect([...state.doc!]).toEqual([7]);
    expect(state.captures).toHaveLength(2);
    expect(state.captures.every((c) => c instanceof Uint8Array)).toBe(true);
    expect([...state.captures[0]]).toEqual([8]);
    expect(state.recovered).toBeNull();
    await clearJournalClient();
  });

  test('journalGet on an empty journal yields nulls and an empty capture list', async () => {
    await bootWithJournal({ doc: null, captures: [], recovered: null });
    await expect(journalGet()).resolves.toEqual({ doc: null, captures: [], recovered: null });
    await clearJournalClient();
  });

  test('journalDiscardRecovered sends the discard op', async () => {
    const f = await bootWithJournal();
    await journalDiscardRecovered();
    expect(f.calls[0].op).toBe('journal_discard_recovered');
    await clearJournalClient();
  });

  test('every journal call rejects (never silently no-ops) when no journal is available', async () => {
    await clearJournalClient();
    await expect(journalSet(new Uint8Array([1]))).rejects.toThrow(/no session journal/);
    await expect(journalGet()).rejects.toThrow(/no session journal/);
    await expect(journalDiscardRecovered()).rejects.toThrow(/no session journal/);
  });

  test('onJournalUpdate forwards the client\'s push frames, and unsubscribes', async () => {
    const f = await bootWithJournal();
    let hits = 0;
    const unsub = onJournalUpdate(() => { hits += 1; });
    f.push();
    expect(hits).toBe(1);
    unsub();
    f.push();
    expect(hits).toBe(1);
    await clearJournalClient();
  });

  test('onJournalUpdate is a safe no-op (with a callable unsubscribe) with no journal', async () => {
    await clearJournalClient();
    const unsub = onJournalUpdate(() => { throw new Error('must never fire'); });
    expect(() => unsub()).not.toThrow();
  });
});
