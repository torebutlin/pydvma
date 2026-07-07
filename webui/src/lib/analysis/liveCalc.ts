/**
 * Debounced "live recompute" scheduler for the analysis cards (round-2
 * feedback: PSD / TF / Sono should recompute as soon as a setting or
 * slider changes, not only on the Calc button).
 *
 * A card creates one `createLiveCalc(hasResult, calc)` and calls
 * `schedule()` from every live control's change handler (slider, coupled
 * number entry, quantity/window/channel select). After a short quiet
 * window the scheduler runs `calc` — but ONLY when `hasResult()` is true,
 * so the first compute stays gated behind the explicit Calc button and a
 * tweak made before any result exists never boots the pyodide engine.
 * Rapid changes coalesce to a single trailing call; `cancel()` drops a
 * pending one (e.g. on teardown).
 *
 * Pure and framework-free so the trigger/debounce/gate logic is unit
 * tested with fake timers (`tests/analysis/liveCalc.test.ts`) — the card
 * wiring on top is exercised by the analysis e2e.
 */
export interface LiveCalc {
  /** Debounced, result-gated request to recompute. */
  schedule: () => void;
  /** Drop any pending recompute without firing it. */
  cancel: () => void;
}

/**
 * Build a live-recompute scheduler.
 *
 * @param hasResult gate: only recompute once a first result exists.
 * @param calc the recompute to run (reads the card's current settings).
 * @param ms debounce quiet window in milliseconds (default 150).
 */
export function createLiveCalc(hasResult: () => boolean, calc: () => void, ms = 150): LiveCalc {
  let id: ReturnType<typeof setTimeout> | undefined;
  function schedule(): void {
    if (!hasResult()) return;                 // no first compute yet — stay button-gated
    clearTimeout(id);
    id = setTimeout(() => { id = undefined; calc(); }, ms);
  }
  function cancel(): void {
    clearTimeout(id);
    id = undefined;
  }
  return { schedule, cancel };
}
