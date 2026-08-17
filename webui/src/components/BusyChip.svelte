<script lang="ts">
  /**
   * Global "computing" chip (round-8 feedback): a small pulsing pill in the
   * header that appears whenever engine work is in flight — any calc
   * (`actions.busy`, ref-counted), a damping fit, or the pyodide boot
   * itself (`engine.status === 'loading'`, shown as "starting engine…").
   * Most work is still indeterminate — a soft pulse and a word, no fake
   * percentage. Round-11 (P7) added the exception: the CWT paths report
   * genuine per-scale progress from inside the worker, and when a frame is
   * live (`engineProgress`, read DIRECTLY from the engine store module — no
   * App wiring) the pulse becomes a determinate FILL behind the chip's text
   * and the label names the op. No frames ⇒ the old behaviour, unchanged.
   *
   * Unobtrusive by design: it appears only after a short delay, so quick
   * calcs never flash it, and fades in/out rather than popping.
   */
  import { fade } from 'svelte/transition';
  import { engineProgress } from '../lib/stores/engine';
  import type { EngineHostKind } from '../lib/worker/selectEngine';

  let { busy, label = 'computing…', engineHost = null }: {
    /** Whether any tracked work is currently in flight. */
    busy: boolean;
    /** Chip text — e.g. "computing…" or "starting engine…". */
    label?: string;
    /**
     * Which engine host is answering compute (`engine.host`): the pyodide
     * worker in the browser, or a native CPython `pydvma-serve` over the
     * `/engine` socket. `null` until the transport has been resolved. Shown
     * in the tooltip only — the two hosts compute the same answers, so this
     * is provenance, not a mode the user has to act on.
     */
    engineHost?: EngineHostKind | null;
  } = $props();

  /** Delay before showing (ms) — sub-perceptual calcs never flash the chip. */
  const SHOW_DELAY_MS = 300;

  let shown = $state(false);
  $effect(() => {
    if (!busy) {
      shown = false;
      return;
    }
    const t = setTimeout(() => (shown = true), SHOW_DELAY_MS);
    return () => clearTimeout(t);
  });

  // Determinate only while a tracked calc is actually reporting (total > 0).
  const prog = $derived($engineProgress);
  const determinate = $derived(!!prog && prog.total > 0);
  const pct = $derived(
    determinate ? Math.round(100 * Math.min(1, Math.max(0, prog!.done / prog!.total))) : 0,
  );
  // The op's own name beats the generic word once we know what is running —
  // but "starting engine…" (a caller-set label with no frames) always wins.
  const text = $derived(determinate ? `${prog!.label} ${pct}%` : label);
  // Tooltip-only host provenance. `null` says "resolving…" rather than
  // guessing "browser": on the factory path the chip can already be up
  // ("starting engine…") while the transport is still being decided.
  const hostLabel = $derived(
    engineHost === 'native' ? 'local Python'
      : engineHost === 'pyodide' ? 'browser' : 'resolving…');
</script>

{#if shown}
  <!-- role="status" (a live region) is right for the chip: the percentage is
       announced as part of the TEXT, so no aria-value* here — those belong to
       role="progressbar", which this is not (the real bar is CalcProgress). -->
  <span class="busy-chip" class:determinate role="status" data-testid="busy-chip"
    transition:fade={{ duration: 160 }}
    data-progress={determinate ? pct : undefined}
    data-engine-host={engineHost ?? 'unresolved'}
    title={`${text} — engine: ${hostLabel}`}>
    {#if determinate}
      <span class="busy-fill" aria-hidden="true" style="width:{pct}%"></span>
    {/if}
    <span class="busy-dot" aria-hidden="true"></span><span class="busy-text">{text}</span>
  </span>
{/if}

<style>
  .busy-chip {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    height: 26px;
    padding: 0 12px;
    border-radius: 13px;
    border: 1px solid var(--border);
    background: var(--surface-2);
    font: 12px var(--font-mono);
    color: var(--muted);
    white-space: nowrap;
  }
  /* Determinate: the fill sits BEHIND the dot + text (both lifted by
     position/z-index), so the chip keeps its size and the text stays legible
     as the bar sweeps under it. */
  .busy-chip.determinate { position: relative; overflow: hidden; }
  .busy-fill {
    position: absolute;
    inset: 0 auto 0 0;
    background: color-mix(in srgb, var(--blue, #2563eb) 18%, transparent);
    transition: width 120ms linear;
  }
  .busy-text { position: relative; }
  .determinate .busy-dot { position: relative; animation: none; opacity: 0.9; }
  .busy-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--blue, #2563eb);
    animation: busy-pulse 1.4s ease-in-out infinite;
  }
  @keyframes busy-pulse {
    0%, 100% { opacity: 0.35; transform: scale(0.85); }
    50% { opacity: 1; transform: scale(1); }
  }
  @media (prefers-reduced-motion: reduce) {
    .busy-dot { animation: none; opacity: 0.8; }
  }
</style>
