<script lang="ts">
  /**
   * Data tray (design spec §5; visuals ported from the `.tray` block of
   * dev/mockups/round2-bench.html). The sets×channels navigation surface
   * over the selection store: a header of batch controls, a channel-chip
   * row for cross-set column ops, and one `TrayCard` per set.
   *
   * This component FILLS an existing tray region (App.svelte's wide
   * `aside`, or the narrow flyover drawer) — that container already
   * carries `data-testid="tray"`, so the tray itself must not add a
   * second one. Its own scroll container is `data-testid="tray-body"`.
   *
   * Header buttons: All (`selection.all()`), None (`selection.none()`),
   * Solo, and `‹ ›` steppers (`selection.step(-1/1)`). The channel-chip
   * row shows one chip per channel index `0..maxChannels-1` (maxChannels
   * = the widest set); clicking a chip cycles that column across every
   * set (`selection.cycleChannel`). Each chip's mini dot is coloured by
   * `summariseColumn` over that channel's tri-state across all sets.
   *
   * SOLO / ‹ › GRANULARITY (round-5 item 3): the buttons adapt to the
   * data. With MULTIPLE sets they operate per-SET — Solo isolates the
   * highlighted set (or the first), ‹ › step between sets (`selection.solo`
   * / `selection.step`). With a SINGLE multi-channel set (e.g. an 11-point
   * orphan-TF ruler grid, where set-level Solo/‹ › are inert because there
   * is only one set to isolate/step) they operate per-LINE — Solo isolates
   * the highlighted line (or the first), ‹ › step through the set's channels
   * (`selection.soloLine` / `selection.stepLine`). This keeps the tested
   * multi-set behaviour intact while making the single-set case useful.
   */
  import { get } from 'svelte/store';
  import type { Selection } from '../lib/stores/selection';
  import { summariseColumn, type ColumnState } from '../lib/stores/channelSummary';
  import { factorToSensitivity, sensitivityToFactor, type CalRow } from '../lib/model/calibration';
  import { calibrationController } from '../lib/stores/calibrationController';
  import TrayCard from './TrayCard.svelte';
  import CalibrateDialog from './CalibrateDialog.svelte';

  let {
    selection,
    /** Real time-series for a (setId, ch) so cards can draw sparklines.
     *  Reassigned by the parent when decoded data changes (keeps previews live). */
    channelData,
    /** Read a set's persisted calibration (factors + units) — Task A2. */
    getCalibration,
    /** Persist a set's calibration (factors + units). Both must be supplied
     *  together to enable the per-card Calibrate button. */
    applyCalibration,
  }: {
    selection: Selection;
    channelData?: (setId: number, ch: number) => Float64Array | undefined;
    getCalibration?: (setId: number) => { factors: number[]; units: string[] };
    applyCalibration?: (setId: number, factors: number[], units: string[]) => void;
  } = $props();

  // Prefer explicit props (idiomatic / testable); otherwise use the app-scoped
  // controller the actions layer publishes (avoids a prop thread through App).
  const controller = $derived($calibrationController);
  const readCal = $derived(getCalibration ?? controller?.getCalibration);
  const writeCal = $derived(applyCalibration ?? controller?.setCalFactors);
  const canCalibrate = $derived(!!readCal && !!writeCal);

  // The set whose Calibrate dialog is open (null = closed), plus the rows it
  // was seeded with. Rebuilt each open from the persisted factors/units and
  // the current channel labels (Task A2).
  let calSetId = $state<number | null>(null);
  let calName = $state('');
  let calRows = $state<CalRow[]>([]);

  function openCalibrate(setId: number) {
    if (!readCal) return;
    const set = $setsView.find((s) => s.id === setId);
    if (!set) return;
    const { factors, units } = readCal(setId);
    const label = get(selection.channelLabel);
    calRows = Array.from({ length: set.nChannels }, (_, ch) => ({
      ch,
      label: label(setId, ch),
      // Show the SENSITIVITY (1/factor) the stored cal factor implies; the
      // dialog collects a sensitivity and the parent converts it back.
      sensitivity: factorToSensitivity(factors[ch] ?? 1),
      unit: units[ch] ?? 'V',
    }));
    calName = set.name;
    calSetId = setId;
  }

  function closeCalibrate() {
    calSetId = null;
  }

  function commitCalibrate(results: { sensitivity: number; unit: string }[]) {
    if (calSetId === null || !writeCal) return;
    const factors = results.map((r) => sensitivityToFactor(r.sensitivity));
    const units = results.map((r) => r.unit);
    writeCal(calSetId, factors, units);
    calSetId = null;
  }

  const setsView = $derived(selection.setsView);
  const stateStore = $derived(selection.state);
  const highlight = $derived(selection.highlight);
  const lineHighlight = $derived(selection.lineHighlight);

  // Line-level Solo/‹ › engage when the tray shows exactly one set — its
  // channels are then the natural things to isolate and step through
  // (round-5 item 3). More than one set keeps the per-set behaviour.
  const singleSet = $derived($setsView.length === 1);

  // Widest set drives the channel-chip row (union of channel indices).
  const maxChannels = $derived(
    $setsView.reduce((m, s) => Math.max(m, s.nChannels), 0),
  );

  /** Summary state for the chip of channel `ch` across all sets that have it. */
  function columnState(ch: number): ColumnState {
    const col = $setsView
      .filter(s => ch < s.nChannels)
      .map(s => $stateStore(s.id, ch));
    return summariseColumn(col);
  }

  // The line to isolate/step from in single-set mode: the highlighted line
  // when it still exists in the (one) set, else the set's first channel.
  function currentLine(): { setId: number; ch: number } | null {
    const list = $setsView;
    if (list.length === 0) return null;
    const hl = $lineHighlight;
    if (hl && list.some(s => s.id === hl.setId && hl.ch < s.nChannels)) return hl;
    return { setId: list[0].id, ch: 0 };
  }

  // Solo: isolate the highlighted LINE (single set) or SET (multiple sets).
  function onSolo() {
    const list = $setsView;
    if (list.length === 0) return;
    if (singleSet) {
      const cl = currentLine();
      if (cl) selection.soloLine(cl.setId, cl.ch);
      return;
    }
    const target = list.some(s => s.id === $highlight) ? $highlight : list[0].id;
    selection.solo(target);
  }

  // ‹ ›: step the line-solo (single set) or the set-solo (multiple sets).
  function onStep(dir: 1 | -1) {
    if ($setsView.length === 0) return;
    if (singleSet) selection.stepLine(dir);
    else selection.step(dir);
  }
