# Schoukens BLA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Schoukens random-phase multisine method (BLA + noise/nonlinearity separation, SISO+MISO unified) end-to-end: excitation, orchestrated acquisition on all three paths, analysis, Nonlin stage UI, σ overlays.

**Architecture:** Python engine owns signal design + analysis (`multisine_generator`, `calculate_bla`, TfData extension); webui owns orchestration (a `bla` store looping ordinary captures) and the Nonlin stage. Spec dicts `{seed, m, e, n_exc, …}` make every capture reproducible. See `dev/plans/2026-08-10-schoukens-bla-design.md` — the design governs; one refinement: the generator is a standalone `multisine_generator` (its parameter set doesn't fit `signal_generator`'s signature).

**Tech Stack:** numpy (rfft/irfft, batched linalg.inv), Svelte 5 runes, vitest/pytest/Playwright.

**Conventions for every task:** run pytest as `python3 -m pytest` from the worktree root; webui commands from `webui/`; commit after each task (small, coherent); docstrings griffe-strict (one param per Args line, returns in prose); read the named precedent files BEFORE writing code — matching live patterns beats inventing.

---

## Shared contracts (all tasks use these exact names)

**MultisineSpec (Python dict / TS interface)** — the unit of reproducibility:

```
{
  n_samples: int      # N, samples per period
  k1: int, k2: int    # excited bin range (inclusive), 1 <= k1 <= k2 < N/2
  p_periods: int      # P steady-state periods
  t_periods: int      # transient periods prepended (discarded in analysis)
  seed: int           # uint32; phases for realisation m via default_rng([seed, m])
  m: int              # realisation index 0..M-1
  e: int              # experiment index 0..n_exc-1
  n_exc: int          # driven excitation count (= experiments per realisation)
  amp_rms: float      # per-excitation-channel target RMS (volts on NI, normalised 0..1 in browser)
}
```

Phase law (identical in Python and TS, per-path PRNGs need not match each other):
`phases = rng.uniform(0, 2π, size=(n_exc, n_lines))` drawn ONCE per (seed, m);
experiment e shifts input q's every line by `−2π·q·e/n_exc` (zero-based q, e —
the DFT-matrix rotation `T_qe`). Line amplitudes: equal, `A = amp_rms·sqrt(2/n_lines)`,
identical across realisations (constant excitation class; crest factor varies —
peak is guard-checked, never rescaled).

**BlaRunSpec (analysis input, Python dict from glue/TS):**

```
{
  multisine: MultisineSpec minus m/e,   # plus M: int (realisation count)
  x_mode: 'measured' | 'commanded',
  x_channels: list[int] | None,   # per-excitation measured-x channel indices (None iff commanded)
  resp_channels: list[int],       # response channel indices (n_resp >= 1, independent of n_exc)
  fs: float,                      # ACTUAL capture fs (coerced value)
}
```

**TfData extension (per excitation q):** optional attrs `bla_sigma_nl`,
`bla_sigma_n` — real arrays shape `(n_freq, n_resp)`, **linear FRF-unit standard
deviations** (σ_NL = √max(σ²_tot−σ²_n, 0); σ_n = √σ²_n with the 1/P already
folded in, so the two are directly comparable and to |G|) — and `bla` meta dict
(the BlaRunSpec + `excited_bins` list). `tf_coherence=None` for BLA sets.

---

### Task 1: Python multisine generator

**Files:** Modify `pydvma/acquisition.py` (new function after `signal_generator`, ~line 630). Test: create `tests/test_multisine.py`.

- [ ] Write failing tests (`tests/test_multisine.py`):
  - `test_exact_periodicity`: y of (t_periods+p_periods) periods; assert `np.allclose(y[:N], y[N:2*N])` etc. for all period pairs, all channels.
  - `test_spectral_flatness`: rfft of one period; assert |bins k1..k2| equal within 1e-9 rel, all other bins < 1e-9 abs.
  - `test_rms_level`: per-channel RMS ≈ amp_rms (exact: equal-amplitude lines ⇒ RMS = √(n_lines·A²/2)).
  - `test_seed_reproducibility`: same (seed,m,e) ⇒ identical; different m ⇒ different phases.
  - `test_rotation_orthogonality`: for n_exc=2, per-bin 2×2 matrix `X[q,e]` of one-period spectra has condition number ≈ 1; e=0 vs e=1 spectra differ only by the phase factor `exp(−j2π·q·e/2)` (i.e. q=0 unchanged, q=1 negated).
  - `test_peak_guard`: amp_rms driving peak past `settings.output_vmax()` raises ValueError mentioning the rail and the peak (NO silent rescale).
  - `test_shape`: returns `(t, y)` with y shape `((t_periods+p_periods)*N, n_exc)`.
