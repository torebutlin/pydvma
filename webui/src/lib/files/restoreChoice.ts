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

/**
 * The parts of a serve journal read (`stores/engine` `JournalState`) the
 * restore choice needs: what it holds and when each part was written (ms;
 * absent when the serve reports no time).
 */
export interface JournalSnapshot {
  doc: unknown | null;
  captures: readonly unknown[];
  recovered: unknown | null;
  docSavedAt?: number;
  capturesSavedAt?: number[];
  recoveredSavedAt?: number;
}

/** The journal session boot would offer, and its write times. */
export interface JournalOffer {
  /** `'live'`: this serve's document and pending captures; `'recovered'`: a previous run's spill. */
  kind: 'live' | 'recovered';
  times: JournalTimes;
}

/**
 * Which journal session boot would offer, with the times {@link chooseRestore}
 * compares: the live document and captures when it holds any, else a
 * previous run's recovered session, else null. A time the serve did not
 * report is `NaN` (unknown, which keeps the journal).
 *
 * @param state The journal as read at boot, or null when there is none.
 */
export function journalOffer(state: JournalSnapshot | null): JournalOffer | null {
  if (!state) return null;
  if (state.doc || state.captures.length) {
    return {
      kind: 'live',
      times: {
        doc: state.doc ? { savedAt: state.docSavedAt ?? Number.NaN } : undefined,
        captures: state.captures.map((_, i) => ({ savedAt: state.capturesSavedAt?.[i] ?? Number.NaN })),
      },
    };
  }
  if (state.recovered) {
    return { kind: 'recovered', times: { doc: { savedAt: state.recoveredSavedAt ?? Number.NaN } } };
  }
  return null;
}

/**
 * Whether boot needs the IndexedDB autosave's BYTES: only when the answer
 * could be `'idb'`, that is with no journal session to offer, or an autosave
 * timestamp strictly newer than every journal time. Decided from the
 * timestamp alone, so a long session's autosave (hundreds of MB) is not read
 * just to learn the journal wins. When the bytes then turn out to be absent,
 * the journal is offered after all ({@link chooseRestore} with no autosave).
 *
 * @param offer The journal session boot would offer ({@link journalOffer}).
 * @param idbAt The autosave's timestamp (ms), or null when none is stored.
 */
export function idbMightWin(offer: JournalOffer | null, idbAt: number | null): boolean {
  if (!offer) return true;
  if (idbAt === null) return false;
  return chooseRestore(offer.times, { savedAt: idbAt }) === 'idb';
}
