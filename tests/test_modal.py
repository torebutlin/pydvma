"""Tests for `pydvma.modal` — fitting and reconstruction.

Covers the June 2026 review fixes: reconstruction functions mutating the
stored modal matrix / settings in place, degenerate-input guards in
modal_fit_all_channels, and an end-to-end synthetic round trip proving
the ensemble-averaged TF (post phase fix) feeds the modal fitter in the
convention it expects.

Pure-Python, no hardware required.
"""

import numpy as np
import pytest

from pydvma import analysis, datastructure, modal, options


# ---------- helpers ----------

def _make_modal_data(n_tfs=2, fn=100.0, zn=0.01, an=2.0, pn=0.1,
                     rk=0.5, rm=0.3, fs=1000):
    """One-mode ModalData with nonzero residual terms in the packed row
    [fn, zn, an x N, pn x N, rk x N, rm x N]."""
    row = np.concatenate((
        [fn], [zn],
        np.full(n_tfs, an), np.full(n_tfs, pn),
        np.full(n_tfs, rk), np.full(n_tfs, rm),
    ))
    settings = options.MySettings(fs=fs, channels=n_tfs)
    return datastructure.ModalData(row, settings=settings)


def _sdof_impulse_ensemble(fs=1000, n_samples=1000, f0=100.0, tau=0.1,
                           n_ensemble=3, noise=1e-4):
    """Ensemble of (delta input, SDOF displacement response) captures.

    ch0 is a unit sample at t=0 (flat spectrum, zero phase), ch1 the
    sampled impulse response h(t) = exp(-t/tau)·sin(2π·f0·t). The
    underlying continuous-time TF is wd / (wn² + 2j·ζ·wn·w − w²) with
    wd = 2π·f0, σ = 1/tau, wn = sqrt(σ² + wd²), ζ = σ/wn — i.e. the
    'dsp' form of modal.f_TF with positive amplitude and zero phase.
    """
    rng = np.random.default_rng(99)
    t = np.arange(n_samples) / fs
    h = np.exp(-t / tau) * np.sin(2 * np.pi * f0 * t)
    tdl = datastructure.TimeDataList()
    for _ in range(n_ensemble):
        x = np.zeros(n_samples)
        x[0] = 1.0
        y = h + noise * rng.standard_normal(n_samples)
        settings = options.MySettings(fs=fs, channels=2)
        tdl.append(datastructure.TimeData(
            t, np.column_stack([x, y]), settings,
            channel_cal_factors=np.ones(2), test_name='sdof',
        ))
    sigma = 1.0 / tau
    wd = 2 * np.pi * f0
    wn = np.sqrt(sigma ** 2 + wd ** 2)
    fn_true = wn / (2 * np.pi)
    zn_true = sigma / wn
    return tdl, fn_true, zn_true


# ---------- reconstruction must not mutate its input ----------

class TestReconstructionImmutability:

    def test_local_reconstruction_does_not_mutate_modal_data(self):
        m = _make_modal_data()
        M_before = m.M.copy()
        ch_before = m.settings.channels
        f = np.linspace(1, 200, 400)

        tf1 = modal.reconstruct_transfer_function(m, f)
        tf2 = modal.reconstruct_transfer_function(m, f)

        np.testing.assert_array_equal(m.M, M_before)
        assert m.settings.channels == ch_before
        np.testing.assert_allclose(tf1.tf_data, tf2.tf_data)
        assert tf1.flag_modal_TF is True
        # the reconstruction must not hand out the ModalData's own
        # settings object (later mutation would corrupt it)
        assert tf1.settings is not m.settings

    def test_global_reconstruction_does_not_mutate_modal_data(self):
        """The global variant excludes the local residual terms from the
        *output* but must not zero them inside modal_data.M (it was
        writing through a view)."""
        m = _make_modal_data(rk=0.5, rm=0.3)
        M_before = m.M.copy()
        f = np.linspace(1, 200, 400)

        tf_g1 = modal.reconstruct_transfer_function_global(m, f)
        tf_g2 = modal.reconstruct_transfer_function_global(m, f)

        np.testing.assert_array_equal(m.M, M_before)
        np.testing.assert_allclose(tf_g1.tf_data, tf_g2.tf_data)

        # and the residuals really are excluded from the global output:
        tf_local = modal.reconstruct_transfer_function(m, f)
        assert not np.allclose(tf_local.tf_data, tf_g1.tf_data)