- [ ] Run: `python3 -m pytest tests/test_multisine.py -q` → FAIL (no function).
- [ ] Implement in `pydvma/acquisition.py`:

```python
def multisine_generator(settings, spec):
    """Create a periodic random-phase multisine buffer for a BLA capture.

    One period is ``N = spec['n_samples']`` samples exciting integer DFT
    bins ``k1..k2`` with equal amplitudes and uniform random phases drawn
    from ``numpy.random.default_rng([seed, m])`` — so a saved spec
    reproduces the waveform exactly. Experiment ``e`` applies the
    orthogonal DFT-matrix rotation (phase shift ``−2π·q·e/n_exc`` on
    excitation ``q``), which keeps every channel's amplitude spectrum
    identical across the ``n_exc`` experiments of a realisation.

    Unlike `signal_generator` this applies NO fade window and NO peak
    rescale — both would break exact periodicity. ``amp_rms`` sets the
    per-channel RMS (identical across realisations, keeping the
    excitation class constant); if the resulting peak exceeds
    ``settings.output_vmax()`` a ValueError is raised — lower the level.

    Args:
        settings: MySettings; only ``output_fs`` (time axis) and the
            output voltage rail are consulted.
        spec: MultisineSpec dict — n_samples, k1, k2, p_periods,
            t_periods, seed, m, e, n_exc, amp_rms (see the BLA design
            doc, dev/plans/2026-08-10-schoukens-bla-design.md).

    Returns a tuple ``(t, y)`` with ``y`` shape
    ``((t_periods + p_periods) * n_samples, n_exc)`` in volts, ready for
    ``log_data(..., output=y)``.
    """
    N = int(spec['n_samples']); k1 = int(spec['k1']); k2 = int(spec['k2'])
    P = int(spec['p_periods']); T_per = int(spec['t_periods'])
    n_exc = int(spec['n_exc']); q_all = np.arange(n_exc)
    if not (1 <= k1 <= k2 < N // 2):
        raise ValueError('multisine bins must satisfy 1 <= k1 <= k2 < N/2 '
                         '(got k1={}, k2={}, N={})'.format(k1, k2, N))
    k_bins = np.arange(k1, k2 + 1)
    n_lines = len(k_bins)
    A = float(spec['amp_rms']) * np.sqrt(2.0 / n_lines)
    rng = np.random.default_rng([int(spec['seed']), int(spec['m'])])
    phases = rng.uniform(0, 2 * np.pi, size=(n_exc, n_lines))
    phases = phases - 2 * np.pi * np.outer(q_all, np.ones(n_lines)) * int(spec['e']) / n_exc
    S = np.zeros((n_exc, N // 2 + 1), dtype=complex)
    S[:, k_bins] = 0.5 * N * A * np.exp(1j * phases)
    period = np.fft.irfft(S, n=N, axis=1)        # (n_exc, N)
    y = np.tile(period, (1, T_per + P)).T        # (samples, n_exc)
    peak = float(np.max(np.abs(y)))
    vmax = settings.output_vmax()
    if peak > vmax:
        raise ValueError('multisine peak {:.3g} V exceeds the output rail '
                         '±{:.3g} V — lower the level (amp_rms).'.format(peak, vmax))
    t = np.arange(y.shape[0]) / settings.output_fs
    return t, y
```

  Note `np.tile(period, (1, T_per+P))` tiles along axis 1 → shape (n_exc, (T+P)·N), then `.T`. Verify against the shape test.
- [ ] Run tests → PASS. Then full `python3 -m pytest -q` → no regressions (434 passed baseline).
- [ ] Commit: `feat(engine): multisine_generator — seeded periodic excitation with MISO rotation`

