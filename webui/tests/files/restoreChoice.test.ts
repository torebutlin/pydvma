// chooseRestore: which saved session the boot-time restore offers (Task 11).
// The bug it fixes: after a long capture the serve journal's document was a
// STALE smaller one (the app's post had been skipped for size), and boot
// offered it and never the IndexedDB autosave that held the capture.
import { describe, expect, test } from 'vitest';
import { chooseRestore, idbMightWin, journalOffer } from '../../src/lib/files/restoreChoice';

describe('chooseRestore', () => {
  test('nothing saved anywhere offers nothing', () => {
    expect(chooseRestore(null, null)).toBe('none');
    expect(chooseRestore({}, null)).toBe('none');
    expect(chooseRestore({ captures: [] }, null)).toBe('none');
  });

  test('only one side saved offers that side', () => {
    expect(chooseRestore(null, { savedAt: 1000 })).toBe('idb');
    expect(chooseRestore({}, { savedAt: 1000 })).toBe('idb');
    expect(chooseRestore({ doc: { savedAt: 1000 } }, null)).toBe('journal');
    expect(chooseRestore({ captures: [{ savedAt: 1000 }] }, null)).toBe('journal');
  });

  test('an IndexedDB autosave newer than the journal document wins', () => {
    expect(chooseRestore({ doc: { savedAt: 1000 } }, { savedAt: 5000 })).toBe('idb');
  });

  test('a journal document newer than the IndexedDB autosave wins', () => {
    expect(chooseRestore({ doc: { savedAt: 5000 } }, { savedAt: 1000 })).toBe('journal');
  });

  test('a tie goes to the journal (it also holds captures born at the server)', () => {
    expect(chooseRestore({ doc: { savedAt: 3000 } }, { savedAt: 3000 })).toBe('journal');
  });

  test('a pending capture newer than the IndexedDB autosave keeps the journal', () => {
    // The tab closed inside the autosave debounce: the browser copy predates
    // the capture, which only the journal holds.
    expect(chooseRestore(
      { doc: { savedAt: 1000 }, captures: [{ savedAt: 9000 }] },
      { savedAt: 5000 },
    )).toBe('journal');
    expect(chooseRestore({ captures: [{ savedAt: 9000 }] }, { savedAt: 5000 })).toBe('journal');
  });

  test('an IndexedDB autosave newer than the document AND every capture wins', () => {
    expect(chooseRestore(
      { doc: { savedAt: 1000 }, captures: [{ savedAt: 2000 }] },
      { savedAt: 5000 },
    )).toBe('idb');
  });

  test('an unknown time keeps the journal, the behaviour before timestamps existed', () => {
    // An autosave written by an older app has no timestamp; a journal from an
    // older serve reports none.
    expect(chooseRestore({ doc: { savedAt: 1000 } }, { savedAt: Number.NaN })).toBe('journal');
    expect(chooseRestore({ doc: { savedAt: Number.NaN } }, { savedAt: 5000 })).toBe('journal');
    expect(chooseRestore(
      { doc: { savedAt: 1000 }, captures: [{ savedAt: Number.NaN }] },
      { savedAt: 5000 },
    )).toBe('journal');
  });
});

// The journal read -> write times mapping, and whether boot has to read the
// IndexedDB bytes at all (final review, Minor 17: boot read a 0.6 GB autosave
// only to learn that the journal won).
describe('journalOffer', () => {
  const bytes = new Uint8Array([1]);
  test('a live journal offers its document and captures, with their times', () => {
    expect(journalOffer({
      doc: bytes, captures: [bytes, bytes], recovered: null,
      docSavedAt: 1000, capturesSavedAt: [2000, 3000],
    })).toEqual({
      kind: 'live',
      times: { doc: { savedAt: 1000 }, captures: [{ savedAt: 2000 }, { savedAt: 3000 }] },
    });
  });
  test('a time the serve did not report is unknown (NaN)', () => {
    const o = journalOffer({ doc: null, captures: [bytes], recovered: null });
    expect(o?.kind).toBe('live');
    expect(o?.times.doc).toBeUndefined();
    expect(Number.isNaN(o!.times.captures![0].savedAt)).toBe(true);
    expect(Number.isNaN(journalOffer({ doc: bytes, captures: [], recovered: null })!.times.doc!.savedAt))
      .toBe(true);
  });
  test('an empty live journal offers a previous run\'s recovered session', () => {
    expect(journalOffer({ doc: null, captures: [], recovered: bytes, recoveredSavedAt: 500 }))
      .toEqual({ kind: 'recovered', times: { doc: { savedAt: 500 } } });
    // A live session wins over a recovered one.
    expect(journalOffer({ doc: bytes, captures: [], recovered: bytes, docSavedAt: 1 })?.kind).toBe('live');
  });
  test('nothing in the journal, or no journal, offers nothing', () => {
    expect(journalOffer({ doc: null, captures: [], recovered: null })).toBeNull();
    expect(journalOffer(null)).toBeNull();
  });
});

describe('idbMightWin', () => {
  const live = { kind: 'live' as const, times: { doc: { savedAt: 1000 }, captures: [{ savedAt: 2000 }] } };
  test('with no journal the autosave is the only candidate', () => {
    expect(idbMightWin(null, null)).toBe(true);
    expect(idbMightWin(null, 5)).toBe(true);
  });
  test('no autosave timestamp: the journal wins without reading the bytes', () => {
    expect(idbMightWin(live, null)).toBe(false);
  });
  test('read the bytes only when the autosave is newer than every journal time', () => {
    expect(idbMightWin(live, 1500)).toBe(false);    // a capture is newer
    expect(idbMightWin(live, 2000)).toBe(false);    // a tie goes to the journal
    expect(idbMightWin(live, 2500)).toBe(true);
    expect(idbMightWin({ kind: 'recovered', times: { doc: { savedAt: 10 } } }, 20)).toBe(true);
  });
});
