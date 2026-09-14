<script lang="ts">
  /**
   * Vertical input-level bars + latching CLIP pill (design spec §8;
   * visuals ported from the `.vbar` / `.clip-pill` blocks of
   * round2-bench.html).  Shared by the persistent MiniMonitor
   * (`variant="mini"`, 9 px bars) and the expanded Live scope's levels
   * column (`variant="big"`, 22 px bars with per-channel labels).
   *
   * Each bar is a bottom-up green→amber→red gradient masked from the top
   * by the inverse of that channel's peak level.  The CLIP pill reads the
   * monitor's latching clip flag (trips at peak ≥ 95 % of full scale, stays
   * lit until reset) and clicking it clears the latch.
   *
   * `monitor.levels` is in the STREAM's own units, which are volts on an NI
   * card (full scale = the configured `±VmaxNI` rail, 5 or 10 V) and a
   * normalised 1.0 on Web Audio / an uncalibrated soundcard.  Both the bar
   * fill and the tooltip are therefore taken as a fraction of
   * `monitor.fullScale` — reading them against a hard-coded 1.0 pegged every
   * bar and lit CLIP on healthy NI signals (3C6 lab, 2026-09).
   */
  import type { MonitorStore } from '../lib/stores/monitor';

  let {
    monitor,
    variant = 'mini',
    labels,
  }: {
    monitor: MonitorStore;
    /**
     * - `mini` — 9 px bars in the docked MiniMonitor.
     * - `big` — 22 px bars with per-channel labels in the Live scope.
     * - `rail` — 8 px bars + a compact 'C' clip pill for the narrow-mode
     *   data rail's mini-monitor strip (round-5 item 14); capped to the
     *   first two channels so the 72 px rail stays clean.
     */
    variant?: 'mini' | 'big' | 'rail';
    /** Optional per-channel labels (shown under each bar in the big variant). */
    labels?: (ch: number) => string;
  } = $props();

  const levels = $derived(monitor.levels);
  const clipLatched = $derived(monitor.clipLatched);
  const fullScaleStore = $derived(monitor.fullScale);
  const isVoltsStore = $derived(monitor.fullScaleIsVolts);
  /** Full scale in the levels' own units; guarded so a bad value never divides by ~0. */
  const fullScale = $derived(
    Number.isFinite($fullScaleStore) && $fullScaleStore > 0 ? $fullScaleStore : 1,
  );

  /**
   * Bars to show — always at least the channels we have levels for. The rail
   * strip caps to the first two so it fits the narrow rail (mockup spirit).
   */
  const bars = $derived(
    $levels.length > 0 ? (variant === 'rail' ? $levels.slice(0, 2) : $levels) : [],
  );

  function label(ch: number): string {
    return labels ? labels(ch) : `ch_${ch}`;
  }

  /** Peak as a fraction of full scale, clamped to the bar's 0–1 range. */
  function frac(peak: number): number {
    return Math.max(0, Math.min(1, peak / fullScale));
  }

  /**
   * Tooltip: the percentage of full scale, plus the raw reading in volts
   * once the scale has a voltage meaning (NI, or a calibrated jack).
   */
  function barTitle(ch: number, peak: number): string {
    const pct = `ch${ch}: peak ${(frac(peak) * 100).toFixed(0)}%`;
    return $isVoltsStore ? `${pct} (${peak.toPrecision(3)} V of ${fullScale} V)` : pct;
  }
</script>

<div
  class="levelbars"
  class:big={variant === 'big'}
  class:mini={variant === 'mini'}
  class:rail={variant === 'rail'}
>
  <div class="bars">
    {#each bars as lv, ch (ch)}
      <div class="col">
        <span class="vbar" title={barTitle(ch, lv.peak)}>
          <i style="height:{((1 - frac(lv.peak)) * 100).toFixed(0)}%"></i>
        </span>
        {#if variant === 'big'}<small>{label(ch)}</small>{/if}
      </div>
    {/each}
  </div>
  {#if variant === 'rail'}
    <!-- Rail strip: a non-interactive clip INDICATOR (the whole strip is a
         single navigate-to-Live button, so no nested button here). Resetting
         the latch lives in the MiniMonitor / Live scope pills. -->
    <span
      class="clip-pill"
      class:hot={$clipLatched}
      title="Input clip indicator"
      data-testid="clip-pill"
    >C</span>
  {:else}
    <button
      class="clip-pill"
      class:hot={$clipLatched}
      title="Latching clip flag — click to reset"
      onclick={() => monitor.resetClip()}
      data-testid="clip-pill"
    >CLIP</button>
  {/if}
</div>

<style>
  .levelbars {
    display: flex;
    align-items: stretch;
    gap: 6px;
  }
  .bars {
    display: flex;
    align-items: flex-end;
    gap: 4px;
  }
  .col {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    justify-content: flex-end;
  }
  .vbar {
    border-radius: 4px;
    overflow: hidden;
    position: relative;
    background: linear-gradient(0deg, #16a34a 70%, #d97706 88%, #dc2626);
    display: block;
  }
  .mini .vbar {
    width: 9px;
    height: 52px;
  }
  .rail .vbar {
    width: 8px;
    height: 36px;
  }
  .big .vbar {
    width: 22px;
    height: 100%;
    min-height: 60px;
  }
  .big .col {
    height: 100%;
  }
  .vbar i {
    position: absolute;
    left: 0;
    right: 0;
    top: 0;
    height: 70%;
    background: var(--level-track);
    transition: height 60ms linear;
  }
  .big small {
    font: 11px var(--font-mono);
    color: var(--muted);
  }
  .clip-pill {
    align-self: flex-start;
    font: 600 9.5px var(--font-mono);
    letter-spacing: 0.06em;
    color: var(--muted-2);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 1px 4px;
    background: var(--control-bg);
    cursor: pointer;
    user-select: none;
  }
  .rail .clip-pill {
    font-size: 7.5px;
    padding: 0 2px;
  }
  .clip-pill.hot {
    color: #fff;
    background: var(--danger-strong);
    border-color: var(--danger-strong);
  }
</style>
