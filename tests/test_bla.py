# -*- coding: utf-8 -*-
"""Tests for `pydvma.analysis.calculate_bla` — the Schoukens
random-phase-multisine best linear approximation with noise /
nonlinear-distortion separation.

The synthetic measurement comes from
`pydvma.testdata.create_test_bla_captures`: a known linear MISO system
(one stable digital resonance per input/output pair) plus an optional
instantaneous cubic nonlinearity plus additive output noise. Because
the truth is a digital filter, the exact per-bin FRF is
``scipy.signal.freqz`` of the very same coefficients — so the linear
recovery tests are exact to round-off plus noise, not approximate.

See `dev/plans/2026-08-10-schoukens-bla-design.md` for the method.
"""
import numpy as np
import pytest

import pydvma as dvma
from pydvma import analysis, container, datastructure, testdata


def _rel_error(G_est, G_ref):
    """Elementwise |G_est - G_ref| / |G_ref|."""
    return np.abs(G_est - G_ref) / np.abs(G_ref)


class TestLinearRecovery:
    def test_bla_linear_recovery_siso(self):
        """SISO, no distortion, tiny noise: the BLA must reproduce the
        known filter to 0.1%, and the NL estimate must stay down at the
        noise floor (nothing to detect)."""
        tds, run_spec, G_true = testdata.create_test_bla_captures(
            M=6, n_exc=1, n_resp=1, cubic=0.0, noise_rms=1e-5)
        tfs = analysis.calculate_bla(tds, run_spec)

        assert len(tfs) == 1
        tf = tfs[0]
        ms = run_spec['multisine']
        k_bins = np.arange(ms['k1'], ms['k2'] + 1)
        np.testing.assert_allclose(
            tf.freq_axis, k_bins * run_spec['fs'] / ms['n_samples'])
        assert tf.tf_data.shape == (len(k_bins), 1)
        assert tf.tf_coherence is None

        rel = _rel_error(tf.tf_data[:, 0], G_true[:, 0, 0])
        assert rel.max() < 1e-3, 'worst relative error {:.3g}'.format(rel.max())

        # Nothing nonlinear in the system: sigma_NL must not stand out
        # above the noise scatter it is differenced against.
        assert np.median(tf.bla_sigma_nl) <= 3 * np.median(tf.bla_sigma_n)

    def test_bla_linear_recovery_miso_nonsquare(self):
        """2 excitations x 3 responses — the non-square case: one TfData
        per excitation, each carrying all three responses, every element
        recovered to 0.1%."""
        tds, run_spec, G_true = testdata.create_test_bla_captures(
            M=6, n_exc=2, n_resp=3, cubic=0.0, noise_rms=1e-5)
        tfs = analysis.calculate_bla(tds, run_spec)

        assert len(tfs) == 2
        n_k = G_true.shape[0]
        for q, tf in enumerate(tfs):
            assert tf.tf_data.shape == (n_k, 3)
            assert tf.bla_sigma_nl.shape == (n_k, 3)
            assert tf.bla_sigma_n.shape == (n_k, 3)
            assert tf.bla['q'] == q
            for r in range(3):
                rel = _rel_error(tf.tf_data[:, r], G_true[:, r, q])
                assert rel.max() < 1e-3, (
                    'q={} r={} worst relative error {:.3g}'.format(
                        q, r, rel.max()))

    def test_bla_honours_channel_layout(self):
        """The channel role lists must actually be read.

        With the default layout (x first, then responses) the analysis
        would pass even if it ignored `x_channels`/`resp_channels`
        entirely and assumed that order. So scramble the capture columns
        and describe the scramble in the run spec: recovery must be
        unchanged, and the response ORDER must follow the list, not the
        column order.
        """
        tds, run_spec, G_true = testdata.create_test_bla_captures(
            M=6, n_exc=2, n_resp=2, cubic=0.0, noise_rms=1e-5)
        # captures are [x0, x1, y0, y1]; new column j takes old perm[j],
        # giving [y1, x1, y0, x0] — no role is left where it started.
        perm = [3, 1, 2, 0]
        for td in tds:
            td.time_data = np.ascontiguousarray(td.time_data[:, perm])
            td.units = [td.units[old] for old in perm]
        new_of = {old: new for new, old in enumerate(perm)}
        run_spec['x_channels'] = [new_of[0], new_of[1]]      # -> [3, 1]
        run_spec['resp_channels'] = [new_of[2], new_of[3]]   # -> [2, 0]

        tfs = analysis.calculate_bla(tds, run_spec)
        for q, tf in enumerate(tfs):
            assert tf.settings.ch_in == run_spec['x_channels'][q]
            assert tf.units == ['m/s/s/V', 'm/s/s/V']
            for r in range(2):
                rel = _rel_error(tf.tf_data[:, r], G_true[:, r, q])
                assert rel.max() < 1e-3, (
                    'q={} r={} worst relative error {:.3g}'.format(
                        q, r, rel.max()))


