import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { autosave, cancelAutosave, clearAutosave, restoreOffer, __setIdb } from '../../src/lib/files/autosave';
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
