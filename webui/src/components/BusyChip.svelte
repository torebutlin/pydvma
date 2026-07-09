<script lang="ts">
  /**
   * Global "computing" chip (round-8 feedback): a small pulsing pill in the
   * header that appears whenever engine work is in flight — any calc
   * (`actions.busy`, ref-counted), a damping fit, or the pyodide boot
   * itself (`engine.status === 'loading'`, shown as "starting engine…").
   * The worker protocol is strict request/response — there is no mid-calc
   * progress — so the chip is deliberately indeterminate: a soft pulse and
   * a word, no fake percentage.
   *
   * Unobtrusive by design: it appears only after a short delay, so quick
   * calcs never flash it, and fades in/out rather than popping.
   */
  import { fade } from 'svelte/transition';

  let { busy, label = 'computing…' }: {
    /** Whether any tracked work is currently in flight. */
    busy: boolean;
    /** Chip text — e.g. "computing…" or "starting engine…". */
    label?: string;
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
</script>

{#if shown}
  <span class="busy-chip" role="status" data-testid="busy-chip" transition:fade={{ duration: 160 }}>
    <span class="busy-dot" aria-hidden="true"></span>{label}
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