class TestNonlinearDetection:
    def test_bla_detects_cubic(self):
        """With a cubic nonlinearity the realisation scatter must exceed
        the propagated noise by a wide margin; with the same system and
        no cubic it must not."""
        common = dict(M=6, n_exc=2, n_resp=2, noise_rms=1e-5)

        tds, run_spec, _ = testdata.create_test_bla_captures(
            cubic=1.0, **common)
        tfs = analysis.calculate_bla(tds, run_spec)
        ratio_nl = [np.median(tf.bla_sigma_nl) / np.median(tf.bla_sigma_n)
                    for tf in tfs]
        assert min(ratio_nl) > 10, 'sigma_NL/sigma_n = {}'.format(ratio_nl)

        tds0, run_spec0, _ = testdata.create_test_bla_captures(
            cubic=0.0, **common)
        tfs0 = analysis.calculate_bla(tds0, run_spec0)
        ratio_lin = [np.median(tf.bla_sigma_nl) / np.median(tf.bla_sigma_n)
                     for tf in tfs0]
        assert max(ratio_lin) < 3, 'sigma_NL/sigma_n = {}'.format(ratio_lin)
        # The median is degenerate on a linear system (over half the bins
        # floor at zero), so also pin the non-degenerate mean.
        mean_lin = [np.mean(tf.bla_sigma_nl) / np.mean(tf.bla_sigma_n)
                    for tf in tfs0]
        assert max(mean_lin) < 3, 'mean sigma_NL/sigma_n = {}'.format(mean_lin)

    def test_bla_noise_estimate_calibrated(self):
        """The noise estimate must be calibrated, not merely ordered.

        (a) sigma_n matches the analytic prediction for white output
        noise of known rms propagated through the input inverse — this
        is what pins the 1/P factor; (b) with no nonlinearity the total
        realisation scatter and the propagated noise estimate agree,
        since they then measure the same thing.
        """
        tds, run_spec, _ = testdata.create_test_bla_captures(
            M=6, n_exc=1, n_resp=1, cubic=0.0, noise_rms=1e-3)
        tf = analysis.calculate_bla(tds, run_spec)[0]

        ms = run_spec['multisine']
        N, P = ms['n_samples'], ms['p_periods']
        n_lines = ms['k2'] - ms['k1'] + 1
        # One-period rfft magnitude of the excitation at an excited bin.
        X_mag = 0.5 * N * ms['amp_rms'] * np.sqrt(2.0 / n_lines)
        # E|Y_noise(k)|^2 = N * sigma^2 per period; the mean of P periods
        # divides that by P; dividing by |X| carries it onto G.
        sigma_n_expected = 1e-3 * np.sqrt(N / P) / X_mag
        # Tight on purpose (measured 0.982, and the run is seeded so this
        # is deterministic): a 1/P vs 1/(P-1) slip in the period-scatter
        # denominator lands at 0.850, outside the band.
        assert 0.9 < np.median(tf.bla_sigma_n) / sigma_n_expected < 1.25

        # sigma_NL^2 + sigma_n^2 is the realisation scatter (clamped at
        # the noise floor by the max(., 0) in the difference).
        sig2_tot = tf.bla_sigma_nl ** 2 + tf.bla_sigma_n ** 2
        sig2_n = tf.bla_sigma_n ** 2
        assert 0.5 < np.median(sig2_tot) / np.median(sig2_n) < 2.0


