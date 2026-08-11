"""Tests for `pydvma.acquisition.multisine_generator` — the seeded,
exactly-periodic random-phase multisine excitation used by the
Schoukens BLA (best-linear-approximation) workflow.

See `dev/plans/2026-08-10-schoukens-bla-design.md` for the method and
`dev/plans/2026-08-10-schoukens-bla-plan.md` (Task 1) for the
MultisineSpec contract these tests pin down.
"""
import numpy as np
import pytest

from pydvma import options
from pydvma.acquisition import multisine_generator


def _settings(output_fs=8192, output_channels=2, output_VmaxSC=10.0):
    """A minimal soundcard-path MySettings for multisine tests.

    A generous ``output_VmaxSC`` (default 10 V) keeps ordinary test
    specs well clear of the peak guard; `test_peak_guard` overrides it
    down to provoke the guard deliberately.
    """
    return options.MySettings(
        device_driver='soundcard',
        fs=output_fs,
        output_fs=output_fs,
        channels=output_channels,
        output_channels=output_channels,
        output_device_driver='soundcard',
        output_VmaxSC=output_VmaxSC,
    )


def _spec(**overrides):
    spec = dict(
        n_samples=64,
        k1=4,
        k2=10,
        p_periods=3,
        t_periods=2,
        seed=42,
        m=0,
        e=0,
        n_exc=2,
        amp_rms=0.1,
    )
    spec.update(overrides)
    return spec


class TestShape:
    def test_shape(self):
        settings = _settings()
        spec = _spec()
        t, y = multisine_generator(settings, spec)
        n_periods = spec['t_periods'] + spec['p_periods']
        assert y.shape == (n_periods * spec['n_samples'], spec['n_exc'])
        assert len(t) == y.shape[0]
        assert np.allclose(np.diff(t), 1.0 / settings.output_fs)

    def test_c_contiguous_at_n_exc_2(self):
        """`np.tile(period, ...).T` is an F-contiguous VIEW whenever
        n_exc >= 2 -- sounddevice's OutputStream.write raises TypeError
        on non-C-contiguous data, which would break every MISO
        soundcard/bridge playback (the real Scarlett 2i2 test case).
        n_exc=1 happens to pass this check even without the fix, since
        a single-column array is trivially both C- and F-contiguous --
        that's an accident of shape, not evidence the bug is absent.
        """
        settings = _settings(output_channels=2)
        spec = _spec(n_exc=2)
        t, y = multisine_generator(settings, spec)
        assert y.flags['C_CONTIGUOUS']

    def test_c_contiguous_at_n_exc_1_too(self):
        settings = _settings(output_channels=1)
        spec = _spec(n_exc=1)
        t, y = multisine_generator(settings, spec)
        assert y.flags['C_CONTIGUOUS']


class TestExactPeriodicity:
    def test_exact_periodicity(self):
        settings = _settings()
        spec = _spec()
        N = spec['n_samples']
        n_periods = spec['t_periods'] + spec['p_periods']
        t, y = multisine_generator(settings, spec)

        first = y[:N]
        for p in range(1, n_periods):
            this_period = y[p * N:(p + 1) * N]
            assert np.allclose(first, this_period), (
                'period {} does not exactly match period 0'.format(p))


class TestSpectralFlatness:
    def test_spectral_flatness(self):
        settings = _settings()
        spec = _spec()
        N = spec['n_samples']
        k1, k2 = spec['k1'], spec['k2']
        n_lines = k2 - k1 + 1
        A = spec['amp_rms'] * np.sqrt(2.0 / n_lines)
        expected_mag = 0.5 * N * A

        t, y = multisine_generator(settings, spec)
        one_period = y[:N]
        spectrum = np.fft.rfft(one_period, axis=0)
        mags = np.abs(spectrum)

        excited = np.arange(k1, k2 + 1)
        not_excited = np.array(
            [k for k in range(spectrum.shape[0]) if k not in excited])

        # Excited bins: flat, and equal to the analytically expected
        # magnitude, within a tiny relative tolerance.
        for ch in range(y.shape[1]):
            rel_err = np.abs(mags[excited, ch] - expected_mag) / expected_mag
            assert np.all(rel_err < 1e-9), rel_err.max()

        # Everything else: at the floating-point noise floor, scaled
        # to the excited-bin magnitude (not an absolute constant).
        abstol = 1e-9 * N * A
        for ch in range(y.shape[1]):
            assert np.all(mags[not_excited, ch] < abstol)


