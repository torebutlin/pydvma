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
   * monitor's latching clip flag (trips at peak ≥ 0.95, stays lit until
   * reset) and clicking it clears the latch.
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
        <span class="vbar" title={`ch${ch}: peak ${(lv.peak * 100).toFixed(0)}%`}>
          <i style="height:{Math.max(0, Math.min(100, (1 - lv.peak) * 100)).toFixed(0)}%"></i>
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
