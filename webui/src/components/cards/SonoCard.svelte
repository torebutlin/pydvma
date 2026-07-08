<script lang="ts">
  /**
   * Sonogram-stage context card (design spec §3; Task R1 per-set
   * redesign).
   *
   * FIRST control is the "Dataset ▾" dropdown bound to the shared
   * `analysisTarget` (follows the tray). It replaces the old free-standing
   * "source set" select — the sonogram now runs the TARGET set. A channel
   * select chooses which channel of that set to transform (the channel is
   * a transient card control, not a per-set stored setting). The STFT
   * window size (`nFft = 2^slider`) and heat-map dynamic range two-way
   * bind to the FOCUSED set's sono settings via the `analysisSettings`
   * store, with "–mixed–" shown when the target is `'all'` and sets
   * disagree.
   *
   * Calc Sonogram runs `actions.calcSono(target, ch)`. Once a sonogram
   * exists, the STFT-window slider / nFFT box and the channel select
   * re-issue live but DEBOUNCED (150 ms) and gated on an existing result
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
  // sonogram target, so it must not appear in the "Dataset ▾" dropdown.
  const setsView = $derived(selection.dataSetsView);
  const computeErrors = $derived(actions.computeErrors);
  const busy = $derived(actions.busy);

  const target = $derived(analysisSettings.analysisTarget);
  const settingsMap = $derived(analysisSettings.map);
  const sono = $derived((void $settingsMap, analysisSettings.settingFor($target, 'sono')));
  const mixed = (key: 'nFft' | 'dynRangeDb') =>
    (void $settingsMap, $target === 'all' && analysisSettings.isMixed('sono', key));

  let ch = $state(0);

  // Time-frequency transform: 'stft' (fixed window) or 'cwt' (Morlet wavelet,
  // constant-Q — separates close low-frequency modes an STFT window smears).
  const method = $derived(sono.method);

  // nFft ↔ slider exponent (nFft = 2^resExp). Mixed → the readout shows –mixed–.
  const nFft = $derived(sono.nFft);
  const resExp = $derived(Math.round(Math.log2(nFft)));

  // CWT log-frequency density (voices per octave).
  const VPO_OPTIONS = [8, 12, 16, 24, 32];

  // Channel options come from the target set (first set for 'all').
  const targetView = $derived(
    $target === 'all' ? $setsView[0] : $setsView.find((s) => s.id === $target),
  );
  const chOptions = $derived(targetView?.nChannels ?? 1);

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

  const patch = (partial: Partial<SonoSettings>) =>
    analysisSettings.patch($target, 'sono', partial);

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
    if ($setsView.length) actions.calcSono($target, ch);
  }

  // Slider exponent range (2^6 = 64 .. 2^12 = 4096 pt STFT windows).
  const RES_MIN_EXP = 6;
  const RES_MAX_EXP = 12;

  // Live recompute (round-2 feedback), gated on an existing sonogram so a
  // slider/channel tweak before the first Calc never boots the engine.
  const live = createLiveCalc(() => actions.hasComputed($target, 'sono'), calc);
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

  function onTarget(v: string) {
    analysisSettings.setTarget(v === 'all' ? 'all' : Number(v));
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
    if (!$setsView.length) return;
    dampBusy = true;
    dampError = '';
    try {
      const { fn, Qn } = await actions.calcDamping($target, ch, nFft);
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
          <select value={$target === 'all' ? 'all' : String($target)}
            onchange={(e) => onTarget(e.currentTarget.value)}
            style="width:120px" aria-label="dataset">
            <option value="all">All sets</option>
            {#each $setsView as s (s.id)}
              <option value={String(s.id)}>{s.name}</option>
            {/each}
          </select>
          <select bind:value={ch} onchange={() => live.schedule()} style="width:66px" aria-label="channel">
            {#each Array.from({ length: Math.max(1, chOptions) }, (_, c) => c) as c (c)}
              <option value={c}>ch_{c}</option>
            {/each}
          </select>
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
          <span class="grp-lab">resolution — {mixed('nFft') ? '–mixed–' : `${nFft} pt`}</span>
          <div class="grp-ctl">
            <input type="range" min={RES_MIN_EXP} max={RES_MAX_EXP}
              value={Math.min(RES_MAX_EXP, Math.max(RES_MIN_EXP, resExp))}
              oninput={(e) => onRes(+e.currentTarget.value)} style="width:96px" aria-label="resolution" />
            <span class="ml">nFFT</span>
            <input type="number" step="1" min="1"
              value={mixed('nFft') ? '' : nFft}
              placeholder={mixed('nFft') ? '–mixed–' : ''}
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
          <input type="number" value={mixed('dynRangeDb') ? '' : sono.dynRangeDb}
            placeholder={mixed('dynRangeDb') ? '–mixed–' : ''}
            onchange={(e) => patch({ dynRangeDb: +e.currentTarget.value })}
            step="10" min="30" max="120" style="width:56px" aria-label="dynamic range dB" /><span class="ml">dB</span>
        </div>
      </div>
    </div>
    <div class="ctx-row">
      <div class="grp">
        <span class="grp-lab">damping</span>
        <div class="grp-ctl">
          <button class="btn" disabled={dampBusy || $setsView.length === 0} onclick={fitDamping}
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
    {#if $computeErrors.sono}
      <div class="ctx-err" role="alert">{$computeErrors.sono}</div>
    {/if}
    {#if dampError}
      <div class="ctx-err" role="alert">{dampError}</div>
    {/if}
  </div>
  <div class="ctx-primary">
    <button class="btn indigo" disabled={$busy || $setsView.length === 0} onclick={calc}>Calc Sonogram</button>
  </div>
</section>

<style>
  .damp-table {
    display: inline-block;
    margin-left: 4px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: #fff;
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
    color: #98a1b5;
    font-weight: 600;
    text-align: right;
    padding: 1px 8px 2px 0;
  }
  .damp-table td {
    text-align: right;
    padding: 1px 8px 1px 0;
  }
</style>
