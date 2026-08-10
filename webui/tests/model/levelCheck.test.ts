import { describe, expect, test } from 'vitest';
import {
  CLIP_PEAK,
  HOT_PEAK,
  LOW_PEAK,
  classifyPeak,
  reportLevels,
  verdictAdvice,
  worstVerdict,
} from '../../src/lib/model/levelCheck';

describe('classifyPeak', () => {
  test('flags samples at the rail as clipping', () => {
    expect(classifyPeak(1.0)).toBe('clip');
    expect(classifyPeak(CLIP_PEAK)).toBe('clip');
  });

  test('warns just below the rail, on pydvma capture-time margin', () => {
    // acquisition.log_data checks against 0.95 * input_vmax(); this is the
    // same line drawn BEFORE the capture rather than after it.
    expect(classifyPeak(HOT_PEAK)).toBe('hot');
    expect(classifyPeak(0.98)).toBe('hot');
  });

  test('accepts a healthy level', () => {
    expect(classifyPeak(0.5)).toBe('ok');
    expect(classifyPeak(0.505)).toBe('ok'); // the measured 9 dB sine
  });

  test('flags a level that wastes converter range', () => {
    expect(classifyPeak(0.001)).toBe('low');
    expect(classifyPeak(LOW_PEAK - 1e-9)).toBe('low');
  });

  test('distinguishes silence from merely quiet', () => {
    // Telling someone to turn the gain up when the cable is out wastes
    // their time; these are different problems.
    expect(classifyPeak(0)).toBe('silent');
    expect(classifyPeak(-0)).toBe('silent');
    expect(classifyPeak(NaN)).toBe('silent');
  });

  test('the real clipped capture would have been caught', () => {
    // A 5 Vpp sine at 24 dB gain: 78 % of samples at the rail, peak 1.0158.
    expect(classifyPeak(1.0158)).toBe('clip');
  });
});

describe('reportLevels', () => {
  test('converts to volts when a gain has been stated', () => {
    // VmaxSC = 4.8932 V pk at 9 dB line gain, confirmed on hardware.
    const [r] = reportLevels([{ peak: 0.505072, rms: 0.357139 }], 4.8932);
    expect(r.peakVolts).toBeCloseTo(2.4714, 3);
    expect(r.rmsVolts).toBeCloseTo(1.7475, 3);
    expect(r.verdict).toBe('ok');
  });

  test('reports dBFS only when no gain has been stated', () => {
    // Inventing a scale would be worse than admitting there isn't one.
    const [r] = reportLevels([{ peak: 0.5, rms: 0.35 }], null);
    expect(r.peakVolts).toBeNull();
    expect(r.rmsVolts).toBeNull();
    expect(r.peakDbfs).toBeCloseTo(-6.02, 2);
  });

  test('ignores a non-positive full scale rather than producing zero volts', () => {
    expect(reportLevels([{ peak: 0.5, rms: 0.35 }], 0)[0].peakVolts).toBeNull();
    expect(reportLevels([{ peak: 0.5, rms: 0.35 }], -1)[0].peakVolts).toBeNull();
  });

  test('digital silence reports -Infinity dBFS, not NaN', () => {
    const [r] = reportLevels([{ peak: 0, rms: 0 }], 4.8932);
    expect(r.peakDbfs).toBe(-Infinity);
    expect(r.peakVolts).toBe(0);
  });

  test('indexes channels in order', () => {
    const rs = reportLevels(
      [{ peak: 0.1, rms: 0.05 }, { peak: 0.2, rms: 0.1 }],
      null,
    );
    expect(rs.map((r) => r.channel)).toEqual([0, 1]);
  });

  test('survives malformed level entries', () => {
    const rs = reportLevels(
      [{ peak: NaN, rms: NaN }, { peak: Infinity, rms: 1 }] as never,
      null,
    );
    expect(rs[0].verdict).toBe('silent');
    expect(rs[1].peak).toBe(0);
  });
});

describe('worstVerdict', () => {
  const at = (peak: number) => reportLevels([{ peak, rms: peak / 2 }], null)[0];

  test('clipping beats every other problem', () => {
    expect(worstVerdict([at(0.5), at(1.0), at(0.001)])).toBe('clip');
  });

  test('a dead channel outranks a hot one', () => {
    // Nothing to measure is worse than nearly too much.
    expect(worstVerdict([at(0.96), at(0)])).toBe('silent');
  });

  test('hot outranks low', () => {
    expect(worstVerdict([at(0.001), at(0.96)])).toBe('hot');
  });

  test('all-good reports ok', () => {
    expect(worstVerdict([at(0.4), at(0.5)])).toBe('ok');
  });

  test('no channels reports nothing rather than a false all-clear', () => {
    expect(worstVerdict([])).toBeNull();
  });
});

describe('verdictAdvice', () => {
  test('says which way to turn the knob', () => {
    expect(verdictAdvice('clip')).toMatch(/down/);
    expect(verdictAdvice('hot')).toMatch(/down/);
    expect(verdictAdvice('low')).toMatch(/up/);
  });

  test('sends you to the cable when there is no signal at all', () => {
    expect(verdictAdvice('silent')).toMatch(/cable/);
  });

  test('every verdict has advice', () => {
    for (const v of ['clip', 'hot', 'ok', 'low', 'silent'] as const) {
      expect(verdictAdvice(v).length).toBeGreaterThan(0);
    }
  });
});