# ---------- degenerate-input guards ----------

class TestModalFitGuards:

    def test_empty_list_raises_clear_error(self):
        with pytest.raises(ValueError, match='at least one'):
            modal.modal_fit_all_channels(datastructure.TfDataList())

    def test_all_reconstructions_raises_clear_error(self):
        m = _make_modal_data()
        f = np.linspace(1, 200, 400)
        tf = modal.reconstruct_transfer_function(m, f)  # flag_modal_TF=True
        with pytest.raises(ValueError, match='at least one'):
            modal.modal_fit_all_channels(datastructure.TfDataList([tf]))


# ---------- end-to-end: averaged TF feeds the fitter correctly ----------

class TestModalFitRoundTrip:

    def test_fit_recovers_synthetic_mode_from_averaged_tf(self):
        """Ensemble-averaged TF (H1, e^{+jωt} convention) fitted with
        measurement_type='dsp' must recover the known fn/zn with a
        positive amplitude and near-zero phase. With the pre-fix
        conjugated TF this fit returns a negative-amplitude/garbage-
        phase compromise, so this pins the TF↔fitter convention."""
        tdl, fn_true, zn_true = _sdof_impulse_ensemble()
        tf = analysis.calculate_tf_averaged(tdl, ch_in=0)

        m = modal.modal_fit_all_channels(
            datastructure.TfDataList([tf]),
            freq_range=[60.0, 140.0],
            measurement_type='dsp',
        )

        fn, zn, an, pn, rk, rm = modal.unpack(np.ravel(m.M))
        assert abs(fn - fn_true) < 1.0          # Hz
        assert abs(zn - zn_true) / zn_true < 0.2
        assert an[0] > 0
        assert abs(pn[0]) < np.deg2rad(15)
        assert m.channels == 1


# ---------- simultaneous multi-mode refinement (modal_refine) ----------

def _modal_row(fn, zn, an, pn=0.0, rk=0.0, rm=0.0, n_tfs=1):
    """Pack one mode in the modal.py 'x' layout: [fn, zn, an×N, pn×N, rk×N, rm×N]."""
    return np.concatenate((
        [fn], [zn],
        np.full(n_tfs, an), np.full(n_tfs, pn),
        np.full(n_tfs, rk), np.full(n_tfs, rm),
    ))


def _measured_tf_from_modes(rows, f, fs=1000, measurement_type='acc'):
    """Build a MEASURED TfData (flag_modal_TF=False) as the exact modal sum of
    `rows` over axis `f`, so a fit seeded near the truth can drive cost→0."""
    n_tfs = int((len(rows[0]) - 2) / 4)
    truth = datastructure.ModalData(rows[0], settings=options.MySettings(fs=fs, channels=n_tfs))
    for r in rows[1:]:
        truth.add_mode(r)
    recon = modal.reconstruct_transfer_function(truth, f, measurement_type)
    settings = options.MySettings(fs=fs, channels=n_tfs)
    return datastructure.TfData(f, recon.tf_data, None, settings), truth


