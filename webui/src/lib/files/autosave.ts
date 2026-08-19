// autosave.ts — debounced background autosave + restore.
//
// Every dataset mutation (a new capture, a cleaned impulse, a renamed set)
// schedules an autosave. To avoid thrashing the disk / IndexedDB on rapid
// edits, writes are DEBOUNCED: only the latest payload after a 2 s quiet
// period is persisted. Where it goes depends on the working directory, PLUS
// an optional journal sink that always gets a copy when registered:
//
//   - fsaccess dir → write `autosave.dvma` into the folder (a durable file
//     the user can see and reopen even if IndexedDB is cleared).
//   - download dir → there is no folder, so persist the bytes to IndexedDB
//     under IDB_KEY; on next boot restoreOffer() reads them back and the app
//     offers to restore the session.
//   - journal sink (optional, see setJournalSink) → the pydvma-serve session
//     journal over /engine, when the native engine + journal capability are
//     live. It has NO clearAutosave counterpart by design: the serve journal
//     stays authoritative on its own terms, and an explicit Save only clears
//     the local (folder/idb) stores. It is also SIZE-GUARDED — see
//     JOURNAL_SINK_MAX_BYTES — because the whole document crosses /engine in
//     one frame; a session past the guard keeps its local autosave and drops
//     only the server copy, and says so ONCE (setJournalOverflowNotice).
//
// The journal leg is also reachable on its own, via journalPost(): an
// explicit Save materialises analysis into the document and must reach the
// server WITHOUT waiting for (or racing) the debounce — see App.svelte's
// save handler.
//
// On a FULL explicit Save Dataset (or when the user dismisses the restore
// banner) the caller invokes clearAutosave() so a stale autosave never
// resurfaces after a clean save. A SUBSET save deliberately does not: the
// file it wrote is not the whole session, so the autosave still holds
// something the file does not.
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

/**
 * Optional second autosave target: the pydvma-serve session journal
 * (native-engine stage 3). When registered, every persisted autosave
 * is ALSO handed to the sink (which posts it over /engine as a
 * journal_set op). Best-effort and fire-and-forget, exactly like the
 * idb/folder write: a sink failure (socket closed mid-write, or a
 * rejected promise once the real /engine sink lands) must never break
 * the local autosave. Registered by App.svelte when the native engine
 * + journal capability are live; cleared on fallback.
 */
export type JournalSink = (bytes: Uint8Array) => void | Promise<void>;
let journalSink: JournalSink | null = null;

/**
 * Largest document the journal sink will post. The whole session goes over
 * /engine in ONE websocket frame, and `pydvma-serve` caps an inbound frame at
 * 256 MiB (`max_size` in serve.py's `run()`); an over-cap frame does not fail
 * politely — the server closes the socket with 1009, the app reports "engine
 * connection lost", re-boots, and the next autosave (still over cap) kills it
 * again, forever. So this guard sits comfortably BELOW that cap — the margin
 * covers the frame's own header/envelope and any future growth of serve's
 * per-frame overhead — and a session past it simply stops using the sink:
 * local autosave (folder / IndexedDB) is unaffected, and nothing is lost that
 * an explicit Save would not also have to write.
 */
export const JOURNAL_SINK_MAX_BYTES = 192 * 1024 * 1024;

let journalSinkMaxBytes = JOURNAL_SINK_MAX_BYTES;

/**
 * TEST-ONLY: shrink (or restore) the sink's size guard, so the over-limit
 * branch can be exercised without allocating 192 MB. Not used by the app —
 * same escape hatch as `__setIdb`.
 */
export function __setJournalSinkMaxBytes(next: number): void {
  journalSinkMaxBytes = next;
}

/**
 * Register (or clear, with null) the journal sink; read at persist time, so
 * a pending debounce scheduled before a clear simply skips the sink.
 */
export function setJournalSink(next: JournalSink | null): void {
  journalSink = next;
}

/**
 * Told once, with the offending size and the limit, when a document is too
 * big for the journal sink (see {@link JOURNAL_SINK_MAX_BYTES}).
 */
export type JournalOverflowNotice = (bytes: number, limit: number) => void;
let overflowNotice: JournalOverflowNotice | null = null;
let overflowNotified = false;

/**
 * Register (or clear) the over-size notice — the user-visible half of the
 * size guard, registered by App alongside the sink.
 *
 * Why it exists at all: the guard used to be a bare `console.warn`, which
 * meant the ENTIRE server-side session surface (tab-close restore, crash
 * recovery, `session.data` in a notebook) silently stopped tracking the
 * session while the app carried on looking healthy. That was tolerable while
 * only a pathological session could reach 192 MiB; including sonograms on
 * Save makes it ordinary — one all-channel sonogram of a 30 s × 51.2 kHz ×
 * 4 ch record is ~139 MB, so two measurements cross it.
 *
 * ONE-SHOT: fired at most once per session, because the condition repeats on
 * every autosave and a toast per autosave would be its own bug. It is
 * therefore a *state* notice ("from here on the server copy is stale"), not
 * a per-write error.
 */
export function setJournalOverflowNotice(next: JournalOverflowNotice | null): void {
  overflowNotice = next;
}