### Task 2: `calculate_bla` + synthetic test system + TfData/container extension

**Files:** Modify `pydvma/analysis.py` (new function near `calculate_tf_averaged`), `pydvma/datastructure.py` (TfData: 3 optional attrs), `pydvma/container.py` (`_ARRAY_FIELDS['TfData']` += `['bla_sigma_nl','bla_sigma_n']`, `_OPTIONAL_META['TfData']` += `['bla']`), `pydvma/testdata.py` (synthetic nonlinear MISO system). Test: create `tests/test_bla.py`. Read first: `analysis.py` `calculate_tf_averaged` + the `as_strided` comment block in `calculate_cross_spectrum_matrix`; `container.py` None-array handling ("e.g. TfData.tf_coherence").

- [ ] `datastructure.py`: in `TfData.__init__`, after `self.flag_modal_TF = False`, add `self.bla_sigma_nl = None`, `self.bla_sigma_n = None`, `self.bla = None` (documented in the class docstring Attributes: real (n_freq, n_outputs) σ arrays in FRF units + the BLA run-spec dict; None for ordinary TFs). Old pickles: `container.py` load path uses `.get`/getattr so absent attrs load as None — verify with the round-trip test below.
- [ ] `testdata.py`: add

```python
def create_test_bla_captures(M=6, n_exc=2, n_resp=2, N=2048, P=4, t_periods=2,
                             fs=8192.0, k1=8, k2=200, seed=42, amp_rms=0.1,
                             cubic=0.0, noise_rms=1e-4):
    """Synthetic BLA measurement: known linear MISO system + optional cubic
    distortion + additive output noise.

    Each response r is ``sum_q h_qr * x_q`` plus ``cubic·(sum_q x_q)**3``
    plus white noise, where ``h_qr`` are distinct known 2nd-order IIR
    filters (scipy.signal.lfilter, applied to 2 warmup periods + the
    capture so the filter state is periodic-steady). Returns
    ``(time_data_list, run_spec, G_true)`` — the M·n_exc TimeData list in
    (m, e) order, the BlaRunSpec, and ``G_true`` shape
    ``(n_freq_excited, n_resp, n_exc)`` from scipy.signal.freqz at the
    excited bins.

    Args: (one per line, griffe-strict) ...
    """
```

  Implementation: reuse `acquisition.multisine_generator` for x (channels 0..n_exc−1 of the capture are the measured x — clean copies BEFORE noise; add noise only to responses, matching the notes' output-noise model). Captures carry x in channels `0..n_exc-1`, responses in `n_exc..n_exc+n_resp-1`. Build TimeData with a minimal `MySettings(fs=fs, channels=n_exc+n_resp)`. IMPORTANT filter-state detail: lfilter over the FULL tiled buffer (t_periods≥2 warmup makes the response periodic to <1e-8 by the kept periods for these gentle filters — that's exactly what t_periods is for).
- [ ] Write failing tests (`tests/test_bla.py`):
  - `test_bla_linear_recovery_siso` (n_exc=1, n_resp=1, cubic=0, noise 1e-5): `G_BLA` vs `G_true` rel error < 1e-3 across excited bins; `bla_sigma_nl` ≈ 0 (< noise-dominated bound, i.e. ≤ ~3·bla_sigma_n).
  - `test_bla_linear_recovery_miso_nonsquare` (n_exc=2, n_resp=3): same assertions per (r,q).
  - `test_bla_detects_cubic` (n_exc=2, n_resp=2, cubic=0.5, noise 1e-5): median σ_NL over bins > 10× median σ_n; with cubic=0 the same statistic < 3×.
  - `test_bla_noise_estimate_calibrated` (cubic=0, noise_rms=1e-3): σ_n should predict the realisation scatter — assert median(σ²_tot)/median(σ²_n) within [0.5, 2] (they estimate the same thing when NL=0).
  - `test_bla_commanded_x` (n_exc=1, synthetic captures with x channels dropped, x_mode='commanded'): recovers G_true (the synthetic system is built on the exact generator output so commanded == measured here).
  - `test_bla_ordering_validation`: wrong-length time_data_list raises ValueError naming M·n_exc.
  - `test_tfdata_bla_roundtrip`: build a BLA TfData, save via `container` to .dvma, reload, assert σ arrays and `bla` dict survive and ordinary TfData still round-trips with the new fields None.
