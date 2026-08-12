<script lang="ts">
  /**
   * Long-calc progress strip with a Stop button (round-11 P7; Tore mid-round:
   * "progress bar when it's taking longer than ~3 s, with a stop").
   *
   * Reads the module-level `engineProgress` store DIRECTLY — the frames come
   * from inside the compute worker (pydvma calls a per-scale
   * `progress_callback`, the worker posts it, the engine store routes it), so
   * nothing has to be threaded through App.
   *
   * Deliberately silent for the first `LONG_CALC_MS`: a normal calc finishes
   * inside that window and must not flash a bar. The gate itself is
   * `longCalcView` — a pure function, unit-tested — and this component only
   * supplies the ticking clock it needs.
   *
   * Stop is a genuine kill: `stopEngine()` terminates the worker and reboots
   * (there is no cancel message a busy pyodide worker could read). Every
   * outstanding calc then rejects with `EngineStopped` and its card unwinds.
   */
  import { engineProgress, longCalcView, stopEngine } from '../lib/stores/engine';

  let { ops, testid = 'calc-progress' }: {
    /**
     * Show only these glue OPS (`'calc_sono'`, `'calc_damping'`), so the Sono
     * card and the damping panel each report their own calc rather than both
     * drawing the same bar. Keyed on the op, not the display label, so
     * rewording a label can never silently empty a card's filter. Omit to
     * show any tracked calc.
     */
    ops?: string[];
    testid?: string;
  } = $props();

  /** Clock tick while a calc is live — drives the 3 s gate and the elapsed read-out. */
  const TICK_MS = 250;
  let now = $state(Date.now());
  const live = $derived($engineProgress !== null);
  $effect(() => {
    if (!live) return;
    now = Date.now();
    const t = setInterval(() => (now = Date.now()), TICK_MS);
    return () => clearInterval(t);
  });

  const view = $derived.by(() => {
    const p = $engineProgress;
    if (p && ops && !ops.includes(p.op)) return null;
    return longCalcView(p, now);
  });

  let stopping = $state(false);
  async function stop() {
    stopping = true;
    try {
      await stopEngine();
    } finally {
      stopping = false;
    }
  }
</script>

{#if view}
  <div class="calc-prog" role="group" aria-label="{view.label} progress" data-testid={testid}>
    <div class="cp-bar" role="progressbar"
      aria-valuemin={0} aria-valuemax={view.total} aria-valuenow={view.done}
      aria-label={view.label}>
      <div class="cp-fill" style="width:{(view.fraction * 100).toFixed(1)}%"></div>
    </div>
    <span class="cp-txt" data-testid="{testid}-text">
      {view.label} — {view.done}/{view.total} ({Math.round(view.fraction * 100)}%) · {view.elapsedS.toFixed(0)} s
    </span>
    <button class="btn cp-stop" onclick={stop} disabled={stopping}
      data-testid="{testid}-stop"
      title="Terminate the calculation and restart the analysis engine (a few seconds)">
      {stopping ? 'stopping…' : 'Stop'}</button>
  </div>
{/if}

<style>
  .calc-prog {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    min-width: 0;
  }
  .cp-bar {
    flex: 1 1 90px;
    min-width: 60px;
    height: 6px;
    border-radius: 3px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    overflow: hidden;
  }
  .cp-fill {
    height: 100%;
    background: var(--blue, #2563eb);
    transition: width 150ms linear;
  }
  .cp-txt {
    font: 11px var(--font-mono);
    color: var(--muted);
    white-space: nowrap;
  }
  .cp-stop { padding: 0 8px; height: 22px; font-size: 11px; }
</style>
