"""Shared-pole modal fitting across sets on DIFFERENT frequency axes.

`modal_fit_all_channels` used to pick the in-band rows from the FIRST
TfData's axis and read the same rows of every other set, so a set on a
different axis (another sample rate or frame length, a stepped sine, the
separate measurements of a Vibration Apps CSV) was silently fitted with
the wrong frequencies — or raised an IndexError when it was shorter.
Now each set is fitted on its own points inside the band, the poles are
shared, and every column counts equally whatever its resolution
(``sqrt(n_ref / n_c)`` residual weighting). The same holds for
`modal_refine`, `reconstruct_transfer_function_global` and the web app's
`engine.calc_fit`, which no longer interpolates sets onto the first one's
axis.

Pure-Python, no hardware required.
"""
import contextlib
import io
import os

import numpy as np
import pytest

from pydvma import datastructure, engine, file, modal, options

EXAMPLE = os.path.join(os.path.dirname(__file__), 'data',
                       'vibration_apps_example.csv')

FN, ZN = 150.0, 0.02


def _quiet(fn, *args, **kwargs):
    """Call a fitter without its printed summary."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def _tf(f, amps, fn=FN, zn=ZN, measurement_type='vel', test_name='set',
        noise=0.0, seed=0):
    """A measured one-mode TfData on axis ``f``, one column per modal
    constant in ``amps``, built from the fitter's own model with no
    residual terms (so a noise-free fit can recover it exactly)."""
    f = np.asarray(f, dtype=float)
    cols = []
    for an in amps:
        row = np.array([fn, zn, an, 0.0, 0.0, 0.0])
        cols.append(modal.f_TF_all_channels(row, f, measurement_type)[:, 0])
    G = np.column_stack(cols)
    if noise:
        rng = np.random.default_rng(seed)
        scale = noise * np.max(np.abs(G))
        G = G + scale * (rng.standard_normal(G.shape)
                         + 1j * rng.standard_normal(G.shape))
    settings = options.MySettings(fs=1000, channels=len(amps))
    return datastructure.TfData(f, G, None, settings, test_name=test_name)


def _fit(tfs, freq_range, measurement_type='vel'):
    return _quiet(modal.modal_fit_all_channels,
                  datastructure.TfDataList(list(tfs)),
                  freq_range=freq_range, measurement_type=measurement_type)


# Two axes that do not line up: 0.5 Hz from 50 Hz, and 2 Hz from 51 Hz.
F_FINE = np.arange(50.0, 250.0 + 1e-9, 0.5)
F_COARSE = np.arange(51.0, 249.0 + 1e-9, 2.0)


class TestJointFitOnDifferentAxes:

    @pytest.mark.parametrize('measurement_type', ['acc', 'vel', 'dsp'])
    def test_recovers_the_true_mode(self, measurement_type):
        a = _tf(F_FINE, [1.0e4], measurement_type=measurement_type)
        b = _tf(F_COARSE, [0.7e4, -1.3e4], measurement_type=measurement_type)

        m = _fit([a, b], [100.0, 200.0], measurement_type)

        fn, zn, an, pn, _, _ = modal.unpack(np.ravel(m.M))
        assert fn == pytest.approx(FN, abs=1e-4)
        assert zn == pytest.approx(ZN, rel=1e-4)
        # one column per TF column, in list order, each with its own constant
        np.testing.assert_allclose(an * np.cos(pn), [1.0e4, 0.7e4, -1.3e4],
                                   rtol=1e-4)
        assert m.channels == 3

    def test_matches_each_set_fitted_alone(self):
        a = _tf(F_FINE, [1.0e4])
        b = _tf(F_COARSE, [0.7e4])

        joint = _fit([a, b], [100.0, 200.0])
        alone_a = _fit([a], [100.0, 200.0])
        alone_b = _fit([b], [100.0, 200.0])

        for alone in (alone_a, alone_b):
            assert joint.fn[0] == pytest.approx(alone.fn[0], abs=1e-4)
            assert joint.zn[0] == pytest.approx(alone.zn[0], rel=1e-4)
        assert joint.an[0, 0] == pytest.approx(alone_a.an[0, 0], rel=1e-4)
        assert joint.an[0, 1] == pytest.approx(alone_b.an[0, 0], rel=1e-4)

    def test_order_does_not_matter(self):
        # A little noise, so no parameter set fits exactly and the answer
        # is a genuine compromise between the two sets.
        a = _tf(F_FINE, [1.0e4], noise=0.02, seed=1)
        b = _tf(F_COARSE, [0.7e4], fn=FN + 1.0, noise=0.02, seed=2)

        ab = _fit([a, b], [100.0, 200.0])
        ba = _fit([b, a], [100.0, 200.0])

        assert ab.fn[0] == pytest.approx(ba.fn[0], abs=1e-6 * FN)
        assert ab.zn[0] == pytest.approx(ba.zn[0], rel=1e-5)
        # columns follow the list order
        assert ab.an[0, 0] == pytest.approx(ba.an[0, 1], rel=1e-5)
        assert ab.an[0, 1] == pytest.approx(ba.an[0, 0], rel=1e-5)

    def test_density_does_not_buy_weight(self):
        """Each column counts equally whatever its number of points: a set
        resampled four times denser pulls the shared pole no harder."""
        f_c = np.arange(101.0, 199.0 + 1e-9, 2.0)      # 50 points in band
        f_d = np.arange(100.25, 199.75 + 1e-9, 0.5)   # 200 points, 4x denser
        f_other = np.arange(100.5, 199.5 + 1e-9, 1.0)
        # Two systems that disagree, so the shared pole is a compromise
        # whose position depends on the relative weights.
        coarse = _tf(f_c, [1.0e4], fn=148.0, zn=0.05)
        dense = _tf(f_d, [1.0e4], fn=148.0, zn=0.05)
        other = _tf(f_other, [1.0e4], fn=152.0, zn=0.05)

        with_coarse = _fit([coarse, other], [100.0, 200.0])
        with_dense = _fit([dense, other], [100.0, 200.0])

        # Equal weights put the compromise near the middle either way ...
        assert 149.0 < with_coarse.fn[0] < 151.0
        assert 149.0 < with_dense.fn[0] < 151.0
        # ... and the density does not move it (measured: under 1e-6 Hz;
        # with every point weighted alike it moved 1.4 Hz of the 4 Hz the
        # two systems disagree by).
        assert abs(with_dense.fn[0] - with_coarse.fn[0]) < 0.01

    def test_set_with_no_points_in_band_raises_naming_it(self):
        a = _tf(F_FINE, [1.0e4], test_name='fine')
        sparse_f = np.array([60.0, 90.0, 210.0, 240.0])
        b = _tf(sparse_f, [1.0e4], test_name='sparse stepped sine')

        with pytest.raises(ValueError) as err:
            _fit([a, b], [100.0, 200.0])
        msg = str(err.value)
        assert "tf_data_list[1] ('sparse stepped sine')" in msg
        assert '100 to 200 Hz' in msg         # the band
        assert '60 to 240 Hz' in msg          # where its points are

    def test_no_points_message_without_a_name(self):
        """The web app's sets carry no test_name: the message then gives the
        list position and the span of the set's points."""
        a = _tf(F_FINE, [1.0e4])
        b = _tf(np.array([60.0, 90.0, 210.0, 240.0]), [1.0e4], test_name=None)

        with pytest.raises(ValueError, match=r"tf_data_list\[1\] has no frequency"):
            _fit([a, b], [100.0, 200.0])

    def test_default_band_is_the_union_of_the_axes(self):
        """freq_range=None spans every set, not just the first one."""
        lo = _tf(np.arange(100.0, 160.0, 0.5), [1.0e4], fn=140.0)
        hi = _tf(np.arange(130.0, 200.0, 0.5), [1.0e4], fn=140.0)

        m = _fit([lo, hi], None)

        assert m.fn[0] == pytest.approx(140.0, abs=1e-3)


