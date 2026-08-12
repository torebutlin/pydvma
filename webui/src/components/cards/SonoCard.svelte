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
  import { autoVoicesForW0, VPO_LADDER, type AnalysisSettings, type SonoSettings } from '../../lib/stores/analysisSettings';
  import { editSonoBand, sonoFreqScaleFor } from '../../lib/analysis/sonoBand';
  import type { ViewState } from '../../lib/stores/viewstate';
  import type { DampingStore } from '../../lib/stores/damping';
  import { createLiveCalc } from '../../lib/analysis/liveCalc';
  import { ENGINE_STOPPED_MESSAGE } from '../../lib/stores/engine';
  import Segmented from '../Segmented.svelte';
  import CalcProgress from '../CalcProgress.svelte';

  let {
    viewState,
    actions,
    selection,
    analysisSettings,
    damping,
    onFitDamping,
  }: {
    viewState: ViewState; actions: Actions; selection: Selection;
    analysisSettings: AnalysisSettings;
    /** Interactive damping panel state (round-7) — Fit damping opens it. */
    damping: DampingStore;
    /** Run the fit with the damping store's current knobs (App wires it). */
    onFitDamping: () => void;
  } = $props();

  // Heat colour mode lives in the (per-view) sono view-state, driven from the
  // plot toolbar's `colour` control. The dynamic-range dB span only applies to
  // the dB colour map; in LINEAR colour mode the heat is normalised 0→peak, so
  // the dB span is not used — the control is disabled here with a note (the
  // painter ignores it in lin mode too). The card is only mounted while the sono
  // view is active, so `viewState.current` is the sono slice.
  const currentSlice = $derived(viewState.current);
  const colourLin = $derived($currentSlice.sonoColour === 'lin');

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

  // CWT log-frequency density (voices per octave). Round-9: defaults to AUTO
  // — `autoVoicesForW0` keeps the density matched to the wavelet Q (a high-Q
  // wavelet needs a comparably dense frequency grid or its narrow bands fall
  // between analysis frequencies); an explicit pick from the ladder overrides.
  const VPO_OPTIONS = VPO_LADDER;

  // Morlet wavelet Q (w0): cycles under the Gaussian envelope. Higher = finer
  // frequency resolution, coarser time resolution. 6 is the classic default.
  // Round-9: a slider (nFFT feel) spanning 4..64, with an exact box accepting
  // up to 128 — the engine has no hard w0 limit, but past ~107 the 64-voice
  // ladder top undersamples the grid slightly, so the box clamps there. NB
  // memory for the damping fit grows with the grid (rows x time columns), so a
  // long record at a high Q can exceed the engine's image ceiling — pydvma
  // then refuses with a sizing error naming the remedies (shorter record,
  // narrower freq range, fewer voices), which is what the freq-range boxes
  // below are for.
  const W0_MIN = 4;
  const W0_SLIDER_MAX = 64;
  const W0_BOX_MAX = 128;

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
  //
  // The toggle also sets the frequency axis each transform wants
  // (`sonoFreqScaleFor`: CWT → log, STFT → lin). RULE, deliberately simple:
  // every method toggle sets that default, and a manual choice from the plot
  // toolbar afterwards stands until the NEXT toggle. Without it the CWT's
  // native log ladder was drawn on a linear axis by default, which crushes its
  // low-frequency rows into a blocky band — the detail the wavelet was chosen
  // for — and every user had to find the toolbar's lin/log control to see it.
  function onMethod(m: 'stft' | 'cwt') {
    patch({ method: m });
    viewState.setSonoFreqScale(sonoFreqScaleFor(m));
    bandError = '';                 // the band boxes only exist for the CWT
    live.schedule();
  }
  // Voices select: the 'auto' entry re-enables following the wavelet Q; an
  // explicit number pins the density (voicesAuto off) until 'auto' is chosen
  // again. `voicesPerOctave` always stores the RESOLVED number.
  function onVoices(raw: string) {
    if (raw === 'auto') {
      patch({ voicesAuto: true, voicesPerOctave: autoVoicesForW0(sono.w0) });
    } else {
      patch({ voicesAuto: false, voicesPerOctave: +raw });
    }
    live.schedule();
  }
  // w0 changes drag the auto-resolved voices along (round-9).
  function onW0(v: number) {
    if (!Number.isFinite(v)) return;
    const w0 = Math.min(W0_BOX_MAX, Math.max(W0_MIN, Math.round(v)));
    patch(sono.voicesAuto ? { w0, voicesPerOctave: autoVoicesForW0(w0) } : { w0 });
    live.schedule();
  }
  // Optional CWT band. The two boxes are INDEPENDENT: a blank clears that side
  // back to auto, and a lone bound is honoured (the engine fills the other side
  // with its automatic value). A reversed pair is refused with a note rather
  // than swapped or dropped — see `editSonoBand` for the full rule. The band
  // matters beyond the picture: it is also what keeps a long record's CWT
  // damping fit inside the engine's memory ceiling.
  let bandError = $state('');
  function onBand(which: 'fMin' | 'fMax', raw: string) {
    const { patch: p, error } = editSonoBand(which, raw, { fMin: sono.fMin, fMax: sono.fMax });
    bandError = error;
    if (!p) return;
    patch(p as Partial<SonoSettings>);
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

  // --- Damping fit (Task A1; round-7 interactive rebuild) -----------------
  // "Fit damping" opens the shared interactive panel below the sonogram
  // (DampingPanel: decay-fit plot, threshold + start-time controls, the
  // peaks|bands method toggle) and runs the first fit. Results live in the
  // damping store — the inline fn/Qn chip this card used to render is gone;
  // the panel is the readout. Independent of the sonogram calc, so it can
  // run without first computing the heat map.
  const dampState = $derived($damping);

  function fitDamping() {
    if (targetId === null) return;
    damping.openFor(targetId, ch);
    onFitDamping();
  }

  // --- Stop (round-11 P7) --------------------------------------------------
  // A stopped calc is not a failure: `actions.guarded` still routes the
  // rejection into `computeErrors.sono`, but it lands there as the known stop
  // MESSAGE, and this card shows it as a quiet note rather than a red alert.
  // (Whether it also raises one toast is the actions layer's call — see the
  // integration note; the card is honest either way.)
  const sonoError = $derived($computeErrors.sono);
  const sonoStopped = $derived(sonoError === ENGINE_STOPPED_MESSAGE);
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
          <span class="grp-lab">wavelet Q (w0) — {sono.w0}</span>
          <div class="grp-ctl">
            <input type="range" min={W0_MIN} max={W0_SLIDER_MAX} step="1"
              value={Math.min(W0_SLIDER_MAX, Math.max(W0_MIN, sono.w0))}
              oninput={(e) => onW0(+e.currentTarget.value)}
              style="width:96px" aria-label="wavelet Q slider"
              title="Morlet wavelet Q — higher = finer frequency resolution, coarser time resolution" />
            <input type="number" step="1" min={W0_MIN} max={W0_BOX_MAX}
              value={sono.w0}
              onchange={(e) => onW0(+e.currentTarget.value)}
              style="width:56px" aria-label="wavelet Q w0"
              title="Exact wavelet Q — accepts values beyond the slider (up to {W0_BOX_MAX})" />
          </div>
        </div>
        <div class="grp">
          <span class="grp-lab">voices / octave</span>
          <div class="grp-ctl">
            <select value={sono.voicesAuto ? 'auto' : String(sono.voicesPerOctave)}
              onchange={(e) => onVoices(e.currentTarget.value)}
              style="width:86px" aria-label="voices per octave"
              title="Log-frequency grid density. Auto keeps it matched to the wavelet Q (≥ 0.6·w0, min 16); pick a number to pin it.">
              <option value="auto">auto ({autoVoicesForW0(sono.w0)})</option>
              {#each VPO_OPTIONS as v (v)}
                <option value={String(v)}>{v}</option>
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
            {#if bandError}
              <span class="ctx-err" role="alert" data-testid="sono-band-error">{bandError}</span>
            {/if}
          </div>
        </div>
      {/if}
      <div class="grp">
        <span class="grp-lab">dynamic range</span>
        <div class="grp-ctl">
          <input type="number" value={sono.dynRangeDb}
            onchange={(e) => patch({ dynRangeDb: +e.currentTarget.value })}
            step="10" min="30" max="120" style="width:56px" aria-label="dynamic range dB"
            disabled={colourLin} title={colourLin ? 'Not used in linear colour mode' : ''} /><span class="ml">dB</span>
          {#if colourLin}<span class="note" data-testid="sono-dynrange-lin-note">n/a — linear colour</span>{/if}
        </div>
      </div>
    </div>
    <div class="ctx-row">
      <div class="grp">
        <span class="grp-lab">damping</span>
        <div class="grp-ctl">
          <button class="btn" disabled={dampState.busy || noTimeSet || targetId === null}
            onclick={fitDamping} data-testid="sono-fit-damping"
            title="Open the interactive damping panel: per-band decay fits (peaks) or Schroeder band metrics (bands)">
            {dampState.busy ? 'Fitting…' : 'Fit damping'}</button>
          <span class="note">
            {dampState.open
              ? 'panel below the sonogram — drag the start line / threshold'
              : `decay of ${method === 'cwt' ? 'CWT' : 'sonogram'} bands, or Schroeder band metrics`}
          </span>
        </div>
      </div>
    </div>
    {#if noTimeSet}
      <div class="ctx-note" role="note">
        The sonogram needs a time-domain signal. Load or record a set with time
        data — a loaded spectrum or transfer function alone cannot be transformed.
      </div>
    {/if}
    <!-- Long-calc progress + Stop: silent until the calc passes ~3 s, then a
         determinate bar (the CWT reports one frame per wavelet scale). -->
    <div class="ctx-row cp-row"><CalcProgress ops={['calc_sono']} testid="sono-progress" /></div>
    {#if sonoStopped}
      <div class="ctx-note" role="note" data-testid="sono-stopped">
        Calculation stopped — the engine is restarting. Press Calc Sonogram again when it is ready.
      </div>
    {:else if sonoError}
      <div class="ctx-err" role="alert">{sonoError}</div>
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
  /* The progress strip collapses to nothing when no calc is long-running —
     `CalcProgress` renders nothing at all, so the row must not reserve gap. */
  .cp-row:empty { display: none; }
</style>
