import { describe, expect, test } from 'vitest';
import {
  applyRowChange,
  channelRows,
  clampStatedGain,
  GAIN_RANGE_SLACK_DB,
  fitToChannels,
  retargetGain,
  opticalRange,
  rangeText,
  roleRange,
  rowFullScaleVolts,
  shouldUsePreferredFs,
  staleChannelSettingsReset,
} from '../../src/lib/model/channelGain';
import { dbuToVoltsPeak, type DeviceCapsEntry } from '../../src/lib/audio/provider';

const ROLES22 = [
  ...Array(4).fill('analogue'),
  ...Array(16).fill('optical'),
  ...Array(2).fill('loopback'),
];
const ID44: DeviceCapsEntry = {
  channel_roles: ROLES22,
  input_modes: ['mic', 'line', 'inst'],
  max_input_dbu: { mic: 18, line: 28, inst: 10 },
  gain_range_db: { mic: [0, 60], line: [-10, 50], inst: [0, 60] },
  pad_db: 10,
  mode_channels: { inst: [0, 1] },
  per_channel_gain: true,
  preferred_fs: 48000,
};

describe('channelRows', () => {
  test('iD44: one row per analogue channel, inst on the first two only', () => {
    const rows = channelRows(ID44, 22, ROLES22);
    expect(rows.map((r) => r.ch)).toEqual([0, 1, 2, 3]);
    expect(rows[0].modes).toContain('inst');
    expect(rows[1].modes).toContain('inst');
    expect(rows[2].modes).not.toContain('inst');
    expect(rows[3].modes).toEqual(['mic', 'line']);
    expect(rows[2].gainRange.line).toEqual([-10, 50]);
    expect(rows[2].gainRange.inst).toBeUndefined();
    expect(rows.every((r) => r.padAvailable)).toBe(true);
  });
  test('a channel count of 2 gives two rows; no pad_db means no pad', () => {
    expect(channelRows(ID44, 2, ROLES22)).toHaveLength(2);
    expect(channelRows({ ...ID44, pad_db: null }, 4, ROLES22)[0].padAvailable).toBe(false);
  });
});

describe('rowFullScaleVolts', () => {
  const row = channelRows(ID44, 4, ROLES22)[0];
  test('mic 60 dB with the pad: 18 - 60 + 10 dBu', () => {
    expect(rowFullScaleVolts(ID44, row, 60, 'mic', true)).toBeCloseTo(dbuToVoltsPeak(-32), 12);
  });
  test('line starts at -10 dB: gain -10 gives the 28 dBu maximum', () => {
    expect(rowFullScaleVolts(ID44, row, -10, 'line', false)).toBeCloseTo(dbuToVoltsPeak(28), 12);
  });
  test('blank gain, or a mode the row lacks, gives null', () => {
    expect(rowFullScaleVolts(ID44, row, null, 'mic', false)).toBeNull();
    const r3 = channelRows(ID44, 4, ROLES22)[2];
    expect(rowFullScaleVolts(ID44, r3, 20, 'inst', false)).toBeNull();
  });
});

describe('ranges', () => {
  test('opticalRange', () => {
    expect(opticalRange(ROLES22, 22)).toEqual([5, 20]);
    expect(opticalRange(ROLES22, 4)).toBeNull();
    expect(opticalRange(ROLES22, 10)).toEqual([5, 10]);
  });
  test('loopback range names 21-22 with optical between', () => {
    const r = roleRange(ROLES22, 'loopback', 22);
    expect(r).toEqual([21, 22]);
    expect(rangeText(r!)).toBe('channels 21–22');
    expect(roleRange(ROLES22, 'loopback', 20)).toBeNull();
    expect(rangeText([3, 3])).toBe('channel 3');
  });
});

describe('shouldUsePreferredFs', () => {
  const rates = [44100, 48000, 88200, 96000];
  test('moves a foreign rate to the preferred one', () => {
    expect(shouldUsePreferredFs(ID44, 10000, rates, false)).toBe(true);
  });
  test('not when already there, with the low-pass on, or no preference', () => {
    expect(shouldUsePreferredFs(ID44, 48000, rates, false)).toBe(false);
    expect(shouldUsePreferredFs(ID44, 10000, rates, true)).toBe(false);
    expect(shouldUsePreferredFs({ ...ID44, preferred_fs: null }, 10000, rates, false)).toBe(false);
    expect(shouldUsePreferredFs(undefined, 10000, rates, false)).toBe(false);
  });
  test('not when the hardware cannot run it', () => {
    expect(shouldUsePreferredFs(ID44, 10000, [44100], false)).toBe(false);
  });
});

