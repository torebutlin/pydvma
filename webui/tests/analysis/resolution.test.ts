import { expect, test } from 'vitest';
import { fromNFrames, fromFrameLength, fromNFft } from '../../src/lib/analysis/resolution';

// ground truth from the Qt GUI: 30 s capture, N=10 -> "Frame length = 5.45 s"
test('nFrames -> frame length matches Qt formula (overlap 0.5)', () => {
  const r = fromNFrames(10, 30, 44100);
  expect(r.frameLengthS).toBeCloseTo(5.4545, 3);
  expect(r.nFft).toBe(Math.round(5.4545454 * 44100));
  expect(r.dF).toBeCloseTo(1 / r.frameLengthS, 6);
});

test('round trips: frameLength -> nFrames -> frameLength', () => {
  const a = fromFrameLength(1.0, 30, 44100);
  const b = fromNFrames(a.nFrames, 30, 44100);
  expect(b.frameLengthS).toBeCloseTo(a.frameLengthS, 6);
});

test('nFft entry snaps the other two consistently', () => {
  const r = fromNFft(44100, 30, 44100);       // 1 s frames
  expect(r.frameLengthS).toBeCloseTo(1, 6);
  expect(r.nFrames).toBeGreaterThan(1);
});

test('clamps nFrames to [1, samples]', () => {
  expect(fromNFrames(0, 30, 44100).nFrames).toBe(1);
});