class TestModalRefine:

    def test_refine_improves_cost_for_interacting_modes(self):
        """Two nearby modes whose skirts interact: a seed perturbed off the
        truth (as isolated/pair fits would be) must be pulled back so the
        simultaneous refinement reduces cost and reports convergence."""
        f = np.linspace(20.0, 260.0, 600)
        true_rows = [_modal_row(100.0, 0.020, 1.0e5),
                     _modal_row(140.0, 0.030, 0.8e5)]
        tf_meas, truth = _measured_tf_from_modes(true_rows, f)

        # seed: fn/zn deliberately off (the neighbours biased the isolated fits)
        seed = datastructure.ModalData(
            _modal_row(95.0, 0.032, 1.0e5),
            settings=options.MySettings(fs=1000, channels=1))
        seed.add_mode(_modal_row(146.0, 0.021, 0.8e5))

        refined, info = modal.modal_refine(
            seed, datastructure.TfDataList([tf_meas]), measurement_type='acc')

        assert info['converged'] is True
        assert info['cost_after'] < info['cost_before']
        # refined natural frequencies land much closer to the truth
        fn_ref = np.sort(refined.fn)
        assert abs(fn_ref[0] - 100.0) < 1.0
        assert abs(fn_ref[1] - 140.0) < 1.0
        assert refined.channels == 1
        assert refined.M.shape[0] == 2

    def test_refine_three_modes_multichannel(self):
        """Three modes across two channels: refinement keeps the channel
        geometry and returns a same-shaped model."""
        f = np.linspace(20.0, 400.0, 800)
        n_tfs = 2
        true_rows = [_modal_row(80.0, 0.02, 1.0e5, n_tfs=n_tfs),
                     _modal_row(160.0, 0.025, 0.7e5, n_tfs=n_tfs),
                     _modal_row(300.0, 0.03, 0.5e5, n_tfs=n_tfs)]
        tf_meas, truth = _measured_tf_from_modes(true_rows, f)

        seed = datastructure.ModalData(
            _modal_row(84.0, 0.03, 1.0e5, n_tfs=n_tfs),
            settings=options.MySettings(fs=1000, channels=n_tfs))
        seed.add_mode(_modal_row(155.0, 0.018, 0.7e5, n_tfs=n_tfs))
        seed.add_mode(_modal_row(305.0, 0.04, 0.5e5, n_tfs=n_tfs))

        refined, info = modal.modal_refine(
            seed, datastructure.TfDataList([tf_meas]))

        assert info['cost_after'] <= info['cost_before']
        assert refined.channels == n_tfs
        assert refined.M.shape == (3, 2 + 4 * n_tfs)

    def test_refine_reports_non_convergence_without_raising(self):
        """Pathological input (a non-finite sample in the measured TF) must be
        REPORTED (converged=False) — never raised — and still hand back a
        valid ModalData so the caller can revert.

        The NaN sits INSIDE the modes' fitted band (~140 Hz within [76, 184])
        so it genuinely reaches the solver. (The original test poisoned f[10]
        ≈ 26 Hz, OUTSIDE the band — it passed only because the old refine's
        cost drifted from exactly 0.0 off a perfect seed.)"""
        f = np.linspace(20.0, 260.0, 400)
        true_rows = [_modal_row(100.0, 0.02, 1.0e5),
                     _modal_row(160.0, 0.03, 0.8e5)]
        tf_meas, truth = _measured_tf_from_modes(true_rows, f)
        tf_meas.tf_data[200, 0] = np.nan    # ~140 Hz — inside the fit band

        refined, info = modal.modal_refine(
            truth, datastructure.TfDataList([tf_meas]))

        assert info['converged'] is False
        assert refined.M.shape[0] == 2      # seed handed back, still valid
        assert set(info) == {'converged', 'cost_before', 'cost_after'}

    def test_refine_empty_model_raises(self):
        """Refining a model with no modes is a programming error."""
        f = np.linspace(20.0, 260.0, 200)
        tf_meas, _ = _measured_tf_from_modes([_modal_row(100.0, 0.02, 1e5)], f)
        empty = datastructure.ModalData(settings=options.MySettings(fs=1000, channels=1))
        with pytest.raises(ValueError, match='at least one mode'):
            modal.modal_refine(empty, datastructure.TfDataList([tf_meas]))


# ---------- global linear re-estimation (round-7g) ----------