class TestCommandedInput:
    def test_bla_commanded_x(self):
        """Commanded-x mode regenerates the input spectra analytically
        from the seed. The synthetic captures hold the exact generator
        output, so the commanded result must match the measured one —
        which is the point: the regeneration law has to agree with
        `multisine_generator` bit for bit."""
        tds, run_spec, G_true = testdata.create_test_bla_captures(
            M=6, n_exc=1, n_resp=1, cubic=0.0, noise_rms=1e-5)
        # Distinct cal factors so the two conventions are separable:
        # measured x divides by the input channel's factor, commanded x
        # has no input channel and so must not divide at all.
        for td in tds:
            td.channel_cal_factors = np.array([2.0, 6.0])
        tf_measured = analysis.calculate_bla(tds, run_spec)[0]

        spec_cmd = dict(run_spec)
        spec_cmd['x_mode'] = 'commanded'
        spec_cmd['x_channels'] = None
        tf_cmd = analysis.calculate_bla(tds, spec_cmd)[0]

        rel = _rel_error(tf_cmd.tf_data[:, 0], G_true[:, 0, 0])
        assert rel.max() < 1e-3, 'worst relative error {:.3g}'.format(rel.max())
        np.testing.assert_allclose(tf_cmd.tf_data, tf_measured.tf_data,
                                   rtol=1e-10, atol=1e-12)
        # No measured input channel to name.
        assert tf_cmd.settings.ch_in is None
        assert tf_cmd.bla['x_mode'] == 'commanded'
        # Commanded drive: units are per volt, cal is the raw response
        # factor (nothing to divide by).
        assert tf_cmd.units == ['m/s/s/V']
        np.testing.assert_allclose(tf_cmd.channel_cal_factors, [6.0])
        # Measured x: the usual out/in ratio.
        assert tf_measured.units == ['m/s/s/V']
        np.testing.assert_allclose(tf_measured.channel_cal_factors, [3.0])

    def test_bla_commanded_x_miso(self):
        """Same, for THREE excitations — this is where the per-experiment
        rotation ``-2*pi*q*e/n_exc`` has to be reproduced exactly.

        Three, not two: with ``n_exc == 2`` the only nonzero rotation is
        a half turn, and ``exp(-j*pi) == exp(+j*pi)``, so a sign error in
        the rotation would go undetected. At ``n_exc == 3`` flipping the
        sign moves the regenerated spectra by ~170%.
        """
        tds, run_spec, G_true = testdata.create_test_bla_captures(
            M=6, n_exc=3, n_resp=2, cubic=0.0, noise_rms=1e-5)
        tf_measured = analysis.calculate_bla(tds, run_spec)
        spec_cmd = dict(run_spec)
        spec_cmd['x_mode'] = 'commanded'
        spec_cmd['x_channels'] = None
        tfs = analysis.calculate_bla(tds, spec_cmd)

        for q, tf in enumerate(tfs):
            for r in range(2):
                rel = _rel_error(tf.tf_data[:, r], G_true[:, r, q])
                assert rel.max() < 1e-3, (
                    'q={} r={} worst relative error {:.3g}'.format(
                        q, r, rel.max()))
            np.testing.assert_allclose(tf.tf_data, tf_measured[q].tf_data,
                                       rtol=1e-9, atol=1e-11)