class TestRmsLevel:
    def test_rms_level(self):
        settings = _settings()
        spec = _spec(amp_rms=0.25)
        N = spec['n_samples']
        t, y = multisine_generator(settings, spec)
        one_period = y[:N]
        rms = np.sqrt(np.mean(one_period ** 2, axis=0))
        assert np.allclose(rms, spec['amp_rms'], rtol=1e-9)


class TestSisoCoverage:
    """SISO (n_exc=1) is the degenerate case of the general MISO
    generator -- exercise shape, RMS and flatness explicitly rather
    than relying on the n_exc=2 tests to cover it implicitly."""

    def test_siso_shape(self):
        settings = _settings(output_channels=1)
        spec = _spec(n_exc=1, e=0)
        n_periods = spec['t_periods'] + spec['p_periods']
        t, y = multisine_generator(settings, spec)
        assert y.shape == (n_periods * spec['n_samples'], 1)

    def test_siso_rms(self):
        settings = _settings(output_channels=1)
        spec = _spec(n_exc=1, e=0, amp_rms=0.25)
        N = spec['n_samples']
        t, y = multisine_generator(settings, spec)
        rms = np.sqrt(np.mean(y[:N] ** 2, axis=0))
        assert np.allclose(rms, spec['amp_rms'], rtol=1e-9)

    def test_siso_flatness(self):
        settings = _settings(output_channels=1)
        spec = _spec(n_exc=1, e=0)
        N = spec['n_samples']
        k1, k2 = spec['k1'], spec['k2']
        n_lines = k2 - k1 + 1
        A = spec['amp_rms'] * np.sqrt(2.0 / n_lines)
        expected_mag = 0.5 * N * A

        t, y = multisine_generator(settings, spec)
        spectrum = np.fft.rfft(y[:N], axis=0)
        mags = np.abs(spectrum)
        excited = np.arange(k1, k2 + 1)
        rel_err = np.abs(mags[excited, 0] - expected_mag) / expected_mag
        assert np.all(rel_err < 1e-9)


class TestSeedReproducibility:
    def test_same_spec_identical_output(self):
        settings = _settings()
        spec = _spec()
        t1, y1 = multisine_generator(settings, spec)
        t2, y2 = multisine_generator(settings, dict(spec))
        assert np.array_equal(y1, y2)
        assert np.array_equal(t1, t2)

    def test_different_realisation_differs(self):
        settings = _settings()
        t0, y0 = multisine_generator(settings, _spec(m=0))
        t1, y1 = multisine_generator(settings, _spec(m=1))
        assert not np.allclose(y0, y1)