/** TEST-ONLY: re-arm the one-shot notice (each test starts fresh). */
export function __resetJournalOverflowNotice(): void {
  overflowNotified = false;
}

/**
 * Hand `bytes` to the journal sink if one is registered and the document is
 * within the size guard; otherwise warn (and raise the one-shot notice).
 *
 * Called from two places, and it matters that both go through here:
 *   - `persist()`, the debounced autosave's journal leg;
 *   - App's explicit Save, which materialises computed analysis INTO the
 *     document and posts it directly (see the exported-seam note in the
 *     module header) — without that post the journal would only learn about
 *     materialised items on the next unrelated mutation, so a tab closed
 *     right after Save would restore a session missing the very results the
 *     user just saved.
 *
 * Fire-and-forget and failure-tolerant in both directions, exactly like the
 * local write: a sink that throws (sync) or rejects (async — the real
 * `/engine` sink is async) must never break the caller's flow.
 */
export function journalPost(bytes: Uint8Array): void {
  if (!journalSink) return;
  if (bytes.length > journalSinkMaxBytes) {
    const mb = (n: number) => Math.round(n / (1024 * 1024));
    console.warn(
      `[autosave] session too large for the serve journal (${mb(bytes.length)} MB > ` +
        `${mb(journalSinkMaxBytes)} MB limit) — local autosave only`,
    );
    if (!overflowNotified) {
      overflowNotified = true;
      try {
        overflowNotice?.(bytes.length, journalSinkMaxBytes);
      } catch (e) {
        console.warn('[autosave] journal overflow notice failed:', e);
      }
    }
    return;
  }
  try {
    void Promise.resolve(journalSink(bytes)).catch((e) =>
      console.warn('[autosave] journal sink failed:', e),
    );
  } catch (e) {
    console.warn('[autosave] journal sink failed:', e);
  }
}

/** The single pending debounce timer (module-level; one autosave at a time). */
let timer: ReturnType<typeof setTimeout> | null = null;

/**
 * Schedule an autosave to `dir`, debounced by 2 s. Rapid calls collapse to a
 * single write once 2 s elapse with no further call. When `enabled` is false
 * the call is a no-op AND cancels any pending write (calling `autosave(...,
 * false)` is equivalent to `cancelAutosave()`), so disabling autosave never
 * lets a stale scheduled write slip through. fsaccess dirs get an
 * `autosave.dvma` file; download dirs persist to IndexedDB.
 *
 * NOTE: only a subsequent `autosave(false)` / `cancelAutosave()` cancels a
 * pending write — the fired timer does NOT re-read some external enabled flag.
 * The UI toggle therefore calls `cancelAutosave()` when it goes OFF so a write
 * scheduled just before the toggle does not fire after it.
 *
 * `source` is a THUNK, not bytes: the (potentially expensive) `writeDvma`
 * serialize is DEFERRED until the debounce timer actually fires, and only the
 * latest scheduled thunk is invoked. This is load-bearing — a naive
 * `autosave(writeDvma(ds), …)` would serialize the whole zip on EVERY store
 * emission (and re-serialize the bytes just loaded on every loadDataset /
 * Restore), even though N rapid mutations must yield exactly ONE write. The
 * thunk collapses N serializes to 1. A raw `Uint8Array` is still accepted for
 * callers that already hold the bytes.
 */
export function autosave(
  source: Uint8Array | (() => Uint8Array),
  dir: WorkDir | null,
  enabled: boolean,
): void {
  if (timer !== null) clearTimeout(timer);
  if (!enabled) {
    timer = null;
    return;
  }
  timer = setTimeout(() => {
    timer = null;
    // Serialize NOW (once), only for the write that actually fires.
    const bytes = typeof source === 'function' ? source() : source;
    void persist(bytes, dir);
  }, DEBOUNCE_MS);
}

/**
 * Cancel a pending (debounced-but-not-yet-fired) autosave. Called when the
 * user toggles autosave OFF so a write scheduled by a mutation just before the
 * toggle does not still land 2 s later. No-op when nothing is pending. Does
 * NOT touch already-persisted bytes — use `clearAutosave()` for that.
 */
export function cancelAutosave(): void {
  if (timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
}

/**
 * Perform the actual write: folder file for fsaccess, else IndexedDB — and,
 * when registered and within `JOURNAL_SINK_MAX_BYTES`, fan out a copy to the
 * journal sink too. An over-size session degrades to local-only autosave with
 * one console warning, rather than repeatedly closing the /engine socket.
 */
async function persist(bytes: Uint8Array, dir: WorkDir | null): Promise<void> {
  journalPost(bytes);          // size-guarded, failure-tolerant; see its doc
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
 * Delete the IndexedDB autosave. Called after a successful FULL explicit Save
 * Dataset (the autosave is now redundant) and when the user dismisses the
 * restore banner, so a stale session never re-offers.
 *
 * NOT called after a SUBSET save ("Choose sets…"): that file holds only the
 * chosen measurements, so the autosave still carries session state the file
 * does not and must survive.
 */
export async function clearAutosave(): Promise<void> {
  await idb.del(IDB_KEY);
}