class TestVibrationAppsExample:
    """The real file: m1 is 836 bins at 5.86 Hz from 105.47 Hz, m2 is
    13380 bins at 0.37 Hz from 100.34 Hz. Fitting them together used to
    read m2's rows at 101-106 Hz as if they were m1's 123-193 Hz."""

    @pytest.fixture(scope='class')
    def tfs(self):
        return file.import_from_vibration_apps_csv(EXAMPLE).tf_data_list

    @pytest.mark.parametrize('measurement_type', ['vel', 'acc'])
    def test_joint_fit_agrees_with_each_set_alone(self, tfs, measurement_type):
        band = [120.0, 200.0]
        m1, m2 = tfs[0], tfs[1]
        alone1 = _fit([m1], band, measurement_type)
        alone2 = _fit([m2], band, measurement_type)

        for order in ([m1, m2], [m2, m1]):
            joint = _fit(order, band, measurement_type)
            fn = joint.fn[0]
            assert abs(fn - alone1.fn[0]) < 0.5
            assert abs(fn - alone2.fn[0]) < 0.5
            lo = min(alone1.fn[0], alone2.fn[0]) - 0.05
            hi = max(alone1.fn[0], alone2.fn[0]) + 0.05
            assert lo < fn < hi
            # Each column's modal constant is its own set's, not a
            # constant fitted to the wrong rows (m2's came out -2.2
            # against 40.2 alone). They differ from the single fits by up
            # to ~20 % because the shared damping is a compromise between
            # m1 (zeta 0.035 on its coarse grid) and m2 (0.020).
            col = {id(m1): 0, id(m2): 1} if order[0] is m1 else {id(m2): 0, id(m1): 1}
            A = joint.an[0] * np.exp(1j * joint.pn[0])
            A1 = alone1.an[0, 0] * np.exp(1j * alone1.pn[0, 0])
            A2 = alone2.an[0, 0] * np.exp(1j * alone2.pn[0, 0])
            assert abs(A[col[id(m1)]] - A1) < 0.3 * abs(A1)
            assert abs(A[col[id(m2)]] - A2) < 0.3 * abs(A2)

    def test_both_orders_give_the_same_fit(self, tfs):
        m1, m2 = tfs[0], tfs[1]
        ab = _fit([m1, m2], [120.0, 200.0], 'acc')
        ba = _fit([m2, m1], [120.0, 200.0], 'acc')
        assert ab.fn[0] == pytest.approx(ba.fn[0], abs=1e-6)
        assert ab.zn[0] == pytest.approx(ba.zn[0], rel=1e-5)

    def test_four_measurements_of_one_system_fit_together(self, tfs):
        """m1-m4 measure the same demo system (160 Hz, zeta 0.02, modal
        constant 0.04 as an accelerance), on three different axes,
        including the 20-point stepped sine with three points in the band.
        (m5 has a mass added, so it is a different system.)"""
        m = _fit(list(tfs[:4]), [120.0, 200.0], 'acc')
        assert m.fn[0] == pytest.approx(160.0, abs=0.1)
        assert m.channels == 4
        A = m.an[0] * np.exp(1j * m.pn[0])
        np.testing.assert_allclose(np.abs(A), 0.04, rtol=0.15)
        assert np.max(np.abs(np.angle(A))) < np.deg2rad(10)


