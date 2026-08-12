// progress.test.ts — the worker-side progress poster (round-11 P7).
//
// The poster is the piece between pydvma's per-scale callback and the main
// thread: it stamps frames with the ACTIVE call id and rate-limits them. Both
// jobs are pure logic, so they are tested here with an injected clock rather
// than through a real worker (engine.worker.ts imports pyodide and cannot be
// loaded in node).
import { describe, expect, test } from 'vitest';
import { createProgressPoster, PROGRESS_THROTTLE_MS, type ProgressMessage } from '../../src/lib/worker/progress';

/** Poster with a manually advanced clock. */
function makePoster(intervalMs = PROGRESS_THROTTLE_MS) {
  const sent: ProgressMessage[] = [];
  let t = 1000;
  const poster = createProgressPoster((m) => sent.push(m), () => t, intervalMs);
  return { poster, sent, advance: (ms: number) => { t += ms; }, now: () => t };
}

describe('progress poster: arming', () => {
  test('drops frames when nothing is armed', () => {
    const { poster, sent } = makePoster();
    poster.postProgress(1, 10);
    expect(sent).toEqual([]);
  });

  test('stamps frames with the armed call id', () => {
    const { poster, sent } = makePoster();
    poster.arm(7);
    poster.postProgress(3, 10);
    expect(sent).toEqual([{ type: 'progress', callId: 7, done: 3, total: 10 }]);
  });

  test('disarm stops reporting — a late frame is never mis-attributed', () => {
    const { poster, sent, advance } = makePoster();
    poster.arm(7);
    poster.postProgress(1, 10);
    poster.disarm();
    advance(1000);
    poster.postProgress(2, 10);
    expect(sent.map((m) => m.done)).toEqual([1]);
  });

  test('re-arming switches id and lets the next call report immediately', () => {
    const { poster, sent } = makePoster();
    poster.arm(1);
    poster.postProgress(1, 4);
    poster.arm(2);            // no clock advance at all
    poster.postProgress(1, 4);
    expect(sent.map((m) => m.callId)).toEqual([1, 2]);
  });
});

describe('progress poster: throttling', () => {
  test('rate-limits to one frame per interval', () => {
    const { poster, sent, advance } = makePoster(100);
    poster.arm(1);
    poster.postProgress(1, 100);      // first frame always goes (carries total)
    poster.postProgress(2, 100);      // same instant — dropped
    advance(50);
    poster.postProgress(3, 100);      // still inside the window — dropped
    advance(60);
    poster.postProgress(4, 100);      // 110 ms since the last send — goes
    expect(sent.map((m) => m.done)).toEqual([1, 4]);
  });

  test('the terminal frame is never throttled away', () => {
    const { poster, sent } = makePoster(100);
    poster.arm(1);
    poster.postProgress(1, 3);
    poster.postProgress(2, 3);        // dropped (same instant)
    poster.postProgress(3, 3);        // done === total — always sent
    expect(sent.map((m) => m.done)).toEqual([1, 3]);
  });

  test('a 5000-scale transform posts ~10 Hz, not 5000 messages', () => {
    // One scale every 2 ms of compute: 10 s of work at the default interval.
    const { poster, sent, advance } = makePoster();
    poster.arm(1);
    for (let i = 1; i <= 5000; i++) {
      poster.postProgress(i, 5000);
      advance(2);
    }
    expect(sent.length).toBeLessThanOrEqual(10_000 / PROGRESS_THROTTLE_MS + 2);
    expect(sent[sent.length - 1].done).toBe(5000);
  });
});