</script>

<div class="tray-inner">
  <div class="tray-head">
    <span class="sec-label">Data</span>
    <button class="btn sm" title="All channels of all sets on" onclick={() => selection.all()}>All</button>
    <button class="btn sm" title="All channels of all sets off" onclick={() => selection.none()}>None</button>
    <button class="btn sm" title={singleSet ? 'Show only the highlighted channel' : 'Show only the highlighted set'} onclick={onSolo}>Solo</button>
    <button class="btn sm" title={singleSet ? 'Highlight previous channel' : 'Highlight previous set'} aria-label={singleSet ? 'Previous channel' : 'Previous set'} onclick={() => onStep(-1)}>‹</button>
    <button class="btn sm" title={singleSet ? 'Highlight next channel' : 'Highlight next set'} aria-label={singleSet ? 'Next channel' : 'Next set'} onclick={() => onStep(1)}>›</button>
  </div>

  {#if maxChannels > 0}
    <div class="chip-row">
      <span class="chiprow-lab">Ch</span>
      {#each Array.from({ length: maxChannels }, (_, ch) => ch) as ch (ch)}
        {@const agg = columnState(ch)}
        <button
          class="colchip agg-{agg}"
          data-testid={`chip-ch-${ch}`}
          title={`Cycle channel ${ch} across all sets`}
          onclick={() => selection.cycleChannel(ch)}
        >
          <span class="tdot"></span>{ch}
        </button>
      {/each}
    </div>
  {/if}

  <div class="tray-body" data-testid="tray-body">
    {#if $setsView.length === 0}
      <p class="tray-empty">No data loaded</p>
    {:else}
      {#each $setsView as set (set.id)}
        <TrayCard
          {selection}
          {set}
          onDeleteSet={selection.removeSet}
          onCalibrate={canCalibrate ? openCalibrate : undefined}
          channelData={channelData ? (ch) => channelData(set.id, ch) : undefined}
        />
      {/each}
    {/if}
  </div>
</div>

{#if calSetId !== null}
  {#key calSetId}
    <CalibrateDialog
      setName={calName}
      rows={calRows}
      onApply={commitCalibrate}
      onCancel={closeCalibrate}
    />
  {/key}
{/if}

<style>
  .tray-inner {
    display: flex;
    flex-direction: column;
    min-height: 0;
    height: 100%;
    width: 100%;
    background: var(--surface);
  }
  .tray-head {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 9px 12px 7px;
  }
  .sec-label {
    margin-right: auto;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
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
  }
  .btn:hover {
    border-color: #c6cbd6;
    background: #fafbfc;
  }
  .btn:active {
    transform: translateY(1px);
  }
  .btn.sm {
    height: 24px;
    padding: 0 8px;
    font-size: 11.5px;
    border-radius: 6px;
  }
  .chip-row {
    flex: 0 0 auto;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 5px;
    padding: 2px 12px 8px;
    border-bottom: 1px solid var(--border);
    overflow-x: auto;
  }
  .chiprow-lab {
    font-size: 9.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #a3aabc;
    margin-right: 2px;
  }
  .colchip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    height: 22px;
    padding: 0 8px;
    border-radius: 11px;
    border: 1px solid var(--border);
    background: #f8f9fb;
    font: 11px var(--font-mono);
    color: var(--text);
    cursor: pointer;
    flex: 0 0 auto;
  }
  .colchip:hover {
    border-color: #c6cbd6;
    background: #fff;
  }
  .tdot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    border: 1.5px solid #c7ccd8;
    background: transparent;
    flex: 0 0 auto;
  }
  .agg-on .tdot {
    background: var(--green);
    border-color: var(--green);
  }
  .agg-fade .tdot {
    background: #86efac;
    border-color: #86efac;
  }
  .agg-mixed .tdot {
    background: linear-gradient(90deg, var(--green) 50%, transparent 50%);
    border-color: var(--green);
  }
  .agg-off .tdot {
    background: transparent;
    border-color: #c7ccd8;
  }
  .tray-body {
    flex: 1;
    overflow-y: auto;
    padding: 10px 12px;
    min-height: 60px;
  }
  .tray-empty {
    color: var(--muted);
    font-size: 12.5px;
    text-align: center;
    padding: 26px 8px;
    margin: 0;
  }
</style>
