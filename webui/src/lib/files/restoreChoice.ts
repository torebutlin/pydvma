// restoreChoice.ts — which saved session the boot-time restore offers.
//
// Served by pydvma-serve, a session is saved in two places: the serve
// journal (the app's autosave posts the document there, and the server
// registers every capture at birth) and the browser's IndexedDB autosave.
// The journal used to win whenever it held anything. But the post is
// skipped when the document is too big for the /engine frame, or fails when
// the engine is down, while the IndexedDB write still lands — so after a long
// capture the journal's document was STALE, and boot offered it and never
// the IndexedDB copy that held the capture (Task 11). The rule now: offer
// the copy written last, by the times each side records.

/** A saved thing's write time, in ms since the epoch (NaN: unknown). */
export interface SavedAt { savedAt: number }

/** What the serve journal holds, by write time. */
export interface JournalTimes {
  /** The posted document, or absent when none was posted. */
  doc?: SavedAt;
  /** Each pending capture (born at the server since the last post). */
  captures?: SavedAt[];
}

/**
 * Choose which session the boot-time restore offers.
 *
 * - Neither side holds anything: `'none'`; only one does: that one.
 * - Both do: the IndexedDB autosave (`'idb'`) only when it is STRICTLY newer
 *   than the journal's document AND every pending capture, else the journal.
 *   A pending capture newer than the browser copy means the tab closed
 *   inside the autosave debounce, and only the journal has that capture. A
 *   tie goes to the journal: the app stamps its autosave when the write
 *   starts, before the journal post, so a document posted by the same
 *   autosave always carries the later time.
 * - An unknown time (`NaN`: an autosave from an app that predates the
 *   timestamp, or a serve that reports none) keeps the journal — the
 *   behaviour before either side recorded times.
 *
 * Args are null for a side with nothing saved (or unavailable).
 */
export function chooseRestore(
  journal: JournalTimes | null,
  idb: SavedAt | null,
): 'journal' | 'idb' | 'none' {
  const times = journal
    ? [...(journal.doc ? [journal.doc.savedAt] : []), ...(journal.captures ?? []).map((c) => c.savedAt)]
    : [];
  if (times.length === 0) return idb ? 'idb' : 'none';
  if (!idb) return 'journal';
  if (!Number.isFinite(idb.savedAt) || times.some((t) => !Number.isFinite(t))) return 'journal';
  return idb.savedAt > Math.max(...times) ? 'idb' : 'journal';
}