- [ ] Run → FAIL. Implement `analysis.calculate_bla`:

```python
def calculate_bla(time_data_list, run_spec):
    """Best Linear Approximation with noise/nonlinearity separation
    (Schoukens random-phase multisine method, SISO and MISO unified).

    Consumes the ``M × n_exc`` captures of a BLA run (ordering
    ``[(m, e) for m in 0..M-1 for e in 0..n_exc-1]``), slices exact
    ``N``-sample periods after discarding ``t_periods`` transients,
    DFTs each period (no window — the data is periodic by construction),
    and estimates per response channel: the BLA FRF matrix (mean over
    realisations of the per-realisation n×n solve), the noise std
    ``bla_sigma_n`` (period-to-period scatter propagated through the
    input-matrix inverse, 1/P folded in) and the nonlinear-distortion
    std ``bla_sigma_nl`` (realisation scatter minus noise, floored at 0).
    Start-time offsets between captures are harmless for measured x —
    x and y share the ADC clock so the common phase rotation cancels in
    the solve; for ``x_mode='commanded'`` the input spectra are
    regenerated analytically from the seed (valid ONLY on
    hardware-synced AO/AI — the caller enforces that).

    Args:
        time_data_list: list of TimeData in (m, e) order, length M·n_exc.
        run_spec: BlaRunSpec dict — see the design doc.

    Returns a list of ``n_exc`` TfData (one per excitation q), each with
    ``tf_data`` shape (n_excited_bins, n_resp), ``bla_sigma_nl``/
    ``bla_sigma_n`` same shape, ``tf_coherence=None``, and the run spec
    in ``.bla``.
    """
```

  Reference implementation (follow closely — the variance bookkeeping is the point of the method):

