<script lang="ts">
  /**
   * Sonogram-stage context card (design spec §3; round-6 item 3 explicit
   * single-target redesign).
   *
   * FIRST control is a "dataset" dropdown that — UNLIKE the FFT/TF cards —
   * has NO "All sets" option: the sonogram is a single-set, single-channel
   * heat map, so it targets exactly ONE set. The dropdown lists only
   * TIME-BEARING sets: round-5's orphan-TF / spectrum sets (a TF-only
   * `.mat`/`.dvma` load) carry no time series to transform, and running a
   * sonogram on one used to deref a missing array and blank the plot with an
   * opaque error (round-6 item 2). Those sets are filtered out via
   * `actions.workingSets().hasTime`; the modal-fit pseudo-set is already
   * excluded by `dataSetsView` (round-5 item 13).
   *
   * The chosen set lives in the SHARED `analysisSettings.sonoTarget` store
   * (App's heat renderer reads the same store). It defaults to the tray focus
   * when that is a single time-bearing set, else the first time-bearing set;
   * it re-defaults if its set is removed, and is `null` (Calc disabled, with a
   * note) when no time-bearing set exists. A channel select chooses which
   * channel to transform (transient card state, not a stored setting). The
   * STFT window / CWT params / heat-map dynamic range two-way bind to the
   * TARGET set's `sono` settings (per-set persistence, round-5 item 13).
   *
   * Calc Sonogram runs `actions.calcSono(targetId, ch)`. Once a sonogram
   * exists, the STFT-window slider / nFFT box and the channel select re-issue
   * live but DEBOUNCED (150 ms) and gated on an existing result
   * (`createLiveCalc`), so a tweak before the first Calc never boots the
   * engine; the action carries a per-kind stale seq (key 'sono').
   */
  import type { Actions } from '../../lib/analysis/actions';
  import type { Selection } from '../../lib/stores/selection';
  import type { AnalysisSettings, SonoSettings } from '../../lib/stores/analysisSettings';
  import { createLiveCalc } from '../../lib/analysis/liveCalc';
  import Segmented from '../Segmented.svelte';

  let {
    actions,
    selection,
    analysisSettings,
  }: { actions: Actions; selection: Selection; analysisSettings: AnalysisSettings } = $props();

  // DATA sets only (round-5 item 13): the modal-fit pseudo-set is not a
  // sonogram target, so it must not appear in the "dataset" dropdown.
  const setsView = $derived(selection.dataSetsView);
  const computeErrors = $derived(actions.computeErrors);
  const busy = $derived(actions.busy);
  const trayFocus = $derived(selection.trayFocus);

  const sonoTarget = $derived(analysisSettings.sonoTarget);
  const settingsMap = $derived(analysisSettings.map);

  // TIME-BEARING sets only (round-6 items 2/3): orphan TF/spectrum sets have
  // no time series to transform. `workingSets()` is not itself a store, so key
  // the derived on `$setsView` — which emits whenever a set is added/removed —
  // to re-read the has-time flags in step with the tray.
  const timeIds = $derived(
    (void $setsView, new Set(actions.workingSets().filter((w) => w.hasTime).map((w) => w.setId))),
  );
  const timeSets = $derived($setsView.filter((s) => timeIds.has(s.id)));

  // The concrete single target (a setId) or null when no time-bearing set
  // exists. Keep `sonoTarget` valid: if the stored id is missing/stale, default
  // to the tray focus (when it names a time-bearing set) else the first
  // time-bearing set. Runs reactively and converges (writes only when invalid).
  const targetId = $derived($sonoTarget);
  $effect(() => {
    const ids = timeSets.map((s) => s.id);
    if (targetId !== null && ids.includes(targetId)) return;   // already valid
    const focus = $trayFocus;
    const next = typeof focus === 'number' && ids.includes(focus)
      ? focus
      : ids.length ? ids[0] : null;
    if (next !== targetId) sonoTarget.set(next);
  });

  // Target set's per-set sono settings (defaults when nothing is chosen — the
  // controls are disabled in that state anyway).
  const sono = $derived(
    (void $settingsMap, analysisSettings.settingFor(targetId ?? 'all', 'sono')),
  );

  let ch = $state(0);

  // Time-frequency transform: 'stft' (fixed window) or 'cwt' (Morlet wavelet,
  // constant-Q — separates close low-frequency modes an STFT window smears).
  const method = $derived(sono.method);

  // nFft ↔ slider exponent (nFft = 2^resExp).
  const nFft = $derived(sono.nFft);
  const resExp = $derived(Math.round(Math.log2(nFft)));

  // CWT log-frequency density (voices per octave).
  const VPO_OPTIONS = [8, 12, 16, 24, 32];

  // Channel options come from the target set.
  const targetView = $derived(timeSets.find((s) => s.id === targetId));
  const chOptions = $derived(targetView?.nChannels ?? 1);

  // No time-bearing set to target ⇒ Calc disabled with a note.
  const noTimeSet = $derived(timeSets.length === 0);

  // Keep the channel select inside the target set's range (round-4 bug 1).
  // `ch` is card-local state that survives a target switch, so moving to a
  // set with fewer channels (e.g. selecting ch_1 then logging a mono take)
  // would leave `ch` pointing at a channel that no longer exists — the
  // engine's `sono_data[:, :, ch]` then raises and the sonogram renders
  // NOTHING. Snap back to ch_0 whenever the current channel falls out of
  // range so a Calc always targets a real channel.
  $effect(() => {
    if (ch >= chOptions) ch = 0;
  });

  const patch = (partial: Partial<SonoSettings>) => {
    if (targetId !== null) analysisSettings.patch(targetId, 'sono', partial);
  };

  // Switching method re-runs live (gated on an existing sonogram) so the heat
  // map updates immediately when toggling STFT ↔ CWT.
  function onMethod(m: 'stft' | 'cwt') {
    patch({ method: m });
    live.schedule();
  }
  function onVoices(v: number) {
    patch({ voicesPerOctave: v });
    live.schedule();
  }
  // Optional CWT band: blank entry ⇒ null ⇒ auto band. Only apply a range when
  // BOTH bounds are valid and ordered; otherwise clear to auto.
  function onBand(which: 'fMin' | 'fMax', raw: string) {
    const v = raw.trim() === '' ? null : Number(raw);
    if (v !== null && !Number.isFinite(v)) return;
    patch({ [which]: v } as Partial<SonoSettings>);
    live.schedule();
  }

  function calc() {
    if (targetId !== null) actions.calcSono(targetId, ch);
  }

  function onTarget(v: string) {
    sonoTarget.set(Number(v));
  }

  // Slider exponent range (2^6 = 64 .. 2^12 = 4096 pt STFT windows).
  const RES_MIN_EXP = 6;
  const RES_MAX_EXP = 12;

  // Live recompute (round-2 feedback), gated on an existing sonogram so a
  // slider/channel tweak before the first Calc never boots the engine.
  const live = createLiveCalc(() => targetId !== null && actions.hasComputed(targetId, 'sono'), calc);
  function onRes(v: number) {
    patch({ nFft: 1 << v });
    live.schedule();
  }
  // Drop a pending live recompute if the card unmounts (stage switch).
  $effect(() => () => live.cancel());

  /**
   * Text-box entry for nFFT: snap an arbitrary point count to the nearest
   * power of two (the STFT window must be 2^k), then reuse `onRes`. The
   * TEXT BOX accepts values OUTSIDE the slider's exponent range; the
   * SLIDER clamps to its end-stops (R2 point 3), mirroring
   * `ResolutionControl` for the frame-count family. Non-positive / NaN
   * entries are ignored.
   */
  function onNFftText(v: number) {
    if (!Number.isFinite(v) || v < 1) return;
    const exp = Math.round(Math.log2(v));   // nearest power of two
    onRes(exp);                             // patch stores 1<<exp; slider clamps
  }

  // --- Damping fit (Task A1) ---------------------------------------------
  // Log-decrement damping from the decay of each sonogram band, on the same
  // target set + channel + STFT window. Results (fn / Qn per detected mode)
  // show in a small popover chip; independent of the sonogram calc so it can
  // run without first computing the heat map.
  let dampModes = $state<{ fn: number; Qn: number }[] | null>(null);
  let dampBusy = $state(false);
  let dampError = $state('');

  async function fitDamping() {
    if (targetId === null) return;
    dampBusy = true;
    dampError = '';
    try {
      const { fn, Qn } = await actions.calcDamping(targetId, ch, nFft);
      const rows: { fn: number; Qn: number }[] = [];
      for (let i = 0; i < fn.length; i++) rows.push({ fn: fn[i], Qn: Qn[i] });
      dampModes = rows;
    } catch (e) {
      dampError = e instanceof Error ? e.message : String(e);
      dampModes = null;
    } finally {
      dampBusy = false;
    }
  }
