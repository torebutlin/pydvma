<script lang="ts">
  /**
   * Shared coupled-resolution control (Stage-2 Plan 1.5, Task R2).
   *
   * Renders ONE frame-count slider (drag = coarse) paired with FOUR text
   * boxes — N frames · frame length (s) · nFFT · Δf (Hz) — every one of
   * which both DISPLAYS and EDITS the resolution. All four are coupled
   * through `resolution.ts` (via `resolveFrom`): editing any box, or
   * dragging the slider, recomputes the consistent
   * {nFrames, frameLengthS, nFft, dF} snapshot and writes back the
   * resulting integer `nFrames` through `onchange`. The parent stores only
   * `nFrames` (the canonical handle); the rest are derived on display.
   *
   * OUT-OF-RANGE (R2 point 3): the text boxes are the source of truth and
   * accept values OUTSIDE the slider range. The slider clamps to its
   * end-stops (`sliderPosition`) and never fights a typed value — type
   * N=500 on a slider that maxes at 128 and the value holds while the
   * thumb pins to 128.
   *
   * DEFAULT RANGE (R2 point 4): the slider range derives from the set's
   * (fs, duration) via `defaultFrameRange` — 1 .. a sane per-record max,
   * not a fixed 1..30.
   *
   * PRECOMPUTE / LIVE vs DEFER (R2 point 5): the coupled read-outs update
   * live on every slider `input` for SMALL sets (cheap closed-form maths,
   * so dragging feels instant). For LARGE sets (`shouldDeferLive`) the
   * live write-back is deferred to slider `change` (release) so a heavy
   * record never stutters mid-drag. Text-box commits always apply
   * immediately regardless of size.
   *
   * MIXED (R2 / R1 carry): when `mixed` is set (target 'all' with sets
   * that disagree) the boxes show a "–mixed–" placeholder; the first edit
   * still routes through `onchange` and, being an 'all' patch upstream,
   * makes the sets agree.
   */
  import {
    defaultFrameRange,
    sliderPosition,
    resolveFrom,
    shouldDeferLive,
    type ResolutionQuantity,
  } from '../lib/analysis/resolutionControl';

  let {
    fs,
    durationS,
    nFrames,
    mixed = false,
    onchange,
  }: {
    /** Target set's sample rate (Hz). */
    fs: number;
    /** Target set's capture duration (s). */
    durationS: number;
    /** Current canonical frame count (the stored handle). */
    nFrames: number;
    /** Show a "–mixed–" placeholder (target 'all', sets disagree). */
    mixed?: boolean;
    /** Write back the resolved integer frame count. */
    onchange: (nFrames: number) => void;
  } = $props();

  // Slider range + precompute gate both derive from the set metadata.
  const range = $derived(defaultFrameRange(durationS, fs));
  const nSamples = $derived(Math.round(durationS * fs));
  const defer = $derived(shouldDeferLive(nSamples));

  // Full coupled snapshot for the current frame count (drives every box).
  const res = $derived(resolveFrom('frames', nFrames, durationS, fs));
  // Where the thumb sits: clamps to the end-stops for out-of-range values.
  const thumb = $derived(sliderPosition(nFrames, range));

  /** Resolve from any quantity and write back the integer frame count. */
  function commit(quantity: ResolutionQuantity, value: number) {
    if (!Number.isFinite(value)) return;
    onchange(resolveFrom(quantity, value, durationS, fs).nFrames);
  }

  // Slider: live for small sets, deferred to release for large ones.
  function onSliderInput(v: number) {
    if (!defer) commit('frames', v);
  }
  function onSliderChange(v: number) {
    if (defer) commit('frames', v);
  }
</script>

<input
  type="range"
  min={range.min}
  max={range.max}
  value={thumb}
  oninput={(e) => onSliderInput(+e.currentTarget.value)}
  onchange={(e) => onSliderChange(+e.currentTarget.value)}
  style="width:104px"
  aria-label="resolution frames"
/>
<span class="ml">N</span>
<input
  type="number" min="1" step="1"
  value={mixed ? '' : res.nFrames}
  placeholder={mixed ? '–mixed–' : ''}
  onchange={(e) => commit('frames', +e.currentTarget.value)}
  style="width:56px" aria-label="N frames"
/>
<span class="ml">frame&nbsp;s</span>
<input
  type="number" step="0.01" min="0"
  value={mixed ? '' : res.frameLengthS.toFixed(2)}
  placeholder={mixed ? '–mixed–' : ''}
  onchange={(e) => commit('frameLength', +e.currentTarget.value)}
  style="width:64px" aria-label="frame length seconds"
/>
<span class="ml">nFFT</span>
<input
  type="number" step="1" min="2"
  value={mixed ? '' : res.nFft}
  placeholder={mixed ? '–mixed–' : ''}
  onchange={(e) => commit('nFft', +e.currentTarget.value)}
  style="width:64px" aria-label="nFFT"
/>
<span class="ml">Δf</span>
<input
  type="number" step="0.01" min="0"
  value={mixed ? '' : res.dF.toFixed(2)}
  placeholder={mixed ? '–mixed–' : ''}
  onchange={(e) => commit('dF', +e.currentTarget.value)}
  style="width:64px" aria-label="delta f Hz"
/>
<span class="note">Hz</span>
