// autosave.ts — debounced background autosave + restore.
//
// Every dataset mutation (a new capture, a cleaned impulse, a renamed set)
// schedules an autosave. To avoid thrashing the disk / IndexedDB on rapid
// edits, writes are DEBOUNCED: only the latest payload after a 2 s quiet
// period is persisted. Where it goes depends on the working directory:
//
//   - fsaccess dir → write `autosave.dvma` into the folder (a durable file
//     the user can see and reopen even if IndexedDB is cleared).
//   - download dir → there is no folder, so persist the bytes to IndexedDB
//     under IDB_KEY; on next boot restoreOffer() reads them back and the app
//     offers to restore the session.
//
// On an explicit Save Dataset (or when the user dismisses the restore
// banner) the caller invokes clearAutosave() so a stale autosave never
// resurfaces after a clean save.
import { del as idbDelReal, get as idbGetReal, set as idbSetReal } from 'idb-keyval';
import type { WorkDir } from './workdir';

/** IndexedDB key holding the last autosave bytes (download-mode fallback). */
export const IDB_KEY = 'pydvma:autosave';

/** Filename used for the in-folder autosave when an fsaccess dir is set. */
const AUTOSAVE_NAME = 'autosave.dvma';

/** Debounce window: writes settle 2 s after the last mutation. */
const DEBOUNCE_MS = 2000;

/**
 * Injectable idb functions so the debounce/enabled-gate can be tested with
 * fake timers and an in-memory store (no real IndexedDB in node). The app
 * uses the real idb-keyval trio; `__setIdb` swaps them in tests.
 */
interface IdbLike {
  get(key: string): Promise<Uint8Array | undefined>;
  set(key: string, value: Uint8Array): Promise<void>;
  del(key: string): Promise<void>;
}
let idb: IdbLike = {
  get: (k) => idbGetReal(k),
  set: (k, v) => idbSetReal(k, v),
  del: (k) => idbDelReal(k),
};

/** TEST-ONLY: override the idb backend. Not used by the app. */
export function __setIdb(next: IdbLike): void {
  idb = next;
}

/** The single pending debounce timer (module-level; one autosave at a time). */
let timer: ReturnType<typeof setTimeout> | null = null;

/**
 * Schedule an autosave of `bytes` to `dir`, debounced by 2 s. Rapid calls
 * collapse to a single write of the LATEST bytes once 2 s elapse with no
 * further call. When `enabled` is false the call is a no-op (and does NOT
 * cancel an already-scheduled write — the enabled flag is checked again
 * when the timer fires so a mid-flight disable is honoured). fsaccess dirs
 * get an `autosave.dvma` file; download dirs persist to IndexedDB.
 *
 * `bytes` should be the current `writeDvma(dataset)` output; the caller
 * computes it (autosave never touches the dataset model directly).
 */
export function autosave(bytes: Uint8Array, dir: WorkDir | null, enabled: boolean): void {
  if (timer !== null) clearTimeout(timer);
  if (!enabled) {
    timer = null;
    return;
  }
  timer = setTimeout(() => {
    timer = null;
    void persist(bytes, dir);
  }, DEBOUNCE_MS);
}

/** Perform the actual write (folder file for fsaccess, else IndexedDB). */
async function persist(bytes: Uint8Array, dir: WorkDir | null): Promise<void> {
  try {
    if (dir && dir.kind === 'fsaccess') {
      await dir.save(AUTOSAVE_NAME, bytes);
    } else {
      await idb.set(IDB_KEY, bytes);
    }
  } catch (e) {
    // Autosave is best-effort: never surface a failure to the user flow.
    console.warn('[autosave] write failed:', e);
  }
}

/**
 * Read the last IndexedDB autosave, if any, for the boot-time restore
 * banner. Returns the raw `.dvma` bytes (feed to `readDvma`) or null when
 * there is nothing to restore. Only the download-mode fallback is offered
 * here — an fsaccess autosave.dvma is a visible file the user can reopen
 * directly, so it is not auto-surfaced.
 */
export async function restoreOffer(): Promise<Uint8Array | null> {
  const v = await idb.get(IDB_KEY);
  return v ?? null;
}

/**
 * Delete the IndexedDB autosave. Called after a successful explicit Save
 * Dataset (the autosave is now redundant) and when the user dismisses the
 * restore banner, so a stale session never re-offers.
 */
export async function clearAutosave(): Promise<void> {
  await idb.del(IDB_KEY);
}