class TestValidation:
    def test_bla_ordering_validation(self):
        """A capture list of the wrong length is a run-assembly bug and
        must say so, naming the expected count."""
        tds, run_spec, _ = testdata.create_test_bla_captures(
            M=3, n_exc=2, n_resp=1, N=256, P=2, t_periods=1,
            fs=2048.0, k1=4, k2=40, noise_rms=0.0)
        with pytest.raises(ValueError, match='6 captures'):
            analysis.calculate_bla(tds[:-1], run_spec)

    def test_bla_measured_mode_needs_x_channels(self):
        tds, run_spec, _ = testdata.create_test_bla_captures(
            M=3, n_exc=1, n_resp=1, N=256, P=2, t_periods=1,
            fs=2048.0, k1=4, k2=40, noise_rms=0.0)
        run_spec['x_channels'] = None
        with pytest.raises(ValueError, match='x_channels'):
            analysis.calculate_bla(tds, run_spec)

    def test_bla_channel_out_of_range_rejected(self):
        tds, run_spec, _ = testdata.create_test_bla_captures(
            M=3, n_exc=1, n_resp=1, N=256, P=2, t_periods=1,
            fs=2048.0, k1=4, k2=40, noise_rms=0.0)
        run_spec['resp_channels'] = [7]
        with pytest.raises(ValueError, match='out of range'):
            analysis.calculate_bla(tds, run_spec)

    def test_bla_solve_phase_oom_is_actionable(self, monkeypatch):
        """The 32-bit 'array is too big' guard must span the SOLVE phase,
        not just the capture loop: the solve allocates as much again
        while the capture-phase arrays are still live, so it is the
        likelier place to hit the ceiling."""
        tds, run_spec, _ = testdata.create_test_bla_captures(
            M=3, n_exc=1, n_resp=1, N=256, P=2, t_periods=1,
            fs=2048.0, k1=4, k2=40, noise_rms=0.0)

        def boom(*args, **kwargs):
            raise MemoryError('Unable to allocate array')

        monkeypatch.setattr(np.linalg, 'inv', boom)
        with pytest.raises(ValueError, match='too large an internal buffer'):
            analysis.calculate_bla(tds, run_spec)

    def test_bla_singular_input_matrix_not_swallowed(self, monkeypatch):
        """A genuine LinAlgError must surface as its own message, not be
        re-labelled by the memory guard it now sits inside."""
        tds, run_spec, _ = testdata.create_test_bla_captures(
            M=3, n_exc=1, n_resp=1, N=256, P=2, t_periods=1,
            fs=2048.0, k1=4, k2=40, noise_rms=0.0)

        def boom(*args, **kwargs):
            raise np.linalg.LinAlgError('Singular matrix')

        monkeypatch.setattr(np.linalg, 'inv', boom)
        with pytest.raises(ValueError, match='singular'):
            analysis.calculate_bla(tds, run_spec)

    def test_bla_short_capture_rejected(self):
        """A capture shorter than (t_periods + p_periods) periods can't
        be sliced and must raise rather than silently analyse garbage."""
        tds, run_spec, _ = testdata.create_test_bla_captures(
            M=3, n_exc=1, n_resp=1, N=256, P=2, t_periods=1,
            fs=2048.0, k1=4, k2=40, noise_rms=0.0)
        tds[0].time_data = tds[0].time_data[:-10, :]
        with pytest.raises(ValueError, match='too short'):
            analysis.calculate_bla(tds, run_spec)


class TestContainerRoundtrip:
    def _small_bla(self):
        tds, run_spec, _ = testdata.create_test_bla_captures(
            M=3, n_exc=1, n_resp=2, N=256, P=3, t_periods=1,
            fs=2048.0, k1=4, k2=40, noise_rms=1e-4)
        return analysis.calculate_bla(tds, run_spec)[0]

    def test_tfdata_bla_roundtrip(self, tmp_path):
        tf = self._small_bla()
        data = datastructure.DataSet(tf)
        path = tmp_path / 'bla.dvma'
        container.save(data, str(path))
        loaded = container.load(str(path)).tf_data_list[0]

        np.testing.assert_allclose(loaded.tf_data, tf.tf_data)
        np.testing.assert_allclose(loaded.bla_sigma_nl, tf.bla_sigma_nl)
        np.testing.assert_allclose(loaded.bla_sigma_n, tf.bla_sigma_n)
        assert loaded.tf_coherence is None
        # `bla` is a nested dict in the manifest — it must come back as an
        # equal dict, not a string or a type-tagged blob.
        assert isinstance(loaded.bla, dict)
        assert loaded.bla == tf.bla

    def test_ordinary_tfdata_roundtrip_unaffected(self, tmp_path):
        """The new fields must not disturb an ordinary transfer
        function: all three come back as None, present but empty — no
        absent-attribute asymmetry to guard against downstream."""
        data = dvma.create_test_impulse_data(noise_level=0)
        data.calculate_tf_set(ch_in=0)
        path = tmp_path / 'plain.dvma'
        container.save(data, str(path))
        loaded = container.load(str(path)).tf_data_list[0]

        assert loaded.bla_sigma_nl is None
        assert loaded.bla_sigma_n is None
        assert loaded.bla is None
        assert loaded.tf_coherence is not None
        np.testing.assert_allclose(loaded.tf_data,
                                   data.tf_data_list[0].tf_data)


