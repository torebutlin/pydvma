import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import {
  autosave,
  cancelAutosave,
  clearAutosave,
  journalPost,
  restoreOffer,
  setJournalOverflowNotice,
  setJournalSink,
  JOURNAL_SINK_MAX_BYTES,
  __setIdb,
  __setJournalSinkMaxBytes,
  __resetJournalOverflowNotice,
} from '../../src/lib/files/autosave';
import type { WorkDir } from '../../src/lib/files/workdir';

/** A fake in-memory idb so restoreOffer/clearAutosave are deterministic. */
function makeFakeIdb() {
  const store = new Map<string, Uint8Array>();
  return {
    store,
    get: vi.fn(async (k: string) => store.get(k)),
    set: vi.fn(async (k: string, v: Uint8Array) => void store.set(k, v)),
    del: vi.fn(async (k: string) => void store.delete(k)),
  };
}

/** A fake fsaccess WorkDir whose save() we can spy on. */
function fakeFsDir(): WorkDir & { save: ReturnType<typeof vi.fn> } {
  return {
    kind: 'fsaccess',
    name: 'folder',
    save: vi.fn(async () => {}),
    open: vi.fn(async () => null),
  } as WorkDir & { save: ReturnType<typeof vi.fn> };
}

let idb: ReturnType<typeof makeFakeIdb>;

beforeEach(() => {
  vi.useFakeTimers();
  idb = makeFakeIdb();
  __setIdb(idb);
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  setJournalSink(null); // guard: a leaked sink from a failing test must not poison later ones
  setJournalOverflowNotice(null);
  __setJournalSinkMaxBytes(JOURNAL_SINK_MAX_BYTES); // and a shrunk limit must not leak either
  __resetJournalOverflowNotice();                   // the notice is ONE-SHOT per session
});

