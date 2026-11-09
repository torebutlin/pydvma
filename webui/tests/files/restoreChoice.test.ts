// chooseRestore: which saved session the boot-time restore offers (Task 11).
// The bug it fixes: after a long capture the serve journal's document was a
// STALE smaller one (the app's post had been skipped for size), and boot
// offered it and never the IndexedDB autosave that held the capture.
import { describe, expect, test } from 'vitest';
import { chooseRestore } from '../../src/lib/files/restoreChoice';

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