class TestMetadata:
    def test_bla_metadata_and_settings(self):
        tds, run_spec, _ = testdata.create_test_bla_captures(
            M=3, n_exc=2, n_resp=2, N=256, P=2, t_periods=1,
            fs=2048.0, k1=4, k2=40, noise_rms=1e-5)
        # channels are [x0, x1, y0, y1]; all four factors distinct so the
        # inherited out/in RATIO is checkable per excitation.
        for td in tds:
            td.channel_cal_factors = np.array([2.0, 4.0, 3.0, 5.0])
        tfs = analysis.calculate_bla(tds, run_spec)

        expected_cal = {0: [1.5, 2.5], 1: [0.75, 1.25]}   # [3, 5] / cal_in
        for q, tf in enumerate(tfs):
            assert tf.bla['x_mode'] == 'measured'
            assert tf.bla['q'] == q
            assert tf.bla['excited_bins'] == list(range(4, 41))
            assert tf.bla['multisine']['M'] == 3
            assert tf.settings.ch_in == run_spec['x_channels'][q]
            np.testing.assert_array_equal(tf.settings.ch_out_set,
                                          np.array(run_spec['resp_channels']))
            # TF units and cal follow the usual out/in convention
            assert tf.units == ['m/s/s/V', 'm/s/s/V']
            np.testing.assert_allclose(tf.channel_cal_factors, expected_cal[q])
            # every capture is credited as a source
            assert len(tf.id_link) == 3 * 2
            assert tf.id_link[0] == tds[0].unique_id

    def test_bla_meta_lists_are_not_shared_between_excitations(self):
        """Each excitation's `bla` dict owns its lists — editing one must
        not reach through to its siblings."""
        tds, run_spec, _ = testdata.create_test_bla_captures(
            M=3, n_exc=2, n_resp=1, N=256, P=2, t_periods=1,
            fs=2048.0, k1=4, k2=40, noise_rms=0.0)
        tfs = analysis.calculate_bla(tds, run_spec)

        assert tfs[0].bla is not tfs[1].bla
        assert tfs[0].bla['excited_bins'] is not tfs[1].bla['excited_bins']
        assert tfs[0].bla['multisine'] is not tfs[1].bla['multisine']
        assert tfs[0].bla['resp_channels'] is not run_spec['resp_channels']
        tfs[0].bla['excited_bins'][0] = -1
        assert tfs[1].bla['excited_bins'][0] == 4

    def test_bla_metadata_is_json_clean(self, tmp_path):
        """The bla dict travels through the .dvma manifest, which is
        strict JSON — so it must hold only plain scalars, lists and
        dicts (no numpy types, no arrays)."""
        import json
        tds, run_spec, _ = testdata.create_test_bla_captures(
            M=3, n_exc=1, n_resp=1, N=256, P=2, t_periods=1,
            fs=2048.0, k1=4, k2=40, noise_rms=0.0)
        tf = analysis.calculate_bla(tds, run_spec)[0]
        json.dumps(tf.bla, allow_nan=False)   # raises if anything exotic


class TestTestData:
    def test_captures_ordering_and_shape(self):
        """The capture list is ordered ``[(m, e) for m ... for e ...]``
        and each capture carries x channels then response channels."""
        M, n_exc, n_resp = 3, 2, 2
        tds, run_spec, G_true = testdata.create_test_bla_captures(
            M=M, n_exc=n_exc, n_resp=n_resp, N=256, P=2, t_periods=1,
            fs=2048.0, k1=4, k2=40, noise_rms=0.0)
        assert len(tds) == M * n_exc
        for td in tds:
            assert td.time_data.shape == (3 * 256, n_exc + n_resp)
        assert run_spec['x_channels'] == [0, 1]
        assert run_spec['resp_channels'] == [2, 3]
        assert G_true.shape == (37, n_resp, n_exc)

        # The DFT-matrix rotation shifts excitation q by -2*pi*q*e/n_exc,
        # so within a realisation excitation 0 is the SAME in every
        # experiment while excitation 1 is rotated...
        np.testing.assert_allclose(tds[0].time_data[:, 0],
                                   tds[1].time_data[:, 0], atol=1e-12)
        assert not np.allclose(tds[0].time_data[:, 1], tds[1].time_data[:, 1])
        # ...and a new realisation redraws every phase.
        assert not np.allclose(tds[0].time_data[:, 0], tds[2].time_data[:, 0])

    def test_captures_are_periodic(self):
        """The excitation channels are exactly periodic — that is what
        lets calculate_bla DFT without a window."""
        tds, run_spec, _ = testdata.create_test_bla_captures(
            M=1, n_exc=1, n_resp=1, N=256, P=3, t_periods=1,
            fs=2048.0, k1=4, k2=40, noise_rms=0.0)
        x = tds[0].time_data[:, 0]
        np.testing.assert_allclose(x[:256], x[256:512], atol=1e-12)