class TestRotationOrthogonality:
    def test_condition_number_and_sign_relation(self):
        settings = _settings()
        N = 64
        k1, k2 = 4, 10
        n_exc = 2

        spec_e0 = _spec(n_samples=N, k1=k1, k2=k2, n_exc=n_exc, e=0)
        spec_e1 = _spec(n_samples=N, k1=k1, k2=k2, n_exc=n_exc, e=1)
        _, y0 = multisine_generator(settings, spec_e0)
        _, y1 = multisine_generator(settings, spec_e1)

        one_period_0 = y0[:N]   # (N, n_exc)
        one_period_1 = y1[:N]

        spec0 = np.fft.rfft(one_period_0, axis=0)   # (N//2+1, n_exc)
        spec1 = np.fft.rfft(one_period_1, axis=0)

        excited = np.arange(k1, k2 + 1)
        for k in excited:
            # X[q, e]: rows = excitation channel q, columns = experiment e
            X = np.stack([spec0[k, :], spec1[k, :]], axis=1)
            cond = np.linalg.cond(X)
            assert np.isclose(cond, 1.0, atol=1e-6), (k, cond)

        # e=0 vs e=1: q=0 (row 0) unchanged (rotation angle 0), q=1
        # (row 1) exactly negated (rotation angle -pi at n_exc=2).
        assert np.allclose(one_period_0[:, 0], one_period_1[:, 0])
        assert np.allclose(one_period_0[:, 1], -one_period_1[:, 1])

    def test_full_rotation_law_and_conditioning_n_exc_3(self):
        """n_exc=2 is a blind spot for the rotation law: at e=1 the
        per-line phase shift is exactly -pi, and exp(-j*pi) ==
        exp(+j*pi), so a sign bug in the rotation direction would still
        pass. n_exc=3 has no such symmetry (shifts of -2*pi/3 and
        -4*pi/3 are distinguishable from their conjugates), so this
        checks the full complex law: spec_e[k, q] ~= spec_0[k, q] *
        exp(-2j*pi*q*e/n_exc), plus the per-bin 3x3 X[q, e] matrix is
        still well conditioned (condition number ~= 1).
        """
        settings = _settings(output_channels=3)
        N = 64
        k1, k2 = 4, 10
        n_exc = 3

        spectra = {}
        for e in range(n_exc):
            spec = _spec(n_samples=N, k1=k1, k2=k2, n_exc=n_exc, e=e)
            _, y = multisine_generator(settings, spec)
            spectra[e] = np.fft.rfft(y[:N], axis=0)   # (N//2+1, n_exc)

        excited = np.arange(k1, k2 + 1)
        q_all = np.arange(n_exc)

        for k in excited:
            for e in (1, 2):
                expected = spectra[0][k, :] * np.exp(-2j * np.pi * q_all * e / n_exc)
                assert np.allclose(spectra[e][k, :], expected, atol=1e-6), (k, e)

            # X[q, e]: rows = excitation channel q, columns = experiment e
            X = np.stack([spectra[e][k, :] for e in range(n_exc)], axis=1)
            cond = np.linalg.cond(X)
            assert np.isclose(cond, 1.0, atol=1e-6), (k, cond)


class TestPeakGuard:
    def test_illegal_level_raises_with_rail_and_peak_in_message(self):
        # A tiny voltage rail against a normal-sized excitation
        # guarantees the peak exceeds it.
        spec = _spec(amp_rms=0.1)

        # The waveform itself (and hence its peak) doesn't depend on
        # the rail, only on the spec -- so generate it once against a
        # generous rail to learn the actual peak the guard will see,
        # independent of the implementation's internals.
        permissive_settings = _settings(output_VmaxSC=1000.0)
        t, y = multisine_generator(permissive_settings, spec)
        expected_peak = float(np.max(np.abs(y)))
        expected_peak_str = '{:.3g}'.format(expected_peak)

        settings = _settings(output_VmaxSC=0.01)
        with pytest.raises(ValueError) as excinfo:
            multisine_generator(settings, spec)
        msg = str(excinfo.value)
        assert 'rail' in msg
        assert '0.01' in msg  # the rail voltage appears in the message
        assert expected_peak_str in msg  # the peak value appears too

    def test_legal_level_is_not_rescaled(self):
        """A legal amp_rms may still peak above amp_rms itself (crest
        factor > 1 for a multisine) — that is expected and must NOT
        trigger any silent rescale. Confirm by re-checking spectral
        flatness: a rescale would shrink the excited-bin magnitude
        below the analytic prediction.
        """
        settings = _settings(output_VmaxSC=10.0)
        spec = _spec(amp_rms=0.1)
        N = spec['n_samples']
        k1, k2 = spec['k1'], spec['k2']
        n_lines = k2 - k1 + 1
        A = spec['amp_rms'] * np.sqrt(2.0 / n_lines)
        expected_mag = 0.5 * N * A

        t, y = multisine_generator(settings, spec)
        one_period = y[:N]

        # crest factor > 1: peak exceeds the RMS target amp_rms.
        assert np.max(np.abs(one_period)) > spec['amp_rms']

        spectrum = np.fft.rfft(one_period, axis=0)
        mags = np.abs(spectrum)
        excited = np.arange(k1, k2 + 1)
        for ch in range(y.shape[1]):
            rel_err = np.abs(mags[excited, ch] - expected_mag) / expected_mag
            assert np.all(rel_err < 1e-9)