class TestGlobalReestimation:
    """`estimate_global_constants` (linear solve with fixed poles + per-channel
    global residues) and the re-estimated global reconstruction built on it."""

    F = np.linspace(5.0, 500.0, 2000)
    # Truth: two IN-BAND modes plus one below-band and one above-band mode —
    # the neighbours whose tails the global residues must absorb.
    IN_BAND = [(100.0, 0.02, 1.0e5), (140.0, 0.03, 0.8e5)]
    OUT_BAND = [(20.0, 0.05, 2.0e5), (450.0, 0.02, 3.0e5)]

    @classmethod
    def _measured(cls):
        rows = [_modal_row(fn, zn, an) for fn, zn, an in cls.IN_BAND + cls.OUT_BAND]
        tf_meas, _ = _measured_tf_from_modes(rows, cls.F)
        return tf_meas

    @classmethod
    def _band_sel(cls):
        return np.where((cls.F > 60.0) & (cls.F < 250.0))[0]

    def test_recovers_in_band_constants_with_global_residues(self):
        tf_meas = self._measured()
        sel = self._band_sel()
        f = self.F[sel]
        G0 = tf_meas.tf_data[sel, :]
        fn = [m[0] for m in self.IN_BAND]
        zn = [m[1] for m in self.IN_BAND]
        A, RH, RL, cost = modal.estimate_global_constants(fn, zn, f, G0, 'acc')
        # The in-band constants come back accurately and essentially REAL —
        # the out-of-band tails went into the residues, not the phases.
        assert abs(abs(A[0, 0]) - 1.0e5) / 1.0e5 < 0.05
        assert abs(abs(A[1, 0]) - 0.8e5) / 0.8e5 < 0.05
        assert np.max(np.abs(np.angle(A))) < 0.15
        # And the residues genuinely matter: without them (the naive 2-mode
        # sum with TRUE constants) the band residual is far larger.
        naive_rows = [_modal_row(fn_, zn_, an_) for fn_, zn_, an_ in self.IN_BAND]
        naive = sum(modal.f_TF_all_channels(r, f, 'acc') for r in naive_rows)
        naive_cost = 0.5 * float(np.sum(np.abs(naive - G0) ** 2))
        assert cost < 0.2 * naive_cost

    def test_global_reconstruction_reestimates_when_given_measured_tfs(self):
        tf_meas = self._measured()
        # A model holding only the two in-band modes, with POLLUTED local
        # rows: wrong amplitudes, significant local phases (the neighbour-
        # rotation artefact), junk local residues.
        md = datastructure.ModalData(
            _modal_row(100.0, 0.02, 0.7e5, pn=0.5, rk=3.0, rm=1e6),
            settings=options.MySettings(fs=1000, channels=1))
        md.add_mode(_modal_row(140.0, 0.03, 1.1e5, pn=-0.4, rk=1.0, rm=5e5))

        sel = self._band_sel()
        legacy = modal.reconstruct_transfer_function_global(md, self.F, 'acc')
        reest = modal.reconstruct_transfer_function_global(
            md, self.F, 'acc', tf_data_list=datastructure.TfDataList([tf_meas]))
        err_legacy = np.sum(np.abs(legacy.tf_data[sel] - tf_meas.tf_data[sel]) ** 2)
        err_reest = np.sum(np.abs(reest.tf_data[sel] - tf_meas.tf_data[sel]) ** 2)
        assert err_reest < 0.05 * err_legacy
        assert bool(reest.flag_modal_TF) is True

    def test_refine_recovers_poles_despite_polluted_local_rows(self):
        """The flat-direction scenario the varpro rebuild targets: a seed
        whose local rows carry junk constants/phases/residues must still
        refine to the true poles (the linear projection re-solves those
        parameters instead of letting them tug the poles around)."""
        tf_meas = self._measured()
        seed = datastructure.ModalData(
            _modal_row(97.0, 0.035, 0.5e5, pn=0.6, rk=2.0, rm=8e5),
            settings=options.MySettings(fs=1000, channels=1))
        seed.add_mode(_modal_row(144.0, 0.018, 1.4e5, pn=-0.5, rk=4.0, rm=2e5))

        refined, info = modal.modal_refine(
            seed, datastructure.TfDataList([tf_meas]), measurement_type='acc')
        assert info['converged'] is True
        fn_ref = np.sort(refined.fn)
        assert abs(fn_ref[0] - 100.0) < 0.5
        assert abs(fn_ref[1] - 140.0) < 0.5
        # The refined rows carry the GLOBAL constants: near-real phases.
        _, _, _, pn, rk, rm = modal.unpack_matrix(np.atleast_2d(refined.M))
        assert np.max(np.abs(np.angle(np.exp(1j * pn)))) < 0.2
        # Local residues are zeroed by contract (globals live in the recon).
        assert np.allclose(rk, 0) and np.allclose(rm, 0)