describe('staleChannelSettingsReset', () => {
  const lists = { inputGainDb: [10, null], inputMode: ['mic', 'line'], inputPad: [true, false] } as const;
  test('lists survive on a per-channel device', () => {
    expect(staleChannelSettingsReset(ID44, lists as never)).toEqual({});
  });
  test('lists are cleared on any other device, scalars are kept', () => {
    const p = staleChannelSettingsReset({ input_modes: ['line'] }, lists as never);
    expect(Object.keys(p).sort()).toEqual(['inputGainDb', 'inputMode', 'inputPad']);
    expect(Object.values(p).every((v) => v === undefined)).toBe(true);
    expect(staleChannelSettingsReset(null, { inputGainDb: 20, inputMode: 'mic', inputPad: true })).toEqual({});
  });
});

describe('retargetGain', () => {
  const r = channelRows(ID44, 4, ROLES22)[0].gainRange;
  test('keeps the knob position across modes', () => {
    expect(retargetGain(r, 'mic', 'line', 30)).toBe(20);
    expect(retargetGain(r, 'line', 'mic', 50)).toBe(60);
    expect(retargetGain(r, 'line', 'mic', -10)).toBe(0);
    expect(retargetGain(r, 'mic', 'inst', 40)).toBe(40);
    expect(retargetGain(r, 'mic', 'line', null)).toBeNull();
  });
});

describe('applyRowChange', () => {
  const rows = channelRows(ID44, 4, ROLES22);
  test('a gain edit fills the other channels and always writes the mode', () => {
    const o = applyRowChange({}, rows[2], { gain: 25 }, 4);
    expect(o.inputGainDb).toEqual([null, null, 25, null]);
    expect(o.inputMode).toEqual(['line', 'line', 'line', 'line']);
    expect(o.inputPad).toEqual([false, false, false, false]);
  });
  test('a pad toggle leaves the gains alone', () => {
    const o = applyRowChange({ inputGainDb: [10, null], inputMode: ['mic', 'line'] }, rows[1], { pad: true }, 2);
    expect(o.inputGainDb).toEqual([10, null]);
    expect(o.inputMode).toEqual(['mic', 'line']);
    expect(o.inputPad).toEqual([false, true]);
  });
  test('a mode change retargets that row only', () => {
    const cur = { inputGainDb: [30, 30], inputMode: ['mic', 'mic'] as ('mic')[] };
    const o = applyRowChange(cur, rows[0], { mode: 'line' }, 2);
    expect(o.inputMode).toEqual(['line', 'mic']);
    expect(o.inputGainDb).toEqual([20, 30]);
  });
  test('clearing the only gain gives undefined', () => {
    expect(applyRowChange({ inputGainDb: [5] }, rows[0], { gain: null }, 1).inputGainDb).toBeUndefined();
  });
});

describe('fitToChannels', () => {
  test('pads, truncates, and leaves a scalar', () => {
    expect(fitToChannels([1, 2], 4, null)).toEqual([1, 2, null, null]);
    expect(fitToChannels([1, 2, 3], 2, null)).toEqual([1, 2]);
    expect(fitToChannels('mic', 4, 'line')).toBe('mic');
  });
});

describe('clampStatedGain', () => {
  test('a measured stop just past the published range is kept (twin of python GAIN_RANGE_SLACK_DB)', () => {
    expect(GAIN_RANGE_SLACK_DB).toBe(2);
    expect(clampStatedGain([0, 60], 60.51)).toBe(60.51);
    expect(clampStatedGain([-10, 50], -11.2)).toBe(-11.2);
  });
  test('beyond the slack it clamps to the slack edge', () => {
    expect(clampStatedGain([0, 60], 75)).toBe(62);
    expect(clampStatedGain([-10, 50], -30)).toBe(-12);
  });
  test('a fixed range has no knob, so no slack; no range keeps the value', () => {
    expect(clampStatedGain([0, 0], 1.5)).toBe(0);
    expect(clampStatedGain(undefined, 71)).toBe(71);
  });
});
