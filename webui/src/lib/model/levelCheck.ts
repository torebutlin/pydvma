/**
 * Judging whether an input level is usable, before a capture commits to it.
 *
 * A sound-card preamp gain is a front-panel knob no audio API can read, so
 * the only way to know the level is right is to look at the signal. Getting
 * it wrong is silent in both directions: too high clips (a 5 Vpp sine into a
 * Scarlett at 24 dB gain came back with 78 % of samples at the rail, THD
 * 30 %, and a crest factor of 1.10 — a square wave), and too low buries the
 * signal in converter noise while still drawing a plausible-looking trace.
 *
 * Thresholds are on PEAK, since that is what clips:
 *
 * - **clip** at ≥ 0.99 of full scale — samples are at the rail.
 * - **hot** at ≥ 0.95 — pydvma's own capture-time clip check uses
 *   `0.95 * input_vmax()` (`acquisition.log_data`), so this is the same line
 *   drawn before the capture rather than after it.
 * - **low** below 0.01 (−40 dBFS) — more than 40 dB of the converter's range
 *   is going unused, which costs real signal-to-noise.
 *
 * Volts are reported only when the operator has stated a preamp gain, since
 * that is the only thing that fixes the normalised-to-volts scale.
 */

/** Peak at or above this fraction of full scale is clipping. */
export const CLIP_PEAK = 0.99;
/** Peak at or above this is within pydvma's own clip-check margin. */
export const HOT_PEAK = 0.95;
/** Peak below this wastes more than 40 dB of converter range. */
export const LOW_PEAK = 0.01;

export type LevelVerdict = 'clip' | 'hot' | 'ok' | 'low' | 'silent';

export interface ChannelLevelReport {
  /** Zero-based channel index. */
  channel: number;
  /** Peak as a fraction of full scale. */
  peak: number;
  /** RMS as a fraction of full scale. */
  rms: number;
  /** Peak in dBFS; `-Infinity` for digital silence. */
  peakDbfs: number;
  /** Peak in volts, or `null` when no gain has been stated. */
  peakVolts: number | null;
  /** RMS in volts, or `null` when no gain has been stated. */
  rmsVolts: number | null;
  verdict: LevelVerdict;
}

/** Peak/RMS of one channel as fractions of full scale. */
export interface ChannelLevelInput {
  peak: number;
  rms: number;
}

/**
 * Classify one peak level.
 *
 * Exact zero is reported as `'silent'` rather than `'low'`: nothing
 * connected is a different problem from a signal that is merely too quiet,
 * and telling someone to turn the gain up when the cable is out wastes
 * their time.
 */
export function classifyPeak(peak: number): LevelVerdict {
  if (!(peak > 0)) return 'silent';
  if (peak >= CLIP_PEAK) return 'clip';
  if (peak >= HOT_PEAK) return 'hot';
  if (peak < LOW_PEAK) return 'low';
  return 'ok';
}

/**
 * Build a per-channel report from monitor levels.
 *
 * `fullScaleVolts` is the jack voltage that reads 1.0 — pydvma's `VmaxSC`,
 * derived from the stated preamp gain. Pass `null` when no gain has been
 * stated and the report carries dBFS only; inventing a scale would be worse
 * than admitting there isn't one.
 */
export function reportLevels(
  levels: readonly ChannelLevelInput[],
  fullScaleVolts: number | null,
): ChannelLevelReport[] {
  const scale = fullScaleVolts != null && fullScaleVolts > 0 ? fullScaleVolts : null;
  return levels.map((lvl, channel) => {
    const peak = Number.isFinite(lvl?.peak) ? Math.abs(lvl.peak) : 0;
    const rms = Number.isFinite(lvl?.rms) ? Math.abs(lvl.rms) : 0;
    return {
      channel,
      peak,
      rms,
      peakDbfs: peak > 0 ? 20 * Math.log10(peak) : -Infinity,
      peakVolts: scale == null ? null : peak * scale,
      rmsVolts: scale == null ? null : rms * scale,
      verdict: classifyPeak(peak),
    };
  });
}

/**
 * The worst verdict across channels — what a single summary should say.
 *
 * Ordered by how much it invalidates a measurement: clipping destroys the
 * waveform, silence means there is nothing to measure, a hot channel is
 * about to clip, and a low one merely costs signal-to-noise.
 */
export function worstVerdict(reports: readonly ChannelLevelReport[]): LevelVerdict | null {
  if (!reports.length) return null;
  const order: LevelVerdict[] = ['clip', 'silent', 'hot', 'low', 'ok'];
  for (const v of order) {
    if (reports.some((r) => r.verdict === v)) return v;
  }
  return 'ok';
}

/** One-line guidance for a verdict, phrased as the action to take. */
export function verdictAdvice(verdict: LevelVerdict): string {
  switch (verdict) {
    case 'clip':
      return 'clipping — turn the input gain down';
    case 'hot':
      return 'close to clipping — turn the gain down a little';
    case 'low':
      return 'very low — turn the input gain up';
    case 'silent':
      return 'no signal — check the cable and the source';
    default:
      return 'levels look good';
  }
}