```python
    ms = run_spec['multisine']
    N, P, T_per = int(ms['n_samples']), int(ms['p_periods']), int(ms['t_periods'])
    M, n_exc = int(ms['M']), int(ms['n_exc'])
    k_bins = np.arange(int(ms['k1']), int(ms['k2']) + 1)
    resp = list(run_spec['resp_channels']); n_resp = len(resp)
    commanded = (run_spec.get('x_mode') == 'commanded')
    x_ch = None if commanded else list(run_spec['x_channels'])
    if len(time_data_list) != M * n_exc:
        raise ValueError(...)
    n_k = len(k_bins)
    Xbar = np.zeros((M, n_exc, n_exc, n_k), dtype=complex)  # [m, q, e, k]
    Ybar = np.zeros((M, n_exc, n_resp, n_k), dtype=complex) # [m, e, r, k]
    varY = np.zeros((M, n_exc, n_resp, n_k))
    for m in range(M):
        for e in range(n_exc):
            td = time_data_list[m * n_exc + e]
            data = td.time_data[T_per * N : (T_per + P) * N, :]
            if data.shape[0] != P * N:
                raise ValueError('capture too short: need {} samples after '
                                 '{} transient periods'.format(P * N, T_per))
            # (P, N, n_ch) view then rfft over axis 1; slices at k_bins.
            per = data.reshape(P, N, -1)          # C-contiguous slice → cheap
            spec = np.fft.rfft(per, axis=1)[:, k_bins, :]   # (P, n_k, n_ch)
            if not commanded:
                Xbar[m, :, e, :] = spec[:, :, x_ch].mean(axis=0).T  # (n_exc, n_k)
            Yp = spec[:, :, resp]                  # (P, n_k, n_resp)
            Ym = Yp.mean(axis=0)                   # (n_k, n_resp)
            Ybar[m, e] = Ym.T
            varY[m, e] = (np.abs(Yp - Ym) ** 2).sum(axis=0).T / (P - 1)
    if commanded:
        # Regenerate X̄ analytically: rfft of A·cos(2πkn/N+φ) at bin k is (N/2)·A·e^{jφ}.
        n_lines = n_k
        A = float(ms['amp_rms']) * np.sqrt(2.0 / n_lines)
        for m in range(M):
            rng = np.random.default_rng([int(ms['seed']), m])
            ph = rng.uniform(0, 2 * np.pi, size=(n_exc, n_lines))
            for e in range(n_exc):
                rot = ph - 2 * np.pi * np.arange(n_exc)[:, None] * e / n_exc
                Xbar[m, :, e, :] = 0.5 * N * A * np.exp(1j * rot)
    # Per-realisation solve, vectorised over k: X[m] is (n_k, n_exc(q), n_exc(e)).
    G = np.zeros((M, n_resp, n_exc, n_k), dtype=complex)
    var_nG = np.zeros((M, n_resp, n_exc, n_k))
    for m in range(M):
        Xk = np.transpose(Xbar[m], (2, 0, 1))          # (n_k, q, e)
        Xinv = np.linalg.inv(Xk)                       # (n_k, e, q)
        Yk = np.transpose(Ybar[m], (2, 1, 0))          # (n_k, r, e)
        G[m] = np.transpose(Yk @ Xinv, (1, 2, 0))      # (r, q, n_k)
        w = np.abs(Xinv) ** 2                          # (n_k, e, q)
        vY = np.transpose(varY[m], (2, 1, 0))          # (n_k, r, e)
        var_nG[m] = np.transpose(vY @ w, (1, 2, 0)) / P
    G_bla = G.mean(axis=0)                             # (r, q, n_k)
    var_tot = (np.abs(G - G_bla) ** 2).sum(axis=0) / (M - 1)
    var_n = var_nG.mean(axis=0)
    sigma_nl = np.sqrt(np.maximum(var_tot - var_n, 0.0))
    sigma_n = np.sqrt(var_n)
```

  Singular-X guard: wrap `np.linalg.inv` and raise a human message on `LinAlgError` ("input matrix singular — are two excitations identical / an x channel silent?"). Then build the n_exc TfData: freq axis `k_bins * fs / N` (fs = run_spec['fs'], the ACTUAL rate), `tf_data = G_bla[:, q, :].T` (n_k, n_resp), σ arrays likewise transposed, settings = copy of source settings with `ch_in = x_ch[q] if measured else None`, `ch_out_set = resp`, units via the `_tf_units_from_source` convention (read `calculate_tf`), `id_link` = list of the M·n_exc TimeData unique_ids, `.bla` = run_spec + `{'excited_bins': k_bins.tolist(), 'q': q}`. Memory: n_k can be ~10⁵ → all arrays here are (M·n_exc·n_resp·n_k) complex — for M=6,n=2,r=4,n_k=1e5 that's ~77 MB total; acceptable, but wrap the rfft loop in the repo's MemoryError catch pattern with the "too big" human message.
- [ ] Run `python3 -m pytest tests/test_bla.py -q` → PASS; full suite → no regressions.
- [ ] Commit: `feat(engine): calculate_bla — BLA + noise/NL separation, TfData bla fields, synthetic MISO testdata`

### Task 3: serve.py multisine output spec

**Files:** Modify `pydvma/serve.py` (`_OUTPUT_SPEC_KEYS` region ~:748-800). Test: extend the existing serve spec tests (find with `grep -rn "_build_output_signal\|output_spec" tests/`). Read `_build_output_signal` fully first.

- [ ] Failing tests: multisine spec accepted `{type:'multisine', amp, n_samples, k1, k2, p_periods, t_periods, seed, m, e, n_exc}`; unknown keys still rejected for classic types; missing multisine key → error naming it; `k2 >= N/2` → Nyquist-style error; duration is DERIVED (a supplied `duration` with type multisine → error "duration is derived from the spec").
- [ ] Implement: per-type keysets — `_OUTPUT_SPEC_KEYS_MULTISINE = frozenset({'type','amp','n_samples','k1','k2','p_periods','t_periods','seed','m','e','n_exc'})`; branch in `_build_output_signal`: validate ints, map `amp`→`amp_rms`, call `acquisition.multisine_generator(settings, spec)`. Keep the classic path byte-identical.
- [ ] Full pytest → green. Commit: `feat(serve): multisine output spec for BLA captures`

### Task 4: TS multisine twin