</script>

<section class="ctx-card card-controls" aria-label="Sonogram stage controls">
  <div class="ctx-name"><span class="cn-t">Sonogram</span><span class="cn-s">time–freq</span></div>
  <div class="ctx-body">
    <div class="ctx-row">
      <div class="grp">
        <span class="grp-lab">dataset</span>
        <div class="grp-ctl">
          {#if noTimeSet}
            <span class="note" role="note" data-testid="sono-no-time">no time-bearing set</span>
          {:else}
            <select value={targetId === null ? '' : String(targetId)}
              onchange={(e) => onTarget(e.currentTarget.value)}
              style="width:120px" aria-label="dataset">
              {#each timeSets as s (s.id)}
                <option value={String(s.id)}>{s.name}</option>
              {/each}
            </select>
            <select bind:value={ch} onchange={() => live.schedule()} style="width:66px" aria-label="channel">
              {#each Array.from({ length: Math.max(1, chOptions) }, (_, c) => c) as c (c)}
                <option value={c}>ch_{c}</option>
              {/each}
            </select>
          {/if}
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">method</span>
        <div class="grp-ctl">
          <Segmented
            ariaLabel="sonogram method"
            testid="sono-method"
            value={method}
            onchange={(m) => onMethod(m as 'stft' | 'cwt')}
            options={[
              { value: 'stft' as const, label: 'STFT', title: 'Short-time Fourier transform (fixed window)' },
              { value: 'cwt' as const, label: 'CWT', title: 'Complex Morlet wavelet transform (constant-Q; separates close low-frequency modes)' },
            ]}
          />
        </div>
      </div>
      {#if method === 'stft'}
        <div class="grp">
          <span class="grp-lab">resolution — {nFft} pt</span>
          <div class="grp-ctl">
            <input type="range" min={RES_MIN_EXP} max={RES_MAX_EXP}
              value={Math.min(RES_MAX_EXP, Math.max(RES_MIN_EXP, resExp))}
              oninput={(e) => onRes(+e.currentTarget.value)} style="width:96px" aria-label="resolution" />
            <span class="ml">nFFT</span>
            <input type="number" step="1" min="1"
              value={nFft}
              onchange={(e) => onNFftText(+e.currentTarget.value)}
              style="width:64px" aria-label="nFFT" />
            <span class="note">pt</span>
          </div>
        </div>
      {:else}
        <div class="grp">
          <span class="grp-lab">voices / octave</span>
          <div class="grp-ctl">
            <select value={sono.voicesPerOctave} onchange={(e) => onVoices(+e.currentTarget.value)}
              style="width:60px" aria-label="voices per octave">
              {#each VPO_OPTIONS as v (v)}
                <option value={v}>{v}</option>
              {/each}
            </select>
            <span class="note">log-freq density</span>
          </div>
        </div>
        <div class="grp">
          <span class="grp-lab">freq range — Hz (blank = auto)</span>
          <div class="grp-ctl">
            <input type="number" step="1" min="0" value={sono.fMin ?? ''} placeholder="min"
              onchange={(e) => onBand('fMin', e.currentTarget.value)}
              style="width:60px" aria-label="cwt f min" />
            <span class="ml">–</span>
            <input type="number" step="1" min="0" value={sono.fMax ?? ''} placeholder="max"
              onchange={(e) => onBand('fMax', e.currentTarget.value)}
              style="width:60px" aria-label="cwt f max" />
          </div>
        </div>
      {/if}
      <div class="grp">
        <span class="grp-lab">dynamic range</span>
        <div class="grp-ctl">
          <input type="number" value={sono.dynRangeDb}
            onchange={(e) => patch({ dynRangeDb: +e.currentTarget.value })}
            step="10" min="30" max="120" style="width:56px" aria-label="dynamic range dB" /><span class="ml">dB</span>
        </div>
      </div>
    </div>
    <div class="ctx-row">
      <div class="grp">
        <span class="grp-lab">damping</span>
        <div class="grp-ctl">
          <button class="btn" disabled={dampBusy || noTimeSet || targetId === null} onclick={fitDamping}
            title="Fit modal damping from the decay of each sonogram band">
            {dampBusy ? 'Fitting…' : 'Fit damping'}</button>
          <span class="note">log-decrement of {method === 'cwt' ? 'CWT' : 'sonogram'} bands</span>
          {#if dampModes}
            <div class="damp-table mono" role="status" aria-label="fitted damping">
              {#if dampModes.length}
                <table>
                  <thead><tr><th>fn (Hz)</th><th>Qn</th></tr></thead>
                  <tbody>
                    {#each dampModes as m, i (i)}
                      <tr><td>{m.fn.toFixed(1)}</td><td>{m.Qn.toFixed(1)}</td></tr>
                    {/each}
                  </tbody>
                </table>
              {:else}
                <span class="note">no decaying modes detected</span>
              {/if}
            </div>
          {/if}
        </div>
      </div>
    </div>
    {#if noTimeSet}
      <div class="ctx-note" role="note">
        The sonogram needs a time-domain signal. Load or record a set with time
        data — a loaded spectrum or transfer function alone cannot be transformed.
      </div>
    {/if}
    {#if $computeErrors.sono}
      <div class="ctx-err" role="alert">{$computeErrors.sono}</div>
    {/if}
    {#if dampError}
      <div class="ctx-err" role="alert">{dampError}</div>
    {/if}
  </div>
  <div class="ctx-primary">
    <button class="btn indigo" disabled={$busy || noTimeSet || targetId === null} onclick={calc}>Calc Sonogram</button>
  </div>
</section>

<style>
  /* Mirrors ContextCard's .ctx-note (Svelte styles are component-scoped). */
  .ctx-note {
    font-size: 12px;
    color: var(--muted);
    font-style: italic;
  }
  .damp-table {
    display: inline-block;
    margin-left: 4px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface-2);
    padding: 3px 7px;
  }
  .damp-table table {
    border-collapse: collapse;
    font-size: 11.5px;
  }
  .damp-table th {
    font-size: 9.5px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted-2);
    font-weight: 600;
    text-align: right;
    padding: 1px 8px 2px 0;
  }
  .damp-table td {
    text-align: right;
    padding: 1px 8px 1px 0;
  }
</style>
