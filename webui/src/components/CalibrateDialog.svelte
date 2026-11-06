<script lang="ts">
  /**
   * Per-set calibration dialog (Wave-A Task A2; visuals ported from the
   * "calibrate stub modal" block of dev/mockups/round2-bench.html:685-701).
   * Opened from a tray card's ⋯ / Calibrate button for ONE set, it shows one
   * row per channel — the channel's display label (custom relabels
   * respected), a **sensitivity** numeric input (source units per engineering
   * unit — volts where the device delivers volts, full-scale units where its
   * voltage scale is unknown; see `sourceUnit`), and a unit `<select>`
   * (V / m/s² / N / Pa, exactly the mockup's options).
   *
   * What the user types vs what gets stored: the input is a SENSITIVITY (the
   * transducer's V/unit rating, e.g. 0.1 V/g for a 100 mV/g accelerometer).
   * The parent converts it to pydvma's stored `channel_cal_factors[ch] =
   * 1/sensitivity` (see `lib/model/calibration.ts`) — a plain multiplier
   * applied at display time. So a factor of 10 (sensitivity 0.1) plots a 0.5 V
   * sample as 5 units.
   *
   * TRANSFER FUNCTION section (when the set has a TF, `tfRows`): a factor on
   * the measured RATIO itself, for when the TF can be calibrated but the
   * sensors cannot — 3C6's free mass, `|a/F| = 1/m`. Each line takes a plain
   * MULTIPLIER ("the factor by which the measured TF must be multiplied"), not
   * a sensitivity, and its unit as numerator / denominator. Left blank, a line
   * follows the channel calibration (its ratio is shown as the placeholder,
   * and the unit pickers show the channel units, disabled); a factor typed in
   * overrides it, and ↺ goes back. For a TF-ONLY set (`tfOrphan`) there is no
   * channel calibration underneath: the channel rows are hidden and the TF
   * rows edit the set's own stored factors, so every line always has one.
   *
   * REFERENCE TONE: each channel row has a "ref tone" button opening an inline
   * panel that derives the sensitivity from a recorded calibrator tone (a
   * 94 dB SPL / 1 kHz acoustic calibrator, or a handheld accelerometer
   * calibrator): pick the set holding the recording, state the calibrator's
   * level and frequency, Measure. The number lands in the row's sensitivity
   * field (editing it by hand afterwards drops the reference), and Apply then
   * records the calibration as `reference_tone` with the level and frequency.
   *
   * DUMB component: it receives the initial per-channel `rows` (and `tfRows`),
   * edits LOCAL copies, and emits the edited values on Apply; the parent owns
   * the sensitivity→factor conversion, persistence, and any toast. It is
   * mounted only while open (keyed by setId), so local state seeds cleanly per
   * open.
   */
  import {
    CAL_UNITS, referenceDefaults, referenceRms, type CalRow, type TfCalLine, type TfCalRow,
  } from '../lib/model/calibration';

  /** What the reference-tone measurement returns (see `actions.measureReferenceTone`). */
  type RefMeasurement = {
    sensitivity: number; measuredRms: number; peakFreq: number;
    warnings: string[]; clipped: boolean;
  };

  let {
    setName,
    rows,
    tfRows = null,
    tfOrphan = false,
    tfPending = false,
    sourceUnit = 'V',
    rowSourceUnits = null,
    refSets = [],
    currentSetId = null,
    measureReference = null,
    gainAtStop = null,
    onApply,
    onCancel,
  }: {
    setName: string;
    rows: CalRow[];
    /** The set's TF lines, or `null` when it has no transfer function. */
    tfRows?: TfCalRow[] | null;
    /** A TF-only set: no channel rows, and every TF line carries a factor. */
    tfOrphan?: boolean;
    /** No TF yet on a set that could have one: say how to get the section. */
    tfPending?: boolean;
    /**
     * What the STORED samples are, and so what a sensitivity is measured
     * against: `'V'` on a card that delivers volts (an NI task, or a
     * characterised soundcard), `'FS'` on one whose voltage scale is unknown,
     * where the samples are full-scale fractions. Getting this wrong is
     * silent — the calibrated numbers simply come out scaled by the unknown
     * full scale — so the label says which. Defaults to `'V'`.
     */
    sourceUnit?: 'V' | 'FS';
    /**
     * Per-channel override of `sourceUnit`, index-aligned to `rows`: a device
     * with a preamp per input can deliver volts on one channel and full-scale
     * units on another (an iD44 channel with a stated gain vs one without).
     */
    rowSourceUnits?: ('V' | 'FS')[] | null;
    /** Sets with recorded time data, for the reference tone's set picker. */
    refSets?: { id: number; name: string; nChannels: number }[];
    /** The set this dialog calibrates: the picker's default. */
    currentSetId?: number | null;
    /** Measure a recorded reference tone; absent hides the reference button. */
    measureReference?: ((
      setId: number, ch: number, refRms: number, freq: number,
    ) => Promise<RefMeasurement>) | null;
    /**
     * Whether the gain of channel `ch` of set `setId` is stated AND at an end
     * of its mode's gain range (a detent the knob can be returned to); when it
     * is not, the panel warns that the calibration holds only while the knob
     * and pad stay put.
     */
    gainAtStop?: ((setId: number, ch: number) => boolean) | null;
    /**
     * Per-channel edited values, index-aligned to `rows` (`null` for a TF-only
     * set, which shows no channel rows), and the TF lines (`null` when there
     * is no TF section): `line: null` = follow the channel calibration.
     * `note` is the free-text calibration note ('' when empty); the parent
     * saves it with the provenance of each channel that changed.
     */
    onApply: (
      results: {
        sensitivity: number; unit: string;
        reference?: { level: number; level_unit: string; freq: number };
      }[] | null,
      tf: { ch: number; line: TfCalLine | null }[] | null,
      note: string,
    ) => void;
    onCancel: () => void;
  } = $props();

  // Local editable copies, seeded ONCE from the incoming rows. Intentional:
  // the dialog is remounted per set (keyed by setId in Tray), so `rows` never
  // changes during its lifetime — the snapshot is exactly what we want.
  // svelte-ignore state_referenced_locally
  let sens = $state<number[]>(rows.map((r) => r.sensitivity));
  // svelte-ignore state_referenced_locally
  let units = $state<string[]>(rows.map((r) => r.unit));
  // Reference-tone panels, one slot per row. `refLevel`/`refFreq` hold what the
  // user typed (null = the default for the row's unit); `refMeta` is the
  // reference the CURRENT sensitivity was measured from (null once edited).
  // svelte-ignore state_referenced_locally
  let refOpen = $state<boolean[]>(rows.map(() => false));
  // svelte-ignore state_referenced_locally
  let refSet = $state<(number | null)[]>(rows.map(() => currentSetId));
  // svelte-ignore state_referenced_locally
  let refLevel = $state<(string | null)[]>(rows.map(() => null));
  // svelte-ignore state_referenced_locally
  let refFreq = $state<(string | null)[]>(rows.map(() => null));
  // svelte-ignore state_referenced_locally
  let refBusy = $state<boolean[]>(rows.map(() => false));
  // svelte-ignore state_referenced_locally
  let refWarnings = $state<string[][]>(rows.map(() => []));
  // svelte-ignore state_referenced_locally
  let refError = $state<string[]>(rows.map(() => ''));
  // svelte-ignore state_referenced_locally
  let refMeta = $state<({ level: number; level_unit: string; freq: number } | null)[]>(
    rows.map(() => null));

  const levelUnit = (unit: string) => referenceDefaults(unit).levelUnit;
  const levelText = (i: number) => refLevel[i] ?? String(referenceDefaults(units[i]).level);
  const freqText = (i: number) => refFreq[i] ?? String(referenceDefaults(units[i]).freq);
  /** The calibrator's rms in engineering units, or NaN when not usable. */
  const refRmsOf = (i: number) =>
    referenceRms(Number(levelText(i)), units[i], Number(freqText(i)));
  function refInvalid(i: number): string {
    const level = Number(levelText(i));
    if (!Number.isFinite(level) || level <= 0) return 'The level must be a number above zero.';
    return Number.isNaN(refRmsOf(i)) ? 'The frequency must be a number above zero.' : '';
  }

  async function measure(i: number) {
    const setId = refSet[i];
    if (!measureReference || setId === null || refInvalid(i)) return;
    refBusy[i] = true;
    refError[i] = '';
    refWarnings[i] = [];
    try {
      const r = await measureReference(setId, rows[i].ch, refRmsOf(i), Number(freqText(i)));
      if (Number.isFinite(r.sensitivity) && r.sensitivity > 0) {
        sens[i] = Number(r.sensitivity.toPrecision(5));
        refMeta[i] = {
          level: Number(levelText(i)), level_unit: levelUnit(units[i]), freq: Number(freqText(i)),
        };
      } else {
        refError[i] = 'No usable sensitivity was measured.';
      }
      refWarnings[i] = r.warnings;
    } catch (e) {
      refError[i] = e instanceof Error ? e.message : String(e);
    } finally {
      refBusy[i] = false;
    }
  }

  /** Free-text note saved with the calibration provenance of changed channels. */
  let note = $state('');

  // TF section, seeded the same way. The factor is edited as TEXT so a blank
  // ("follow the channels") and a typo can be told apart from a number.
  /** A factor as a HINT (placeholder, tooltip): up to 6 significant figures. */
  function fmt(x: number): string {
    return Number.isFinite(x) ? String(Number(x.toPrecision(6))) : '';
  }
  // A stored factor seeds the field at FULL precision (`String` is the
  // shortest exact round trip), so Apply on an untouched row writes back
  // exactly what was there rather than a rounded copy.
  // svelte-ignore state_referenced_locally
  let tfFactor = $state<string[]>((tfRows ?? []).map((r) =>
    r.override ? String(r.override.factor) : tfOrphan ? String(r.ratio) : ''));
  // svelte-ignore state_referenced_locally
  let tfNum = $state<string[]>((tfRows ?? []).map((r) => r.num));
  // svelte-ignore state_referenced_locally
  let tfDen = $state<string[]>((tfRows ?? []).map((r) => r.den));

  /** A field's factor: a number, `null` for blank, `NaN` for something else. */
  function parseFactor(text: string): number | null {
    const t = text.trim();
    if (t === '') return null;
    const v = Number(t);
    return Number.isFinite(v) && v !== 0 ? v : NaN;
  }
  /** Blank is allowed only where a line can fall back on the channels. */
  function factorInvalid(i: number): boolean {
    const v = parseFactor(tfFactor[i] ?? '');
    return Number.isNaN(v) || (tfOrphan && v === null);
  }
  const anyInvalid = $derived(tfFactor.some((_, i) => factorInvalid(i)));

  /** Back to the channel calibration: blank factor, channel units shown. */
  function resetTf(i: number) {
    const r = tfRows![i];
    tfFactor[i] = '';
    tfNum[i] = r.chanNum;
    tfDen[i] = r.chanDen;
  }
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

  /**
   * Sensitivity label, mirroring the mockup ("V / V", "V / (g)") but with the
   * NUMERATOR taken from what the samples actually are: `FS / (g)` where the
   * device's voltage scale is unknown, so the operator is not invited to enter
   * a volts-per-unit rating against full-scale-unit data.
   */
  function sensLabel(unit: string, i: number): string {
    const src = rowSourceUnits?.[i] ?? sourceUnit;
    return unit === src ? `${src} / ${src}` : `${src} / (${unit})`;
  }

  function apply() {
    if (anyInvalid) return;
    const tf = tfRows
      ? tfRows.map((r, i) => {
        const v = parseFactor(tfFactor[i]);
        return { ch: r.ch, line: v === null ? null : { factor: v, num: tfNum[i], den: tfDen[i] } };
      })
      : null;
    onApply(
      tfOrphan ? null : rows.map((_, i) => {
        const reference = refMeta[i];
        return reference
          ? { sensitivity: Number(sens[i]), unit: units[i], reference }
          : { sensitivity: Number(sens[i]), unit: units[i] };
      }),
      tf,
      note.trim(),
    );
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

    {#if sourceUnit !== 'V'}
      <p class="src-note" data-testid="cal-source-note">
        This device's voltage scale is not known, so the samples are in
        full-scale units — enter each sensitivity as FS per engineering unit.
        Set the full scale in Setup to work in volts instead.
      </p>
    {/if}

    {#if !tfOrphan}
    {#each rows as row, i (row.ch)}
      <div class="mrow" data-testid={`cal-row-${row.ch}`}>
        <label for={`cal-sens-${row.ch}`} class="ch-name mono">{row.label}</label>
        <input
          id={`cal-sens-${row.ch}`}
          type="number"
          step="0.001"
          data-testid={`cal-sens-${row.ch}`}
          bind:value={sens[i]}
          oninput={() => { refMeta[i] = null; }}
          style="width:88px"
        />
        <span class="ml">{sensLabel(units[i], i)}</span>
        <select
          data-testid={`cal-unit-${row.ch}`}
          bind:value={units[i]}
          aria-label={`Unit for ${row.label}`}
        >
          {#each unitOptions(row.unit) as u (u)}
            <option value={u}>{u}</option>
          {/each}
        </select>
        {#if measureReference && refSets.length}
          <button
            class="btn small"
            data-testid={`cal-ref-${row.ch}`}
            aria-expanded={refOpen[i]}
            title="calibrate from a recorded reference tone"
            onclick={() => { refOpen[i] = !refOpen[i]; }}
          >ref tone</button>
        {/if}
      </div>
      {#if refOpen[i] && measureReference}
        {@const invalid = refInvalid(i)}
        {@const pickedSet = refSet[i]}
        <div class="ref-panel" data-testid={`cal-ref-panel-${row.ch}`}>
          <div class="mrow">
            <label for={`cal-ref-set-${row.ch}`} class="ml">Recording</label>
            <select
              id={`cal-ref-set-${row.ch}`}
              data-testid="cal-ref-set"
              bind:value={refSet[i]}
            >
              {#each refSets as s (s.id)}
                <option value={s.id}>{s.name}</option>
              {/each}
            </select>
          </div>
          <div class="mrow">
            <label for={`cal-ref-level-${row.ch}`} class="ml">Calibrator</label>
            <input
              id={`cal-ref-level-${row.ch}`}
              type="text"
              inputmode="decimal"
              data-testid="cal-ref-level"
              value={levelText(i)}
              oninput={(e) => { refLevel[i] = e.currentTarget.value; }}
              style="width:64px"
            />
            <span class="ml" data-testid="cal-ref-level-unit">{levelUnit(units[i])}</span>
            <span class="ml">at</span>
            <input
              type="text"
              inputmode="decimal"
              data-testid="cal-ref-freq"
              aria-label="Calibrator frequency in Hz"
              value={freqText(i)}
              oninput={(e) => { refFreq[i] = e.currentTarget.value; }}
              style="width:64px"
            />
            <span class="ml">Hz</span>
            <button
              class="btn small"
              data-testid="cal-ref-measure"
              disabled={!!invalid || refBusy[i] || pickedSet === null}
              onclick={() => measure(i)}
            >{refBusy[i] ? 'Measuring…' : 'Measure'}</button>
          </div>
          {#if invalid}
            <p class="src-note warn" data-testid="cal-ref-invalid">{invalid}</p>
          {/if}
          {#if refError[i]}
            <p class="src-note warn" data-testid="cal-ref-error">{refError[i]}</p>
          {/if}
          {#if refWarnings[i].length}
            <ul class="src-note warn" data-testid="cal-ref-warning">
              {#each refWarnings[i] as w (w)}<li>{w}</li>{/each}
            </ul>
          {/if}
          {#if pickedSet !== null && gainAtStop && !gainAtStop(pickedSet, row.ch)}
            <p class="src-note" data-testid="cal-ref-stop-note">
              Valid only while this channel's gain knob and pad stay where they were.
            </p>
          {/if}
        </div>
      {/if}
    {/each}
    {/if}

    {#if !tfOrphan}
      <div class="mrow">
        <label for="cal-note" class="ch-name">Note</label>
        <input
          id="cal-note"
          type="text"
          data-testid="cal-note"
          bind:value={note}
          placeholder="how this calibration was obtained (optional)"
          style="flex:1"
        />
      </div>
    {/if}

    {#if tfRows && tfRows.length}
      <div class="tf-section" data-testid="cal-tf-section">
        <div class="section-title">Transfer function</div>
        <p class="src-note">
          {#if tfOrphan}
            This set is a transfer function only, so its calibration is the
            factor each line is multiplied by.
          {:else}
            Calibrate the transfer function directly — for example from a known
            mass — when the individual sensors are not calibrated. A factor here
            multiplies the measured ratio and replaces the one the channels
            imply; leave it blank to follow them.
          {/if}
        </p>
        {#each tfRows as row, i (row.ch)}
          {@const set = parseFactor(tfFactor[i]) !== null}
          <div class="mrow" data-testid={`cal-tf-row-${row.ch}`}>
            <label for={`cal-tf-factor-${row.ch}`} class="ch-name mono">{row.label}</label>
            <span class="ml">×</span>
            <input
              id={`cal-tf-factor-${row.ch}`}
              type="text"
              inputmode="decimal"
              class:invalid={factorInvalid(i)}
              data-testid={`cal-tf-factor-${row.ch}`}
              placeholder={tfOrphan ? '' : fmt(row.ratio)}
              title={tfOrphan ? 'multiplier on the stored TF' : `channels give ×${fmt(row.ratio)}`}
              bind:value={tfFactor[i]}
              style="width:80px"
            />
            <select
              class="tf-unit"
              data-testid={`cal-tf-num-${row.ch}`}
              bind:value={tfNum[i]}
              disabled={!set}
              aria-label={`Response unit for ${row.label}`}
            >
              {#each unitOptions(tfNum[i]) as u (u)}
                <option value={u}>{u}</option>
              {/each}
            </select>
            <span class="ml">/</span>
            <select
              class="tf-unit"
              data-testid={`cal-tf-den-${row.ch}`}
              bind:value={tfDen[i]}
              disabled={!set}
              aria-label={`Reference unit for ${row.label}`}
            >
              {#each unitOptions(tfDen[i]) as u (u)}
                <option value={u}>{u}</option>
              {/each}
            </select>
            {#if !tfOrphan}
              <button
                class="icon-btn"
                data-testid={`cal-tf-reset-${row.ch}`}
                title="use the channel calibration"
                aria-label={`Use the channel calibration for ${row.label}`}
                disabled={!set}
                onclick={() => resetTf(i)}
              >↺</button>
            {/if}
          </div>
        {/each}
      </div>
    {:else if tfPending}
      <p class="src-note" data-testid="cal-tf-pending">
        To calibrate the transfer function directly, calculate it first (Calc TF).
      </p>
    {/if}

    <div class="mrow end">
      <button class="btn" data-testid="cal-cancel" onclick={onCancel}>Cancel</button>
      <button class="btn indigo" data-testid="cal-apply" disabled={anyInvalid} onclick={apply}>Apply</button>
    </div>
  </div>
</div>

<style>
  .src-note {
    font-size: 11.5px;
    line-height: 1.4;
    color: var(--muted);
    margin: 0 0 10px;
  }
  .tf-section {
    border-top: 1px solid var(--border);
    margin-top: 14px;
    padding-top: 10px;
  }
  .section-title {
    font-weight: 600;
    font-size: 12.5px;
    margin-bottom: 6px;
  }
  .tf-section select.tf-unit {
    margin-left: 0;
  }
  .tf-section select.tf-unit:disabled {
    opacity: 0.55;
  }
  .src-note.warn {
    color: var(--danger, #dc2626);
  }
  ul.src-note {
    padding-left: 16px;
  }
  .ref-panel {
    margin: -4px 0 8px 12px;
    padding: 4px 0 2px 10px;
    border-left: 2px solid var(--border);
  }
  .ref-panel .mrow {
    margin: 6px 0;
  }
  .btn.small {
    height: 24px;
    padding: 0 8px;
    font-size: 11.5px;
  }
  input.invalid {
    border-color: var(--danger, #dc2626);
  }
  .icon-btn {
    border: 1px solid var(--border);
    background: var(--control-bg);
    color: var(--text);
    border-radius: 6px;
    height: 26px;
    width: 26px;
    padding: 0;
    cursor: pointer;
    font: inherit;
    margin-left: auto;
  }
  .icon-btn:disabled {
    opacity: 0.4;
    cursor: default;
  }
  /* Ported verbatim from round2-bench.html (.overlay/.modal/.mrow/.ml/.btn). */
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 330;
    background: var(--scrim);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .modal {
    width: 440px;
    max-width: calc(100vw - 32px);
    background: var(--surface);
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
  input[type='text'],
  select {
    height: 26px;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0 6px;
    font: inherit;
    font-size: 12px;
    background: var(--control-bg);
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
    background: var(--control-bg);
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
    border-color: var(--border-strong);
    background: var(--hover-bg);
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
    background: var(--indigo-hover);
  }
</style>