**Files:** Modify `webui/src/lib/audio/signal.ts`. Test: extend `webui/src/lib/audio/signal.test.ts` (or the existing signal test file — locate with `ls webui/src/lib/audio/*.test.ts`). Read the file header contract + existing generateStimulus first.

- [ ] Define `export interface MultisineSpec` (fields exactly as the shared contract; amp_rms normalised 0..1 here) and `export function generateMultisine(spec: MultisineSpec, fs: number): Float64Array[]` returning one Float64Array of length `(t_periods+p_periods)*n_samples` PER excitation channel. Seeded PRNG: implement `mulberry32(seed ^ m)`-style — deterministic, documented as NOT matching numpy (analysis never needs the phases to match; one path generates a whole run). Time-domain synthesis is fine (no FFT in this module): for each line `y[n] += A·cos(2π·k·(n%N)/N + φ)` computed once per period then tiled.
- [ ] Failing vitest: periodicity across tiles; flat line amplitudes (goertzel or naive DFT at a few bins); RMS ≈ amp_rms; seed determinism; rotation: n_exc=2, e=1 ⇒ channel 0 identical to e=0, channel 1 exactly negated; peak > limit throws (limit param like StimulusSpec.limit, default 1).
- [ ] Implement → vitest PASS → `npm run check` clean. Commit: `feat(webui): TS multisine generator twin`

### Task 5: browser multi-channel stimulus playback + bridge spec plumbing

**Files:** Modify `webui/src/lib/audio/source.ts` (buildStimulusNode ~:404, start ~:649), `webui/src/lib/audio/provider.ts` (RecordConfig/output types ~:400-430, :560+), `webui/src/lib/audio/bridge.ts` (`buildOutput` ~:565). Read all three regions FIRST — the record-config plumbing must extend the existing shape, not replace it.

- [ ] Extend the provider-level output spec union: classic `{type:'sweep'|'uniform'|'gaussian', amp, f1, f2, duration}` OR `{type:'multisine', ...MultisineSpec}`. `RecordConfig` (or the existing per-capture options object — use whatever `acquire.record()` already passes) gains optional `outputOverride` carrying that union so the BLA store can inject a per-capture stimulus without touching the Acquire card's UI state.
- [ ] Browser path: when the spec is multisine, `generateMultisine` → `AudioBuffer` with `numberOfChannels = n_exc` (fall back to error if `destination.maxChannelCount < n_exc`, message "this output device exposes N channels"). Duration = buffer length (ignore durationS).
- [ ] Bridge path: `buildOutput` emits the multisine keys verbatim when `outputOverride.type === 'multisine'`.
- [ ] Vitest: spec-plumbing unit tests (bridge message shape for a multisine override; browser buffer channel count) following the existing provider/bridge test style. Run vitest + `npm run check` → PASS. Commit: `feat(webui): multisine stimulus through browser and bridge capture paths`

### Task 6: glue op + codec

**Files:** Modify `webui/src/lib/worker/glue.py` (new `calc_bla` op modelled on `calc_tf_averaged` — read it first), `webui/src/lib/codec/dvma.ts` (TfData optional arrays `bla_sigma_nl`, `bla_sigma_n`, meta `bla` — follow how `tf_coherence`/`iw_power_counter` are declared). Tests: the codec vitest file + a glue pytest if `tests/test_webui_glue_*.py` has a tf precedent (it does — follow it).

- [ ] `calc_bla(payload)`: takes the raw time arrays (list, (m,e) order) + BlaRunSpec, builds TimeData, calls `analysis.calculate_bla`, marshals each TfData via the existing `_arr` conventions + the two σ arrays + `bla` meta. Guard with `hasattr(analysis, 'calculate_bla')` → "engine wheel too old" message (copy the `calc_sono`/CWT guard).
- [ ] Round-trip tests both layers. Commit: `feat(webui): calc_bla engine op + .dvma codec fields`

### Task 7: bla store + orchestration