describe('autosave debounce', () => {
  test('rapid calls collapse to ONE write after 2s, serializing the thunk once', async () => {
    const dir = fakeFsDir();
    // The thunk is the (expensive) writeDvma serialize; it MUST run exactly
    // once — when the debounce fires — no matter how many times we schedule.
    const marker = new Uint8Array([0x42]);
    const thunk = vi.fn(() => marker);
    for (let i = 0; i < 5; i++) autosave(thunk, dir, true);
    expect(thunk).not.toHaveBeenCalled(); // deferred — no serialize yet
    expect(dir.save).not.toHaveBeenCalled(); // debounced — nothing yet
    await vi.advanceTimersByTimeAsync(1999);
    expect(dir.save).not.toHaveBeenCalled(); // still before the 2s boundary
    expect(thunk).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(thunk).toHaveBeenCalledTimes(1); // N schedules → ONE serialize
    expect(dir.save).toHaveBeenCalledTimes(1); // exactly one write
    expect(dir.save).toHaveBeenCalledWith('autosave.dvma', marker);
  });

  test('the LATEST thunk wins when different thunks are scheduled', async () => {
    const dir = fakeFsDir();
    const stale = vi.fn(() => new Uint8Array([1]));
    const fresh = vi.fn(() => new Uint8Array([2]));
    autosave(stale, dir, true);
    autosave(fresh, dir, true); // supersedes the pending stale thunk
    await vi.advanceTimersByTimeAsync(2000);
    expect(stale).not.toHaveBeenCalled(); // never serialized — it was superseded
    expect(fresh).toHaveBeenCalledTimes(1);
    expect(dir.save).toHaveBeenCalledWith('autosave.dvma', new Uint8Array([2]));
  });

  test('download-kind dir writes to idb, not dir.save', async () => {
    const dir = { kind: 'download', name: 'Downloads', save: vi.fn(async () => {}), open: vi.fn() } as unknown as WorkDir & { save: ReturnType<typeof vi.fn> };
    autosave(new Uint8Array([7, 7]), dir, true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(dir.save).not.toHaveBeenCalled();
    expect(idb.set).toHaveBeenCalledTimes(1);
    // Round-trips through restoreOffer.
    expect(await restoreOffer()).toEqual(new Uint8Array([7, 7]));
  });

  test('disabled → no write anywhere', async () => {
    const dir = fakeFsDir();
    autosave(new Uint8Array([1]), dir, false);
    await vi.advanceTimersByTimeAsync(5000);
    expect(dir.save).not.toHaveBeenCalled();
    expect(idb.set).not.toHaveBeenCalled();
  });

  test('cancelAutosave() drops a pending write (toggle-off after a mutation)', async () => {
    const dir = fakeFsDir();
    // A mutation scheduled a write; the user toggles autosave off before 2 s.
    autosave(new Uint8Array([1]), dir, true);
    await vi.advanceTimersByTimeAsync(1000); // partway through the debounce
    cancelAutosave(); // toggle-off cancels the in-flight write
    await vi.advanceTimersByTimeAsync(5000); // well past when it would have fired
    expect(dir.save).not.toHaveBeenCalled();
    expect(idb.set).not.toHaveBeenCalled();
  });

  test('autosave(..., false) also cancels a pending write (equivalent to cancelAutosave)', async () => {
    const dir = fakeFsDir();
    autosave(new Uint8Array([1]), dir, true);
    await vi.advanceTimersByTimeAsync(1000);
    autosave(new Uint8Array([2]), dir, false); // disable path clears the timer
    await vi.advanceTimersByTimeAsync(5000);
    expect(dir.save).not.toHaveBeenCalled();
    expect(idb.set).not.toHaveBeenCalled();
  });

  test('cancelAutosave() is a no-op when nothing is pending', () => {
    expect(() => cancelAutosave()).not.toThrow();
  });

  test('a fresh call restarts the timer (clearTimeout guard)', async () => {
    const dir = fakeFsDir();
    autosave(new Uint8Array([1]), dir, true);
    await vi.advanceTimersByTimeAsync(1500); // partway through the window
    autosave(new Uint8Array([2]), dir, true); // resets the 2s countdown
    await vi.advanceTimersByTimeAsync(1500); // 3s total, but only 1.5s since reset
    expect(dir.save).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(500); // now 2s since the reset
    expect(dir.save).toHaveBeenCalledTimes(1);
    expect(dir.save).toHaveBeenCalledWith('autosave.dvma', new Uint8Array([2]));
  });
});

describe('restoreOffer / clearAutosave', () => {
  test('restoreOffer returns null when nothing saved', async () => {
    expect(await restoreOffer()).toBeNull();
  });

  test('clearAutosave deletes the idb key', async () => {
    idb.store.set('pydvma:autosave', new Uint8Array([9]));
    await clearAutosave();
    expect(idb.del).toHaveBeenCalledWith('pydvma:autosave');
    expect(await restoreOffer()).toBeNull();
  });
});

describe('journal sink', () => {
  test('persist() also posts to a registered journal sink', async () => {
    const posted: Uint8Array[] = [];
    setJournalSink((b) => posted.push(b));
    autosave(() => new Uint8Array([1, 2, 3]), null, true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(posted).toHaveLength(1);
    expect([...posted[0]]).toEqual([1, 2, 3]);
  });

  test('sink errors never break the idb write', async () => {
    setJournalSink(() => {
      throw new Error('socket gone');
    });
    autosave(() => new Uint8Array([9]), null, true);
    await vi.advanceTimersByTimeAsync(2000);
    // The throwing sink must not stop the idb write from landing.
    expect(idb.set).toHaveBeenCalledTimes(1);
    expect(idb.store.get('pydvma:autosave')).toEqual(new Uint8Array([9]));
  });

  test('an async sink whose promise rejects never breaks the idb write', async () => {
    setJournalSink(async () => {
      throw new Error('socket gone mid-await');
    });
    autosave(() => new Uint8Array([11]), null, true);
    // advanceTimersByTimeAsync flushes microtasks between ticks, so the
    // rejected promise's .catch() has already settled by the time this
    // resolves — a real unhandled rejection would fail the test/process,
    // so a clean pass here doubles as proof there isn't one.
    await vi.advanceTimersByTimeAsync(2000);
    expect(idb.set).toHaveBeenCalledTimes(1);
    expect(idb.store.get('pydvma:autosave')).toEqual(new Uint8Array([11]));
  });

  test('no sink registered leaves behaviour unchanged', async () => {
    autosave(() => new Uint8Array([7]), null, true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(idb.set).toHaveBeenCalledTimes(1);
    expect(idb.store.get('pydvma:autosave')).toEqual(new Uint8Array([7]));
  });

  test('sink also fires for the fsaccess-dir branch', async () => {
    const dir = fakeFsDir();
    const posted: Uint8Array[] = [];
    setJournalSink((b) => posted.push(b));
    const marker = new Uint8Array([5, 6]);
    autosave(marker, dir, true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(dir.save).toHaveBeenCalledWith('autosave.dvma', marker);
    expect(posted).toHaveLength(1);
    expect([...posted[0]]).toEqual([5, 6]);
  });

  test('an over-limit session skips the sink but still autosaves locally', async () => {
    // serve caps an inbound /engine frame at 256 MiB and CLOSES the socket
    // (1009) on anything bigger — which the app reports as "engine connection
    // lost", re-boots, and hits again on the next autosave. So an over-limit
    // document must never be posted. Limit shrunk for the test; the real one
    // is 192 MiB and cannot be allocated here.
    __setJournalSinkMaxBytes(8);
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const posted: Uint8Array[] = [];
    setJournalSink((b) => posted.push(b));
    const big = new Uint8Array(9);
    autosave(big, null, true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(posted).toHaveLength(0); // sink skipped
    expect(idb.set).toHaveBeenCalledTimes(1); // local autosave unaffected
    expect(idb.store.get('pydvma:autosave')).toEqual(big);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain('too large for the serve journal');
    expect(String(warn.mock.calls[0][0])).toContain('local autosave only');
    warn.mockRestore();
  });

  test('a payload exactly at the limit still posts', async () => {
    __setJournalSinkMaxBytes(8);
    const posted: Uint8Array[] = [];
    setJournalSink((b) => posted.push(b));
    autosave(new Uint8Array(8), null, true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(posted).toHaveLength(1);
  });

  test('the default limit sits under serve’s 256 MiB frame cap', () => {
    expect(JOURNAL_SINK_MAX_BYTES).toBe(192 * 1024 * 1024);
    expect(JOURNAL_SINK_MAX_BYTES).toBeLessThan(256 * 1024 * 1024);
  });

  test('a cancelled or disabled autosave never reaches the sink', async () => {
    const dir = fakeFsDir();
    const posted: Uint8Array[] = [];
    setJournalSink((b) => posted.push(b));
    autosave(new Uint8Array([1]), dir, true);
    await vi.advanceTimersByTimeAsync(1000); // partway through the debounce
    cancelAutosave();
    autosave(new Uint8Array([2]), dir, false); // disable path also clears the timer
    await vi.advanceTimersByTimeAsync(5000); // well past when either would have fired
    expect(posted).toHaveLength(0);
    expect(dir.save).not.toHaveBeenCalled();
    expect(idb.set).not.toHaveBeenCalled();
  });
});

describe('journal overflow notice (one-shot)', () => {
  test('an over-limit autosave raises the notice ONCE, and still writes locally', async () => {
    // The guard used to be console-only, which meant the entire server-side
    // session surface (tab-close restore, crash recovery, session.data) went
    // stale in silence. Including a sonogram on Save makes that ordinary
    // rather than pathological, so the user has to be told.
    __setJournalSinkMaxBytes(8);
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const notices: [number, number][] = [];
    setJournalSink(() => {});
    setJournalOverflowNotice((bytes, limit) => notices.push([bytes, limit]));

    autosave(new Uint8Array(9), null, true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(notices).toEqual([[9, 8]]);
    expect(idb.set).toHaveBeenCalledTimes(1);      // local write unaffected

    // ONE-SHOT: the condition repeats on every autosave, and a toast per
    // autosave would be its own bug.
    autosave(new Uint8Array(10), null, true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(notices).toHaveLength(1);
    expect(idb.set).toHaveBeenCalledTimes(2);
    warn.mockRestore();
  });

  test('a notice that throws cannot break the local write', async () => {
    __setJournalSinkMaxBytes(8);
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    setJournalSink(() => {});
    setJournalOverflowNotice(() => { throw new Error('toast host gone'); });
    autosave(new Uint8Array(9), null, true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(idb.set).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });

  test('within the limit, nothing is raised', async () => {
    const notices: number[] = [];
    setJournalSink(() => {});
    setJournalOverflowNotice((b) => notices.push(b));
    autosave(new Uint8Array(4), null, true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(notices).toEqual([]);
  });
});

describe('journalPost — the explicit-Save journal seam', () => {
  // Save materialises computed analysis INTO the document, and nothing else
  // re-emits it, so the save handler posts the live document to the journal
  // itself rather than waiting for (or racing) the debounce.
  test('posts immediately, with no timers involved', () => {
    const posted: Uint8Array[] = [];
    setJournalSink((b) => posted.push(b));
    journalPost(new Uint8Array([4, 2]));
    expect(posted).toHaveLength(1);               // no advanceTimers needed
    expect([...posted[0]]).toEqual([4, 2]);
  });

  test('is a no-op with no sink registered (Pages / pyodide sessions)', () => {
    expect(() => journalPost(new Uint8Array([1]))).not.toThrow();
  });

  test('honours the same size guard, and raises the same one-shot notice', () => {
    __setJournalSinkMaxBytes(8);
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const posted: Uint8Array[] = [];
    const notices: number[] = [];
    setJournalSink((b) => posted.push(b));
    setJournalOverflowNotice((b) => notices.push(b));
    journalPost(new Uint8Array(9));
    expect(posted).toHaveLength(0);
    expect(notices).toEqual([9]);
    warn.mockRestore();
  });

  test('a rejecting sink does not escape as an unhandled rejection', async () => {
    setJournalSink(async () => { throw new Error('socket gone'); });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    journalPost(new Uint8Array([1]));
    await vi.advanceTimersByTimeAsync(0);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
