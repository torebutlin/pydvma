<script lang="ts">
  /**
   * Per-set calibration dialog (Wave-A Task A2; visuals ported from the
   * "calibrate stub modal" block of dev/mockups/round2-bench.html:685-701).
   * Opened from a tray card's ⋯ / Calibrate button for ONE set, it shows one
   * row per channel — the channel's display label (custom relabels
   * respected), a **sensitivity** numeric input (volts per engineering unit),
   * and a unit `<select>` (V / m/s² / N / Pa, exactly the mockup's options).
   *
   * What the user types vs what gets stored: the input is a SENSITIVITY (the
   * transducer's V/unit rating, e.g. 0.1 V/g for a 100 mV/g accelerometer).
   * The parent converts it to pydvma's stored `channel_cal_factors[ch] =
   * 1/sensitivity` (see `lib/model/calibration.ts`) — a plain multiplier
   * applied at display time. So a factor of 10 (sensitivity 0.1) plots a 0.5 V
   * sample as 5 units.
   *
   * The "known-input calibration…" button is disabled (a guided
   * reference-signal flow is a later stage) — kept, not removed, because it is
   * in the mockup and signposts the roadmap.
   *
   * DUMB component: it receives the initial per-channel `rows`, edits LOCAL
   * copies, and emits the edited sensitivity+unit on Apply; the parent owns the
   * sensitivity→factor conversion, persistence, and any toast. It is mounted
   * only while open (keyed by setId), so local state seeds cleanly per open.
   */
  import { CAL_UNITS, type CalRow } from '../lib/model/calibration';

  let {
    setName,
    rows,
    onApply,
    onCancel,
  }: {
    setName: string;
    rows: CalRow[];
    /** Per-channel edited values, index-aligned to `rows`. */
    onApply: (results: { sensitivity: number; unit: string }[]) => void;
    onCancel: () => void;
  } = $props();

  // Local editable copies, seeded ONCE from the incoming rows. Intentional:
  // the dialog is remounted per set (keyed by setId in Tray), so `rows` never
  // changes during its lifetime — the snapshot is exactly what we want.
  // svelte-ignore state_referenced_locally
  let sens = $state<number[]>(rows.map((r) => r.sensitivity));
  // svelte-ignore state_referenced_locally
  let units = $state<string[]>(rows.map((r) => r.unit));

  /**
   * The unit options for a row: the mockup's four presets, plus the row's
   * CURRENT unit when it is non-standard (e.g. a legacy `'m/s'`), so opening
   * and re-applying never silently rewrites a unit the picker can't offer.
   */
  function unitOptions(current: string): string[] {
    return (CAL_UNITS as readonly string[]).includes(current)
      ? [...CAL_UNITS]
      : [current, ...CAL_UNITS];
  }

  /** Sensitivity denominator label, mirroring the mockup ("V / V", "V / (g)"). */
  function sensLabel(unit: string): string {
    return unit === 'V' ? 'V / V' : `V / (${unit})`;
  }

  function apply() {
    onApply(rows.map((_, i) => ({ sensitivity: Number(sens[i]), unit: units[i] })));
  }

  // Close on Esc / backdrop click (mirrors the mockup's overlay dismiss).
  function onOverlayKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') onCancel();
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div
  class="overlay"
  data-testid="cal-overlay"
  role="dialog"
  aria-modal="true"
  aria-label={`Calibrate ${setName}`}
  tabindex="-1"
  onclick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
  onkeydown={onOverlayKeydown}
>
  <div class="modal">
    <div class="modal-title">Calibrate — {setName}</div>

    {#each rows as row, i (row.ch)}
      <div class="mrow" data-testid={`cal-row-${row.ch}`}>
        <label for={`cal-sens-${row.ch}`} class="ch-name mono">{row.label}</label>
        <input
          id={`cal-sens-${row.ch}`}
          type="number"
          step="0.001"
          data-testid={`cal-sens-${row.ch}`}
          bind:value={sens[i]}
          style="width:88px"
        />
        <span class="ml">{sensLabel(units[i])}</span>
        <select
          data-testid={`cal-unit-${row.ch}`}
          bind:value={units[i]}
          aria-label={`Unit for ${row.label}`}
        >
          {#each unitOptions(row.unit) as u (u)}
            <option value={u}>{u}</option>
          {/each}
        </select>
      </div>
    {/each}

    <div class="mrow">
      <button class="btn" disabled title="guided calibration arrives later">
        known-input calibration…
      </button>
    </div>

    <div class="mrow end">
      <button class="btn" data-testid="cal-cancel" onclick={onCancel}>Cancel</button>
      <button class="btn indigo" data-testid="cal-apply" onclick={apply}>Apply</button>
    </div>
  </div>
</div>

<style>
  /* Ported verbatim from round2-bench.html (.overlay/.modal/.mrow/.ml/.btn). */
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 330;
    background: rgba(23, 32, 58, 0.42);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .modal {
    width: 380px;
    background: #fff;
    border-radius: 12px;
    padding: 16px 18px 14px;
    box-shadow: 0 24px 70px rgba(16, 24, 40, 0.35);
  }
  .modal-title {
    font-weight: 700;
    font-size: 14px;
    margin-bottom: 10px;
  }
  .mrow {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 10px 0;
  }
  .mrow.end {
    justify-content: flex-end;
    margin-top: 16px;
  }
  .ch-name {
    font-size: 12px;
    color: var(--text);
    width: 92px;
    flex: 0 0 auto;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mono {
    font-family: var(--font-mono);
  }
  .ml {
    font-size: 11px;
    color: var(--muted);
    white-space: nowrap;
  }
  input[type='number'],
  select {
    height: 26px;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0 6px;
    font: inherit;
    font-size: 12px;
    background: #fff;
    color: var(--text);
  }
  select {
    margin-left: auto;
  }
  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border);
    background: #fff;
    color: var(--text);
    font-weight: 500;
    cursor: pointer;
    white-space: nowrap;
    font-family: inherit;
    height: 28px;
    padding: 0 12px;
    font-size: 12.5px;
    border-radius: 7px;
  }
  .btn:hover:not(:disabled) {
    border-color: #c6cbd6;
    background: #fafbfc;
  }
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .btn.indigo {
    background: var(--indigo, #4f46e5);
    border-color: var(--indigo, #4f46e5);
    color: #fff;
    font-weight: 600;
  }
  .btn.indigo:hover:not(:disabled) {
    background: #4338ca;
  }
</style>