**Files:** Create `webui/src/lib/stores/bla.ts`. Modify `webui/src/lib/analysis/actions.ts` (results landing + hidden raw sets). Read first: `stores/acquire.ts` (`record()`, `lastRecordingMeta`, `recordingToItem`), `actions.ts` (`addRecordedSet`, the `'across'` ensemble handling, `guarded`/`bump` stale-drop, and the calcDamping `engine.boot()` comment — the boot kick is MANDATORY for a first-compute), selection/tray store for per-set visibility.

- [ ] Store state: `{phase: 'idle'|'running'|'analysing'|'done'|'error'|'cancelled', m, e, M, n_exc, error, runSpec, rawSetIds: number[], resultSetIds: number[]}` + design params (band f1/f2, dfHz, amp, M, P, tPeriods, outputs table rows `{aoChannel, xMode: 'measured'|'commanded', xChannel}`, respChannels derived = all input channels minus measured-x ones).
- [ ] Derived values: `N = Math.round(fs/dfHz)`, `k1/k2 = Math.round(f·N/fs)` clamped to [1, N/2−1], `periodS = N/fs`, `totalS = M·n_exc·(tPeriods+P)·N/fs`.
- [ ] Preflight validation (all hard errors surfaced in the card, run refuses to start): output_fs === fs (read the acquire store's staged config — including the `reclampOutputFs` case, which must present as an error here, not a clamp); pretrigger unarmed (auto-disarm with an info note); commanded-x only when the provider reports the synced-NI condition (bridge caps: nidaq driver + shared-clock support + output_fs==fs; expose via a small provider/caps helper — read how `bridgeCaps` flows); n_exc ≤ available AO channels; measured-x channels distinct and within channel count.
- [ ] Run loop: `for m … for e …`: build MultisineSpec, `await acquire.record({outputOverride})`, `recordingToItem` → `addRecordedSet` with hidden-by-default visibility (find the tray/legend visibility API and set all the set's lines hidden), name `«test» r{m+1}e{e+1}`; honour a `cancel()` flag between captures (in-flight capture completes; sets already landed stay). On loop end: `engine.boot()` kick, then `calc_bla` through the worker with the raw arrays, land `n_exc` TfData result sets via a new `actions.addBlaSets(payloads)` that registers them like TF sets (tray family, view seeding to 'tf'), phase 'done'.
- [ ] Vitest: state machine (progress sequence, cancel semantics, preflight failures), spec construction (N/k rounding), with mocked acquire/provider — follow the existing store-test style. Commit: `feat(webui): BLA run store — orchestrated M×n captures + analysis dispatch`

### Task 8: Nonlin stage + card

**Files:** Modify `webui/src/lib/stores/stages.ts` (insert after 'tf': `{ id: 'bla', label: 'Nonlin', view: 'tf', needs: 'liveSource' }`), `webui/src/components/ContextCard.svelte` (the `{#if}` chain), create `webui/src/components/cards/BlaCard.svelte`. Read `SetupCard.svelte` + `AcquireCard.svelte` (group markup, `data-testid` conventions, advisory-note style) and the Fit card for the results-section pattern.

- [ ] Card sections (single card, three groups, `data-testid="bla-design" / "bla-run" / "bla-results"`):
  - Design: f1/f2 inputs; Δf input with derived readout **"period: N = 4096 samples = 0.500 s"** (always show BOTH sample count and seconds; update live; also show the excited-line count); level (RMS) with unit label V (bridge) / ×FS (browser); M, P, transient-periods number inputs (defaults 6/4/2); outputs table (row per driven AO channel: enable, x-source select listing input channels + "commanded drive" gated per preflight, gating tooltip when disabled); responses readout (chips of remaining channels); total-run-time readout.
  - Run: Start button (disabled with reason while preflight fails), progress `realisation m/M · experiment e/n`, Cancel.
  - Results: per-excitation summary (per-band verdict chip text: compare median σ²_tot vs σ²_n per octave-ish band — "linear at this level (averaging helps)" / "nonlinearity dominates 200–800 Hz (level-dependent — repeat at 2–3 amplitudes)"), buttons "show raw captures" (flips visibility of rawSetIds) and re-run.
- [ ] Stage gating follows Acquire (`needs: 'liveSource'`).
- [ ] Vitest where the card has logic worth testing (verdict banding function — export it pure). Playwright is Task 10. `npm run check` clean. Commit: `feat(webui): Nonlin stage + BLA card (design/run/results)`

### Task 9: TF-view σ overlay

**Files:** Modify `webui/src/lib/plot/model.ts` (read the coherence overlay branch ~:696-730 first — mirror it), `webui/src/lib/stores/viewstate.ts` (`ViewSlice` gains `blaSigma: boolean` default true), the TF card's toolbar/controls file (locate the coherence toggle and add "σ lines" beside it), `SetArrays.tf` in `model.ts` (optional `sigmaNl?`, `sigmaN?` arrays plumbed from the set payloads).

- [ ] For sets with σ arrays and `blaSigma` on: two extra `PlotLine`s per visible channel on the LEFT axis (same dB transform as |G|), dashed, width 1, opacity ~0.7, legend-suppressed if legend entries are per-line (check how coherence lines handle the legend and match).
- [ ] Vitest: buildPlotModel emits the σ lines exactly when arrays present + toggle on; dB mapping matches the main line's transform. Commit: `feat(webui): σ_NL/σ_n overlay on TF view for BLA sets`

### Task 10: wheel rebuild, e2e, full verification

**Files:** wheel via `npm run vendor:wheels` (then verify `ENGINE_WHEELS` in `webui/src/lib/stores/engine.ts` matches the rebuilt filename — version unchanged ⇒ no edit expected). Create `webui/e2e/bla.spec.ts` (read an existing engine-tagged spec + `bridge.spec.ts` for the mock-bridge harness).

- [ ] Playwright (FROM `webui/`): mock-bridge BLA run (small: M=2, P=2, N=512, n_exc=1) → assert progress text cycles, raw sets hidden, a BLA set appears in the tray, TF view shows 3 lines/channel (screenshot-assert composited pixels for the dashed σ lines per the repo's layered-canvas standard); browser-audio path smoke (mock getUserMedia — follow existing browser-path e2e). 
- [ ] Full gates, all green before commit: `python3 -m pytest -q` · `npm run check` · `npx vitest run` · `npx playwright test` (from webui/) · `python -m mkdocs build --strict` (from root).
- [ ] Commit: `test(e2e): BLA run end-to-end + engine wheel rebuild`

### Task 11: docs + TODO + design-doc sync

**Files:** Modify `docs/` Web Logger section (new "Noise & nonlinearity separation (Nonlin stage)" page or section: what the method does, the M/P/transient knobs, measured vs commanded x validity, reading the σ lines, level-sweep advice — written for the lab user, not the implementer), `mkdocs.yml` nav if paged, `TODO.md` (add: webui exposure of `use_output_as_ch0` [verified working + multi-channel, alignment assumed-not-measured]; BLA follow-ups: odd multisines/detection lines, automated level sweeps, PC hardware verification of the BLA path via bridge_hw_check extension), design doc: note the `multisine_generator` refinement. `python -m mkdocs build --strict` green (griffe-strict bites: one param per Args line). Commit: `docs: Nonlin stage user guide + TODO follow-ups`

### Task 12: Scarlett loopback smoke test (Fable-supervised, not delegated)

Headless script `dev/bla_soundcard_check.py` (untracked pattern? No — commit it, it's the sibling of `dev/bridge_hw_check.py`): soundcard driver, 2 outputs, measured x = loopback inputs 3/4 (device channels 2,3), M=4, P=3, N=4096 @ 48 kHz, band 50–5000 Hz; assert |G|≈1 flat on the loopback pairs (digital loopback ⇒ near-perfect), σ_NL ≪ |G|, print a summary table. Run it live on the 2i2 (Rigol off). This validates the whole Python path on real hardware without cables.

---

## Execution notes

- Dispatch order: Tasks 1→2→3 (Python track) can run while 4 runs (TS track); 5 needs 4; 6 needs 2; 7 needs 5+6; 8 needs 7; 9 needs 6; 10 needs all; 11/12 last. 
- Model levels: Tasks 2, 5, 7, 8, 10 → opus; Tasks 1, 3, 4, 6, 9, 11 → sonnet; Task 12 stays with the coordinator.
- Every subagent: read the named precedent files before writing; run the named test commands; commit exactly the listed scope; report the actual test output.
