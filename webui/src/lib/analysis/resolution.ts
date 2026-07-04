// Coupled resolution control (design spec §5): N_frames <-> frame length <-> N_fft.
// Formula matches the Qt GUI with 50% overlap:
//   frameLength = duration / (nFrames*(1-overlap) + overlap)
// Ground truth: 30 s capture, N=10 -> frame length 5.4545... s.
const OVERLAP = 0.5;

/**
 * One consistent snapshot of the coupled resolution parameters.
 *
 * `nFrames` is the integer number of (50%-overlapped) averaging frames,
 * `frameLengthS` the frame duration in seconds, `nFft` the FFT size in
 * samples (`round(frameLengthS * fs)`, min 2), and `dF` the resulting
 * frequency resolution `fs / nFft` in Hz.
 */
export interface Resolution { nFrames: number; frameLengthS: number; nFft: number; dF: number; }

/**
 * Snap a (possibly fractional) frame count to a consistent Resolution.
 * `nFrames` is rounded and clamped to [1, total samples]; the other
 * fields are derived from it via the Qt overlap formula.
 */
function finish(nFrames: number, durationS: number, fs: number): Resolution {
  const maxFrames = Math.max(1, Math.round(durationS * fs));   // one frame per sample at most
  nFrames = Math.min(maxFrames, Math.max(1, Math.round(nFrames)));
  const frameLengthS = durationS / (nFrames * (1 - OVERLAP) + OVERLAP);
  const nFft = Math.max(2, Math.round(frameLengthS * fs));
  return { nFrames, frameLengthS, nFft, dF: fs / nFft };
}

/**
 * Resolution from a requested number of frames for a `durationS`-second
 * capture sampled at `fs` Hz. Input is rounded/clamped (see `finish`).
 */
export const fromNFrames = (n: number, durationS: number, fs: number): Resolution =>
  finish(n, durationS, fs);

/**
 * Resolution from a requested frame length in seconds. The frame length
 * is floored at one sample (`1/fs`), converted to a frame count via the
 * inverse overlap formula, then snapped to the nearest integer count —
 * so the returned `frameLengthS` may differ slightly from the request.
 */
export const fromFrameLength = (frameLengthS: number, durationS: number, fs: number): Resolution =>
  finish((durationS / Math.max(frameLengthS, 1 / fs) - OVERLAP) / (1 - OVERLAP), durationS, fs);

/**
 * Resolution from a requested FFT size in samples (min 2, rounded).
 * Equivalent to `fromFrameLength(nFft / fs, ...)`, so the returned
 * `nFft` is re-derived from the snapped integer frame count.
 */
export const fromNFft = (nFft: number, durationS: number, fs: number): Resolution =>
  fromFrameLength(Math.max(2, Math.round(nFft)) / fs, durationS, fs);