def _two_mode_tf(f, amps, rows=((120.0, 0.02), (180.0, 0.03)),
                 measurement_type='acc'):
    """Measured TF (no residuals) of two modes, one column per amplitude."""
    f = np.asarray(f, dtype=float)
    G = np.zeros((f.size, len(amps)), dtype=complex)
    for fn, zn in rows:
        for c, an in enumerate(amps):
            row = np.array([fn, zn, an, 0.0, 0.0, 0.0])
            G[:, c] += modal.f_TF_all_channels(row, f, measurement_type)[:, 0]
    return datastructure.TfData(f, G, None,
                                options.MySettings(fs=1000, channels=len(amps)))


class TestRefineAndReconstructOnDifferentAxes:

    F_A = np.arange(60.0, 260.0, 0.25)
    F_B = np.arange(61.0, 259.0, 1.5)

    def _pair(self):
        return [_two_mode_tf(self.F_A, [1.0e5]),
                _two_mode_tf(self.F_B, [0.6e5, -0.9e5])]

    def _seed(self):
        n_tfs = 3
        seed = datastructure.ModalData(
            np.concatenate(([116.0, 0.03], np.full(n_tfs, 1e5),
                            np.zeros(3 * n_tfs))),
            settings=options.MySettings(fs=1000, channels=n_tfs))
        seed.add_mode(np.concatenate(([184.0, 0.02], np.full(n_tfs, 1e5),
                                      np.zeros(3 * n_tfs))))
        return seed

    def test_refine_converges_to_the_true_poles(self):
        tfs = datastructure.TfDataList(self._pair())
        refined, info = modal.modal_refine(self._seed(), tfs,
                                           measurement_type='acc')
        assert info['converged'] is True
        assert info['cost_after'] < info['cost_before']
        np.testing.assert_allclose(np.sort(refined.fn), [120.0, 180.0],
                                   atol=1e-3)
        np.testing.assert_allclose(refined.zn, [0.02, 0.03], rtol=1e-3)
        # constants per column, in list order
        A = refined.an * np.exp(1j * refined.pn)
        np.testing.assert_allclose(A[0], [1.0e5, 0.6e5, -0.9e5], rtol=1e-3)

    def test_refine_order_does_not_matter(self):
        a, b = self._pair()
        r_ab, _ = modal.modal_refine(self._seed(), datastructure.TfDataList([a, b]),
                                     measurement_type='acc')
        r_ba, _ = modal.modal_refine(self._seed(), datastructure.TfDataList([b, a]),
                                     measurement_type='acc')
        np.testing.assert_allclose(r_ab.fn, r_ba.fn, rtol=1e-7)
        np.testing.assert_allclose(r_ab.zn, r_ba.zn, rtol=1e-5)

    def test_refine_set_with_no_points_in_band_raises(self):
        a = _two_mode_tf(self.F_A, [1.0e5])
        far = _two_mode_tf(np.array([300.0, 320.0, 340.0, 360.0, 380.0]), [1.0e5])
        far.test_name = 'far away'
        seed = datastructure.ModalData(
            np.concatenate(([120.0, 0.02], np.full(2, 1e5), np.zeros(6))),
            settings=options.MySettings(fs=1000, channels=2))
        with pytest.raises(ValueError, match='far away'):
            modal.modal_refine(seed, datastructure.TfDataList([a, far]),
                               freq_range=[100.0, 200.0], measurement_type='acc')

    def test_refine_band_too_narrow_for_every_set_uses_whole_axes(self):
        """No set has 2*n_modes + 2 points in the band: as for one set, the
        refinement widens to the whole axes (every set's) rather than fail."""
        tfs = datastructure.TfDataList(self._pair())
        refined, info = modal.modal_refine(self._seed(), tfs,
                                           freq_range=[119.9, 120.1],
                                           measurement_type='acc')
        assert info['converged'] is True
        np.testing.assert_allclose(np.sort(refined.fn), [120.0, 180.0],
                                   atol=1e-3)

    def test_global_reconstruction_constants_are_per_set(self):
        """A set's overlay comes from its own points only: adding another set
        (here one too sparse in the band, which falls back to its whole
        axis) does not change it."""
        a = _two_mode_tf(self.F_A, [1.0e5])
        sparse = _two_mode_tf(np.array([70.0, 125.0, 250.0]), [0.5e5])
        noisy = a.tf_data * (1 + 0.05 * np.cos(self.F_A))[:, None]
        a = datastructure.TfData(self.F_A, noisy, None, a.settings)

        def model(n_tfs):
            md = datastructure.ModalData(
                np.concatenate(([121.0, 0.025], np.ones(n_tfs), np.zeros(3 * n_tfs))),
                settings=options.MySettings(fs=1000, channels=n_tfs))
            md.add_mode(np.concatenate(([179.0, 0.028], np.ones(n_tfs),
                                        np.zeros(3 * n_tfs))))
            return md

        alone = modal.reconstruct_transfer_function_global(
            model(1), self.F_A, 'acc', tf_data_list=datastructure.TfDataList([a]))
        both = modal.reconstruct_transfer_function_global(
            model(2), self.F_A, 'acc',
            tf_data_list=datastructure.TfDataList([a, sparse]))
        np.testing.assert_allclose(both.tf_data[:, 0], alone.tf_data[:, 0],
                                   rtol=1e-12)
        assert np.all(np.isfinite(both.tf_data[:, 1]))

    def test_global_reconstruction_on_each_sets_own_axis(self):
        """At the true poles the re-estimated constants reproduce every
        set on its own axis (the constants are solved from each set's own
        points; those stored in M are ignored)."""
        tfs = self._pair()
        settings = options.MySettings(fs=1000, channels=3)
        truth = datastructure.ModalData(
            np.concatenate(([120.0, 0.02], np.full(3, 1.0), np.zeros(9))),
            settings=settings)
        truth.add_mode(np.concatenate(([180.0, 0.03], np.full(3, 1.0),
                                       np.zeros(9))))
        lst = datastructure.TfDataList(tfs)
        # columns 0 belong to set A, columns 1-2 to set B
        for tf, cols in ((tfs[0], slice(0, 1)), (tfs[1], slice(1, 3))):
            rg = modal.reconstruct_transfer_function_global(
                truth, tf.freq_axis, 'acc', tf_data_list=lst)
            assert rg.tf_data.shape == (tf.freq_axis.size, 3)
            band = (tf.freq_axis > 90) & (tf.freq_axis < 220)
            err = np.abs(rg.tf_data[band, cols] - tf.tf_data[band])
            assert np.max(err) < 1e-6 * np.max(np.abs(tf.tf_data[band]))