class TestBinBoundsValidation:
    """Each of the three ways to violate ``1 <= k1 <= k2 <= (N-1)//2``
    must raise ValueError, with the message identifying k1, k2 and N.

    ``(N-1)//2`` is identical to the old ``N/2``-exclusive bound for
    even N, but for ODD N it is one bin higher: an odd-length rFFT has
    no pure Nyquist bin at all, so its topmost bin, index (N-1)//2, is
    a perfectly legitimate line to excite. A strict ``k2 < N//2`` check
    (integer division) wrongly rejected exactly that bin for odd N,
    since floor(N//2) == (N-1)//2 when N is odd.
    """

    def _assert_raises_with_k1_k2_N(self, settings, spec):
        with pytest.raises(ValueError) as excinfo:
            multisine_generator(settings, spec)
        msg = str(excinfo.value)
        assert 'k1' in msg
        assert 'k2' in msg
        assert 'N' in msg

    def test_k1_below_one(self):
        settings = _settings()
        spec = _spec(k1=0, k2=10)
        self._assert_raises_with_k1_k2_N(settings, spec)

    def test_k2_at_or_above_nyquist_bin_even_n(self):
        settings = _settings()
        N = 64
        spec = _spec(n_samples=N, k1=4, k2=N // 2)  # k2 == N/2 is illegal
        self._assert_raises_with_k1_k2_N(settings, spec)

    def test_k1_greater_than_k2(self):
        settings = _settings()
        spec = _spec(k1=10, k2=4)
        self._assert_raises_with_k1_k2_N(settings, spec)

    def test_odd_n_top_bin_is_legal(self):
        """Regression for the off-by-one: for odd N, k2 == (N-1)//2
        must be ACCEPTED, not rejected."""
        settings = _settings()
        N = 65
        top_bin = (N - 1) // 2
        spec = _spec(n_samples=N, k1=4, k2=top_bin)
        t, y = multisine_generator(settings, spec)   # must not raise
        assert y.shape[0] == (spec['t_periods'] + spec['p_periods']) * N

    def test_odd_n_one_past_top_bin_still_illegal(self):
        settings = _settings()
        N = 65
        top_bin = (N - 1) // 2
        spec = _spec(n_samples=N, k1=4, k2=top_bin + 1)
        self._assert_raises_with_k1_k2_N(settings, spec)


class TestDegenerateGuards:
    """n_exc < 1, a zero total period count, and an out-of-range e all
    raised opaque numpy errors (or silently aliased) before these
    guards existed; now they raise a clear ValueError."""

    def test_n_exc_below_one_raises(self):
        settings = _settings()
        spec = _spec(n_exc=0, e=0)
        with pytest.raises(ValueError, match='n_exc'):
            multisine_generator(settings, spec)

    def test_zero_total_periods_raises(self):
        settings = _settings()
        spec = _spec(t_periods=0, p_periods=0)
        with pytest.raises(ValueError, match='t_periods'):
            multisine_generator(settings, spec)

    def test_e_out_of_range_raises(self):
        settings = _settings()
        spec = _spec(n_exc=2, e=2)   # legal range is 0..n_exc-1
        with pytest.raises(ValueError, match='e must satisfy'):
            multisine_generator(settings, spec)

    def test_e_negative_raises(self):
        settings = _settings()
        spec = _spec(n_exc=2, e=-1)
        with pytest.raises(ValueError, match='e must satisfy'):
            multisine_generator(settings, spec)


class TestOutputChannelsGuard:
    def test_n_exc_exceeds_output_channels_raises(self):
        settings = _settings(output_channels=1)
        spec = _spec(n_exc=2, e=0)
        with pytest.raises(ValueError) as excinfo:
            multisine_generator(settings, spec)
        msg = str(excinfo.value)
        assert 'n_exc' in msg
        assert 'output_channels' in msg
        assert '2' in msg  # n_exc
        assert '1' in msg  # output_channels