def _payload(tf):
    G = tf.tf_data
    flat = np.empty(G.size * 2)
    flat[0::2] = G.ravel().real
    flat[1::2] = G.ravel().imag
    return dict(freq_axis=tf.freq_axis, tf_data=flat, n_tf=G.shape[1],
                ch_in=None, n_channels=G.shape[1], fs=1000.0)


class TestEngineCalcFitOnDifferentAxes:

    def test_align_helper_is_gone(self):
        assert not hasattr(engine, '_align_fit_list')

    def test_fit_and_refine_keep_each_sets_axis(self):
        a = _two_mode_tf(np.arange(60.0, 260.0, 0.25), [1.0e5])
        b = _two_mode_tf(np.arange(61.0, 259.0, 1.5), [0.6e5, -0.9e5])
        sets = [_payload(a), _payload(b)]

        fit = _quiet(engine.calc_fit, sets=sets, measurement_type='acc',
                     freq_range=[90.0, 230.0], action='fit', n_modes=2)
        fns = np.sort(np.asarray(fit['fn']['data']))
        np.testing.assert_allclose(fns, [120.0, 180.0], atol=0.5)
        assert fit['M']['shape'][1] == 2 + 4 * 3
        assert [s['n_cols'] for s in fit['slices']] == [1, 2]
        for s, tf in zip(fit['slices'], (a, b)):
            ax = np.asarray(s['global_freq_axis']['data'])
            np.testing.assert_array_equal(ax, tf.freq_axis)
            assert s['global_tf_data']['shape'] == [tf.freq_axis.size,
                                                    tf.tf_data.shape[1]]
            # the overlay matches the measured lines on the set's own axis
            flat = np.asarray(s['global_tf_data']['data'])
            g = (flat[0::2] + 1j * flat[1::2]).reshape(tf.tf_data.shape)
            band = (tf.freq_axis > 100) & (tf.freq_axis < 200)
            err = np.abs(g[band] - tf.tf_data[band])
            assert np.max(err) < 0.02 * np.max(np.abs(tf.tf_data[band]))

        ref = _quiet(engine.calc_fit, sets=sets, M=fit['M'],
                     measurement_type='acc', action='refine')
        assert ref['converged'] is True
        np.testing.assert_allclose(np.sort(np.asarray(ref['fn']['data'])),
                                   [120.0, 180.0], atol=1e-3)
