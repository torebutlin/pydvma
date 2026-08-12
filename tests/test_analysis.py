"""Golden tests for `pydvma.analysis`.

These tests pin the *current* implementation of `calculate_fft`,
`calculate_cross_spectrum_matrix`, and `calculate_tf` against
deterministic synthetic signals and direct scipy reference
calculations. They are intended to act as a safety net for the
Phase A step 3 vectorisation of `calculate_cross_spectrum_matrix` —
the refactored implementation must produce numerically identical
output.

Pure-Python, no hardware required: runs on Mac/Linux/Windows.
"""

import numpy as np
import pytest
from scipy import signal

from pydvma import analysis, datastructure, options


# ---------- shared signal helpers ----------

def _make_time_data(time_data_array, fs):
    """Wrap a (N_samples, N_chans) array in a `TimeData` with default cal."""
    settings = options.MySettings(fs=fs, channels=time_data_array.shape[1])
    time_axis = np.arange(time_data_array.shape[0]) / fs
    return datastructure.TimeData(
        time_axis,
        time_data_array,
        settings,
        channel_cal_factors=np.ones(time_data_array.shape[1]),
        test_name='test',
    )


def _two_channel_sines(fs, n_samples, f1, f2, seed=0):
    """Two sine channels at f1, f2 with a small reproducible noise floor."""
    rng = np.random.default_rng(seed)
    t = np.arange(n_samples) / fs
    x = np.sin(2 * np.pi * f1 * t) + 1e-3 * rng.standard_normal(n_samples)
    y = np.sin(2 * np.pi * f2 * t) + 1e-3 * rng.standard_normal(n_samples)
    return np.column_stack([x, y])


def _linear_system_signals(fs, n_samples, fir_taps, seed=0):
    """White-noise input x, output y = fir_taps * x (causal FIR, no noise)."""
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n_samples)
    y = np.convolve(x, fir_taps, mode='full')[:n_samples]
    return np.column_stack([x, y])


# ---------- calculate_fft ----------

class TestCalculateFft:

    def test_pure_sine_amplitude(self):
        """Unit-amplitude sine at a bin-aligned frequency → |FFT| = N/2 at that bin."""
        fs = 1000
        N = 1000
        f0 = 50  # exactly bin-aligned (50 Hz × 1 s = 50 cycles)
        t = np.arange(N) / fs
        x = np.sin(2 * np.pi * f0 * t)
        td = _make_time_data(x.reshape(-1, 1), fs)

        fd = analysis.calculate_fft(td)

        assert fd.freq_axis.shape == (N // 2 + 1,)
        assert fd.freq_data.shape == (N // 2 + 1, 1)
        assert fd.freq_axis[1] == pytest.approx(fs / N)

        bin_idx = np.argmin(np.abs(fd.freq_axis - f0))
        peak = np.abs(fd.freq_data[bin_idx, 0])
        assert peak == pytest.approx(N / 2, rel=1e-6)

        mask = np.ones_like(fd.freq_axis, dtype=bool)
        mask[bin_idx] = False
        assert np.max(np.abs(fd.freq_data[mask, 0])) < 1e-6

    def test_matches_numpy_rfft_boxcar(self):
        """No window → output equals np.fft.rfft of the raw data."""
        fs = 1000
        x = _two_channel_sines(fs, 1024, 50, 130)
        td = _make_time_data(x, fs)

        fd = analysis.calculate_fft(td, window=None)

        expected = np.fft.rfft(x, axis=0)
        expected_faxis = np.fft.rfftfreq(x.shape[0], 1 / fs)

        np.testing.assert_allclose(fd.freq_data, expected, rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(fd.freq_axis, expected_faxis, rtol=1e-12, atol=1e-12)

    def test_matches_numpy_rfft_hann(self):
        """Hann window → output equals np.fft.rfft of (Hann × data)."""
        fs = 1000
        N = 1024
        x = _two_channel_sines(fs, N, 50, 130)
        td = _make_time_data(x, fs)

        fd = analysis.calculate_fft(td, window='hann')

        w = signal.windows.get_window('hann', N)
        expected = np.fft.rfft(w[:, None] * x, axis=0)
        np.testing.assert_allclose(fd.freq_data, expected, rtol=1e-12, atol=1e-12)

    def test_dc_offset(self):
        """Constant signal → DC bin only."""
        fs = 1000
        N = 512
        dc = 3.7
        x = np.full((N, 1), dc)
        td = _make_time_data(x, fs)

        fd = analysis.calculate_fft(td)

        assert fd.freq_data[0, 0] == pytest.approx(N * dc, rel=1e-12)
        assert np.max(np.abs(fd.freq_data[1:, 0])) < 1e-9

    def test_time_range_subsets_data(self):
        """time_range argument restricts the FFT to that window of samples."""
        fs = 1000
        N = 1000
        t = np.arange(N) / fs
        # Two distinct sine bursts: f1 active in first half, f2 in second half.
        f1, f2 = 50, 200
        x = np.zeros(N)
        x[:N // 2] = np.sin(2 * np.pi * f1 * t[:N // 2])
        x[N // 2:] = np.sin(2 * np.pi * f2 * t[N // 2:])
        td = _make_time_data(x.reshape(-1, 1), fs)

        fd_first = analysis.calculate_fft(td, time_range=np.array([0.0, 0.499]))
        fd_second = analysis.calculate_fft(td, time_range=np.array([0.5, 0.999]))

        f1_bin_first = np.argmin(np.abs(fd_first.freq_axis - f1))
        f2_bin_first = np.argmin(np.abs(fd_first.freq_axis - f2))
        f1_bin_second = np.argmin(np.abs(fd_second.freq_axis - f1))
        f2_bin_second = np.argmin(np.abs(fd_second.freq_axis - f2))

        assert np.abs(fd_first.freq_data[f1_bin_first, 0]) > \
               np.abs(fd_first.freq_data[f2_bin_first, 0])
        assert np.abs(fd_second.freq_data[f2_bin_second, 0]) > \
               np.abs(fd_second.freq_data[f1_bin_second, 0])

    def test_rejects_non_timedata(self):
        with pytest.raises(Exception, match='TimeData'):
            analysis.calculate_fft(np.zeros((10, 1)))


# ---------- calculate_cross_spectrum_matrix ----------

class TestCrossSpectrumMatrix:
    """Pins the current `csd`/`coherence`-loop implementation."""

    def _reference_csm(self, time_data_array, fs, window, N_frames, overlap):
        """Compute (f, Pxy, Cxy) the same way the current implementation does,
        but via direct scipy calls — gives an independent reference value."""
        N_samples, N_chans = time_data_array.shape
        nperseg = int(np.ceil(N_samples / (N_frames + 1) / (1 - overlap)))
        noverlap = int(np.ceil(overlap * nperseg))
        freqlength = len(np.fft.rfftfreq(nperseg))
        Pxy = np.zeros((N_chans, N_chans, freqlength), dtype=complex)
        Cxy = np.zeros((N_chans, N_chans, freqlength))
        f_ref = None
        for nx in range(N_chans):
            for ny in range(N_chans):
                if nx > ny:
                    Pxy[nx, ny, :] = np.conjugate(Pxy[ny, nx, :])
                    Cxy[nx, ny, :] = Cxy[ny, nx, :]
                else:
                    f, P = signal.csd(time_data_array[:, nx],
                                      time_data_array[:, ny],
                                      fs, window=window, nperseg=nperseg,
                                      noverlap=noverlap, scaling='spectrum')
                    _, C = signal.coherence(time_data_array[:, nx],
                                            time_data_array[:, ny],
                                            fs, window=window, nperseg=nperseg,
                                            noverlap=noverlap)
                    Pxy[nx, ny, :] = P
                    Cxy[nx, ny, :] = C
                    f_ref = f
        return f_ref, Pxy, Cxy

    def test_shapes_three_channels(self):
        fs = 1000
        N = 2000
        rng = np.random.default_rng(42)
        data = rng.standard_normal((N, 3))
        td = _make_time_data(data, fs)

        csd = analysis.calculate_cross_spectrum_matrix(td, N_frames=4)

        nperseg = int(np.ceil(N / (4 + 1) / 0.5))
        freqlength = len(np.fft.rfftfreq(nperseg))
        assert csd.Pxy.shape == (3, 3, freqlength)
        assert csd.Cxy.shape == (3, 3, freqlength)
        assert csd.freq_axis.shape == (freqlength,)

    def test_matches_scipy_reference_boxcar(self):
        """Golden regression: exact byte-for-byte match against scipy csd/coherence."""
        fs = 2000
        N = 4096
        rng = np.random.default_rng(7)
        data = rng.standard_normal((N, 3))
        td = _make_time_data(data, fs)

        csd = analysis.calculate_cross_spectrum_matrix(
            td, window=None, N_frames=4, overlap=0.5,
        )

        f_ref, Pxy_ref, Cxy_ref = self._reference_csm(
            data, fs, window='boxcar', N_frames=4, overlap=0.5,
        )
        np.testing.assert_allclose(csd.freq_axis, f_ref, rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(csd.Pxy, Pxy_ref, rtol=1e-12, atol=1e-12)

        # Coherence at the DC bin is undefined under a boxcar window: constant
        # detrending removes each segment's mean, so the DC FFT bin is pure
        # floating-point round-off (~1e-34 in power) and |Pxy|^2 / (Pxx*Pyy)
        # is 0/0. scipy.signal.coherence's separate welch/csd reduction lands
        # on different round-off there than this vectorised single-FFT path, so
        # neither value is meaningful and they cannot agree byte-for-byte.
        # Compare only the bins where the reference auto-spectra carry real
        # energy. (This also masks the even-nperseg Nyquist bin, degenerate the
        # same way; the nperseg here is odd, so there is no Nyquist bin.)
        Pxx_ref = np.real(np.einsum('iif->if', Pxy_ref))         # (N_chans, N_freq)
        well_defined = np.min(Pxx_ref, axis=0) > 1e-12 * np.max(Pxx_ref)
        np.testing.assert_allclose(csd.Cxy[:, :, well_defined],
                                   Cxy_ref[:, :, well_defined],
                                   rtol=1e-12, atol=1e-12)

    def test_matches_scipy_reference_hann(self):
        fs = 2000
        N = 4096
        rng = np.random.default_rng(11)
        data = rng.standard_normal((N, 4))
        td = _make_time_data(data, fs)

        csd = analysis.calculate_cross_spectrum_matrix(
            td, window='hann', N_frames=6, overlap=0.5,
        )

        f_ref, Pxy_ref, Cxy_ref = self._reference_csm(
            data, fs, window='hann', N_frames=6, overlap=0.5,
        )
        np.testing.assert_allclose(csd.Pxy, Pxy_ref, rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(csd.Cxy, Cxy_ref, rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(csd.freq_axis, f_ref, rtol=1e-12, atol=1e-12)

    def test_diagonal_is_psd(self):
        """Pxy[i,i] must equal scipy.signal.welch with scaling='spectrum'."""
        fs = 1000
        N = 2048
        rng = np.random.default_rng(5)
        data = rng.standard_normal((N, 2))
        td = _make_time_data(data, fs)

        N_frames = 4
        overlap = 0.5
        nperseg = int(np.ceil(N / (N_frames + 1) / (1 - overlap)))
        noverlap = int(np.ceil(overlap * nperseg))

        csd = analysis.calculate_cross_spectrum_matrix(
            td, window='hann', N_frames=N_frames, overlap=overlap,
        )

        for ch in range(2):
            f, Pxx = signal.welch(
                data[:, ch], fs, window='hann',
                nperseg=nperseg, noverlap=noverlap, scaling='spectrum',
            )
            np.testing.assert_allclose(csd.Pxy[ch, ch, :], Pxx,
                                       rtol=1e-12, atol=1e-12)

    def test_hermitian(self):
        """Pxy[i,j] = conj(Pxy[j,i]) for all i,j."""
        fs = 1000
        N = 1024
        rng = np.random.default_rng(3)
        data = rng.standard_normal((N, 3))
        td = _make_time_data(data, fs)

        csd = analysis.calculate_cross_spectrum_matrix(td, N_frames=2)

        for i in range(3):
            for j in range(3):
                np.testing.assert_allclose(
                    csd.Pxy[i, j, :], np.conjugate(csd.Pxy[j, i, :]),
                    rtol=1e-12, atol=1e-12,
                )

    def test_coherence_symmetric(self):
        fs = 1000
        N = 1024
        rng = np.random.default_rng(13)
        data = rng.standard_normal((N, 3))
        td = _make_time_data(data, fs)

        csd = analysis.calculate_cross_spectrum_matrix(td, N_frames=3)

        for i in range(3):
            for j in range(3):
                np.testing.assert_allclose(
                    csd.Cxy[i, j, :], csd.Cxy[j, i, :],
                    rtol=1e-12, atol=1e-12,
                )

    def test_coherence_diagonal_is_one(self):
        """Cxy[i,i] = 1 everywhere (auto-coherence)."""
        fs = 1000
        N = 1024
        rng = np.random.default_rng(2)
        data = rng.standard_normal((N, 2))
        td = _make_time_data(data, fs)

        csd = analysis.calculate_cross_spectrum_matrix(td, N_frames=4)

        for ch in range(2):
            np.testing.assert_allclose(csd.Cxy[ch, ch, :], 1.0,
                                       rtol=1e-10, atol=1e-10)

    def test_window_default_is_boxcar(self):
        """window=None ≡ window='boxcar'."""
        fs = 1000
        N = 1024
        rng = np.random.default_rng(99)
        data = rng.standard_normal((N, 2))
        td = _make_time_data(data, fs)

        csd_none = analysis.calculate_cross_spectrum_matrix(td, window=None, N_frames=2)
        csd_box = analysis.calculate_cross_spectrum_matrix(td, window='boxcar', N_frames=2)
        np.testing.assert_allclose(csd_none.Pxy, csd_box.Pxy, rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(csd_none.Cxy, csd_box.Cxy, rtol=1e-12, atol=1e-12)

    def test_freq_axis(self):
        """freq_axis = rfftfreq(nperseg, 1/fs)."""
        fs = 1000
        N = 2000
        rng = np.random.default_rng(8)
        data = rng.standard_normal((N, 2))
        td = _make_time_data(data, fs)
        N_frames = 4
        overlap = 0.5

        csd = analysis.calculate_cross_spectrum_matrix(
            td, N_frames=N_frames, overlap=overlap,
        )

        nperseg = int(np.ceil(N / (N_frames + 1) / (1 - overlap)))
        expected = np.fft.rfftfreq(nperseg, 1 / fs)
        np.testing.assert_allclose(csd.freq_axis, expected, rtol=1e-12, atol=1e-12)

    def test_large_nperseg_high_rate_record(self):
        """Large nFFT on a long, high-rate record must compute (and match scipy).

        Regression for the web-UI PSD crash: a 2 s, 44.1 kHz single-channel
        capture at N_frames=23 gives nperseg≈7350. The old
        ``sliding_window_view`` + slice built an intermediate view of nominal
        size N_chans*(N_samples-nperseg+1)*nperseg ≈ 5.9e8 elements (~4.7 GB
        for float64) — accepted here on 64-bit but rejected on the 32-bit
        pyodide engine as "array is too big". The ``as_strided`` build keeps
        the nominal size at N_seg*nperseg. This pins BOTH that it runs and
        that the diagonal still equals ``scipy.signal.welch`` exactly.
        """
        fs = 44100
        N = 88200                       # 2 s
        N_frames = 23
        overlap = 0.5
        rng = np.random.default_rng(4)
        data = rng.standard_normal((N, 1))
        td = _make_time_data(data, fs)

        csd = analysis.calculate_cross_spectrum_matrix(
            td, window='hann', N_frames=N_frames, overlap=overlap,
        )

        nperseg = int(np.ceil(N / (N_frames + 1) / (1 - overlap)))
        noverlap = int(np.ceil(overlap * nperseg))
        assert nperseg == 7350
        freqlength = len(np.fft.rfftfreq(nperseg))
        assert csd.Pxy.shape == (1, 1, freqlength)

        f, Pxx = signal.welch(
            data[:, 0], fs, window='hann',
            nperseg=nperseg, noverlap=noverlap, scaling='spectrum',
        )
        np.testing.assert_allclose(csd.freq_axis, f, rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(csd.Pxy[0, 0, :], Pxx, rtol=1e-12, atol=1e-12)

    def test_nperseg_longer_than_record_raises(self):
        """N_frames=0 (nperseg > N_samples) raises, never reads out of bounds.

        The old ``sliding_window_view`` raised its own ValueError for a
        window longer than the input; ``as_strided`` does no bounds
        checking, so ``calculate_cross_spectrum_matrix`` now guards
        explicitly. Pins the guard (and its actionable message) so the
        degenerate case can never silently return garbage.
        """
        rng = np.random.default_rng(5)
        td = _make_time_data(rng.standard_normal((256, 1)), 1000)
        with pytest.raises(ValueError, match='N_frames'):
            analysis.calculate_cross_spectrum_matrix(td, N_frames=0)


# ---------- calculate_tf ----------

class TestCalculateTf:

    def test_shapes_excludes_ch_in(self):
        fs = 1000
        N = 1024
        rng = np.random.default_rng(1)
        data = rng.standard_normal((N, 3))
        td = _make_time_data(data, fs)

        tf = analysis.calculate_tf(td, ch_in=0, N_frames=2)

        nperseg = int(np.ceil(N / (2 + 1) / 0.5))
        freqlength = len(np.fft.rfftfreq(nperseg))
        # (N_chan - 1) output channels (ch_in excluded)
        assert tf.tf_data.shape == (freqlength, 2)
        assert tf.tf_coherence.shape == (freqlength, 2)

    def test_matches_csd_ratio(self):
        """tf_data[:, k] = Pxy[ch_in, ch_out_k] / Pxy[ch_in, ch_in]."""
        fs = 1000
        N = 1024
        rng = np.random.default_rng(4)
        data = rng.standard_normal((N, 3))
        td = _make_time_data(data, fs)

        ch_in = 1
        N_frames = 3
        overlap = 0.5

        csd = analysis.calculate_cross_spectrum_matrix(
            td, N_frames=N_frames, overlap=overlap,
        )
        tf = analysis.calculate_tf(
            td, ch_in=ch_in, N_frames=N_frames, overlap=overlap,
        )

        ch_out_set = np.setxor1d(np.arange(3), ch_in)
        expected = np.zeros((len(csd.freq_axis), len(ch_out_set)), dtype=complex)
        for k, ch_out in enumerate(ch_out_set):
            expected[:, k] = csd.Pxy[ch_in, ch_out, :] / csd.Pxy[ch_in, ch_in, :]

        np.testing.assert_allclose(tf.tf_data, expected, rtol=1e-12, atol=1e-12)

    def test_recovers_linear_system_magnitude(self):
        """For y = h * x with no noise, |TF| ≈ |H(f)| of the FIR."""
        fs = 1000
        N = 8192
        # Simple 3-tap lowpass FIR
        fir = np.array([0.25, 0.5, 0.25])
        data = _linear_system_signals(fs, N, fir, seed=0)
        td = _make_time_data(data, fs)

        tf = analysis.calculate_tf(td, ch_in=0, N_frames=8, overlap=0.5,
                                   window='hann')

        # True magnitude of the FIR at the analysis frequencies
        H_true = np.fft.fft(fir, n=2 * (len(tf.freq_axis) - 1))[:len(tf.freq_axis)]
        # tf is conj(H) by the X·conj(Y) convention, so compare magnitudes
        # (phase test could be added but conjugate convention is subtle).
        # Restrict to mid-band to avoid edge effects.
        mid = slice(len(tf.freq_axis) // 8, len(tf.freq_axis) // 2)
        np.testing.assert_allclose(
            np.abs(tf.tf_data[mid, 0]),
            np.abs(H_true[mid]),
            rtol=0.05, atol=0.05,
        )

    def test_single_frame_coherence_is_one(self):
        """With N_frames=1, coherence is identically 1 (Welch's estimator)."""
        fs = 1000
        N = 1024
        rng = np.random.default_rng(6)
        data = rng.standard_normal((N, 2))
        td = _make_time_data(data, fs)

        tf = analysis.calculate_tf(td, ch_in=0, N_frames=1)

        np.testing.assert_allclose(tf.tf_coherence, 1.0, rtol=1e-10, atol=1e-10)

    def test_rejects_non_timedata(self):
        with pytest.raises(Exception, match='TimeData'):
            analysis.calculate_tf(np.zeros((10, 2)))


# ---------- channel_cal_factors / units propagation ----------

def _make_time_data_with_cal(time_data_array, fs, cal_factors, units=None):
    """TimeData with non-default cal factors and units."""
    settings = options.MySettings(fs=fs, channels=time_data_array.shape[1])
    time_axis = np.arange(time_data_array.shape[0]) / fs
    return datastructure.TimeData(
        time_axis, time_data_array, settings,
        channel_cal_factors=np.asarray(cal_factors, dtype=float),
        units=units, test_name='cal',
    )


class TestCalibrationPropagation:
    """Pin the propagation of `channel_cal_factors` and `units` through
    every `analysis.calculate_*` function. Before this work, all of them
    silently dropped the source TimeData's cal factors and units."""

    def test_fft_propagates_cal_and_units(self):
        fs, N = 1000, 256
        rng = np.random.default_rng(0)
        data = rng.standard_normal((N, 3))
        td = _make_time_data_with_cal(
            data, fs, cal_factors=[2.5, 0.1, 7.0], units=['N', 'm/s', 'V'],
        )
        fd = analysis.calculate_fft(td)
        np.testing.assert_array_equal(fd.channel_cal_factors, [2.5, 0.1, 7.0])
        assert fd.units == ['N', 'm/s', 'V']

    def test_fft_default_cal_unchanged(self):
        """Regression: a TimeData with all-ones cal still produces a
        FreqData with all-ones cal (no behavior change vs old code)."""
        fs, N = 1000, 256
        rng = np.random.default_rng(0)
        td = _make_time_data(rng.standard_normal((N, 2)), fs)
        fd = analysis.calculate_fft(td)
        np.testing.assert_array_equal(fd.channel_cal_factors, [1.0, 1.0])

    def test_cross_spectrum_propagates_cal_and_units(self):
        fs, N = 1000, 1024
        rng = np.random.default_rng(1)
        data = rng.standard_normal((N, 3))
        td = _make_time_data_with_cal(
            data, fs, cal_factors=[1.5, 0.5, 4.0], units=['N', 'm/s', 'V'],
        )
        csd = analysis.calculate_cross_spectrum_matrix(td, N_frames=2)
        np.testing.assert_array_equal(csd.channel_cal_factors, [1.5, 0.5, 4.0])
        assert csd.units == ['N', 'm/s', 'V']

    def test_cross_spectra_averaged_propagates_cal(self):
        fs, N = 1000, 1024
        rng = np.random.default_rng(2)
        tdl = datastructure.TimeDataList()
        for k in range(3):
            tdl.append(_make_time_data_with_cal(
                rng.standard_normal((N, 2)), fs,
                cal_factors=[3.0, 0.25], units=['N', 'm/s'],
            ))
        avg = analysis.calculate_cross_spectra_averaged(tdl)
        np.testing.assert_array_equal(avg.channel_cal_factors, [3.0, 0.25])
        assert avg.units == ['N', 'm/s']

    def test_tf_cal_factors_are_out_over_in_ratio(self):
        """The headline behaviour: TF inherits the calibration *ratio*
        cal[ch_out] / cal[ch_in] per output channel."""
        fs, N = 1000, 1024
        rng = np.random.default_rng(3)
        data = rng.standard_normal((N, 4))
        cal = [2.0, 10.0, 0.5, 8.0]
        td = _make_time_data_with_cal(
            data, fs, cal_factors=cal, units=['N', 'm/s', 'g', 'V'],
        )
        # ch_in = 1 → ch_out_set = [0, 2, 3]
        tf = analysis.calculate_tf(td, ch_in=1, N_frames=2)
        expected = np.array([cal[0] / cal[1], cal[2] / cal[1], cal[3] / cal[1]])
        np.testing.assert_allclose(tf.channel_cal_factors, expected, rtol=1e-12)
        assert tf.units == ['N/m/s', 'g/m/s', 'V/m/s']

    def test_tf_with_unit_cal_stays_unit(self):
        """Regression: when source cal is all ones, TF ratio is also all ones."""
        fs, N = 1000, 1024
        rng = np.random.default_rng(4)
        td = _make_time_data(rng.standard_normal((N, 3)), fs)
        tf = analysis.calculate_tf(td, ch_in=0, N_frames=2)
        np.testing.assert_array_equal(tf.channel_cal_factors, [1.0, 1.0])

    def test_tf_averaged_uses_first_ensemble_cal(self):
        fs, N = 1000, 1024
        rng = np.random.default_rng(5)
        tdl = datastructure.TimeDataList()
        for k in range(3):
            tdl.append(_make_time_data_with_cal(
                rng.standard_normal((N, 3)), fs,
                cal_factors=[1.0, 4.0, 2.0], units=['N', 'm/s', 'g'],
            ))
        tf = analysis.calculate_tf_averaged(tdl, ch_in=0)
        np.testing.assert_allclose(tf.channel_cal_factors, [4.0, 2.0], rtol=1e-12)
        assert tf.units == ['m/s/N', 'g/N']

    def test_calibrated_tf_is_raw_tf_times_ratio(self):
        """End-to-end: applying the stored cal ratio to a raw TF gives
        the same result as running the analysis on already-calibrated
        time data. This is the convention plotting.py / modal.py rely on."""
        fs, N = 1000, 2048
        fir = np.array([0.25, 0.5, 0.25])
        data = _linear_system_signals(fs, N, fir, seed=0)
        cal_in, cal_out = 0.5, 7.0

        td_raw = _make_time_data_with_cal(data, fs, cal_factors=[cal_in, cal_out])
        # Same data but with cal already baked in to the time samples
        td_baked = _make_time_data_with_cal(
            data * np.array([cal_in, cal_out]), fs, cal_factors=[1.0, 1.0],
        )

        tf_raw = analysis.calculate_tf(td_raw, ch_in=0, N_frames=4, window='hann')
        tf_baked = analysis.calculate_tf(td_baked, ch_in=0, N_frames=4, window='hann')

        calibrated_raw = tf_raw.tf_data[:, 0] * tf_raw.channel_cal_factors[0]
        # tf_baked.tf_data is already in calibrated values, with cal_factor 1
        np.testing.assert_allclose(calibrated_raw, tf_baked.tf_data[:, 0],
                                   rtol=1e-12, atol=1e-12)

    def test_sonogram_propagates_cal_and_units(self):
        fs, N = 1000, 4096
        rng = np.random.default_rng(7)
        data = rng.standard_normal((N, 2))
        td = _make_time_data_with_cal(
            data, fs, cal_factors=[3.0, 0.25], units=['N', 'm/s'],
        )
        sn = analysis.calculate_sonogram(td, nperseg=256)
        np.testing.assert_array_equal(sn.channel_cal_factors, [3.0, 0.25])
        assert sn.units == ['N', 'm/s']

    def test_units_none_does_not_crash_tf(self):
        """If source TimeData has units=None (the common case from
        un-annotated acquisitions), the TF should still build, with
        units=None."""
        fs, N = 1000, 1024
        rng = np.random.default_rng(8)
        td = _make_time_data_with_cal(
            rng.standard_normal((N, 3)), fs,
            cal_factors=[1.0, 2.0, 3.0], units=None,
        )
        tf = analysis.calculate_tf(td, ch_in=0, N_frames=2)
        assert tf.units is None
        np.testing.assert_allclose(tf.channel_cal_factors, [2.0, 3.0])


# ---------- calculate_tf_averaged (ensemble H1 estimator) ----------

class TestCalculateTfAveraged:
    """Pin the ensemble-averaged TF to the H1 convention used by
    `calculate_tf`: TF = Pxy[ch_in, ch_out] / Pxy[ch_in, ch_in] with
    Pxy[i, j] = conj(X_i)·X_j, i.e. standard e^{+jωt} phase (a pure
    delay has negative phase slope). Regression tests for the June
    2026 conjugate-TF bug."""

    def test_single_element_ensemble_matches_calculate_tf(self):
        """Averaging over a one-element ensemble must reproduce the
        single-capture H1 exactly — including phase."""
        fs, N = 1000, 4096
        rng = np.random.default_rng(11)
        x = rng.standard_normal(N)
        y = np.convolve(x, [0.4, 0.3, -0.2], mode='full')[:N]
        td = _make_time_data(np.column_stack([x, y]), fs)
        tdl = datastructure.TimeDataList([td])

        tf_single = analysis.calculate_tf(td, ch_in=0, N_frames=1)
        tf_avg = analysis.calculate_tf_averaged(tdl, ch_in=0)

        np.testing.assert_allclose(tf_avg.tf_data, tf_single.tf_data,
                                   rtol=1e-12, atol=1e-14)

    def test_recovers_delay_phase_across_ensemble(self):
        """y = x delayed by D samples → TF phase must be -2πfD/fs
        (e^{+jωt} convention), averaged over a 3-capture ensemble."""
        fs, N, D = 1000, 4096, 5
        rng = np.random.default_rng(12)
        tdl = datastructure.TimeDataList()
        for _ in range(3):
            x = rng.standard_normal(N)
            y = np.roll(x, D)
            tdl.append(_make_time_data(np.column_stack([x, y]), fs))

        tf = analysis.calculate_tf_averaged(tdl, ch_in=0)
        # check away from DC/Nyquist where the estimate is clean
        k = np.arange(20, 200)
        expected = np.exp(-1j * 2 * np.pi * tf.freq_axis[k] * D / fs)
        np.testing.assert_allclose(tf.tf_data[k, 0], expected,
                                   rtol=1e-6, atol=1e-8)


# ---------- calculate_sonogram provenance ----------

class TestSonogramIdLink:

    def test_sonogram_id_link_is_source_unique_id(self):
        """Every derived data object stores the source TimeData's
        unique_id in id_link; the sonogram must do the same."""
        fs, N = 1000, 4096
        rng = np.random.default_rng(13)
        td = _make_time_data(rng.standard_normal((N, 2)), fs)
        sn = analysis.calculate_sonogram(td, nperseg=256)
        assert sn.id_link == td.unique_id


# ---------- calculate_sonogram byte-identical low-memory segmentation ----------

class TestSonogramLowMem:
    """Pin `_spectrogram_complex_lowmem` (and `calculate_sonogram`) BYTE-FOR-BYTE
    against `scipy.signal.spectrogram(mode='complex')`.

    The low-memory helper strides directly to the decimated STFT windows
    instead of building scipy's ``sliding_window_view`` intermediate, whose
    NOMINAL size overflows the 32-bit WASM engine's ``2**31-1`` byte ceiling
    for a large nperseg on a long, high-rate record (the round-5 "Sonogram:
    array is too big" bug). It must match scipy exactly — same Hann window,
    constant detrend, density scaling with the stft-mode sqrt, one-sided rfft
    with no psd doubling, and boundary=None/padded=False defaults.
    """

    # (N_samples, N_chans, nperseg, noverlap): default, webui default, odd
    # length/overlap, noverlap=0 (the damping path), and nperseg==N.
    CASES = [
        (9000, 2, 180, 90),
        (9000, 2, 512, 256),
        (4096, 3, 256, 128),
        (4096, 1, 256, 0),
        (2000, 4, 137, 61),
        (1000, 2, 64, 48),
        (500, 1, 500, 0),
        (3001, 2, 300, 150),
    ]

    @pytest.mark.parametrize('N,nch,nperseg,noverlap', CASES)
    def test_helper_byte_identical_to_scipy(self, N, nch, nperseg, noverlap):
        rng = np.random.default_rng(hash((N, nch, nperseg)) & 0xFFFF)
        y = rng.standard_normal((N, nch))
        fs = 4321.0
        f_ref, t_ref, S_ref = signal.spectrogram(
            y, fs=fs, window='hann', nperseg=nperseg, noverlap=noverlap,
            axis=0, mode='complex')
        f2, t2, S2 = analysis._spectrogram_complex_lowmem(y, fs, nperseg, noverlap)
        # Byte-for-byte: identical shape AND identical values (not just close).
        assert S2.shape == S_ref.shape
        np.testing.assert_array_equal(S2, S_ref)
        np.testing.assert_array_equal(f2, f_ref)
        np.testing.assert_array_equal(t2, t_ref)

    def test_calculate_sonogram_matches_scipy_swapaxes(self):
        """The public `calculate_sonogram` must equal scipy's spectrogram
        after the (freq, chan, seg) -> (freq, seg, chan) swapaxes it applies."""
        fs, N = 2000, 8192
        rng = np.random.default_rng(21)
        td = _make_time_data(rng.standard_normal((N, 2)), fs)
        sn = analysis.calculate_sonogram(td, nperseg=512, noverlap=256)
        _, _, S_ref = signal.spectrogram(
            td.time_data, fs=fs, window='hann', nperseg=512, noverlap=256,
            axis=0, mode='complex')
        np.testing.assert_array_equal(sn.sono_data, np.swapaxes(S_ref, 1, 2))

    def test_large_nperseg_does_not_build_giant_intermediate(self):
        """A long record + large nperseg whose scipy ``sliding_window_view``
        NOMINAL size exceeds the 32-bit WASM ceiling still computes here (on
        64-bit the ceiling is huge, so this only demonstrates equivalence at
        a shape that WOULD overflow WASM), and stays byte-identical.

        The nominal ``sliding_window_view`` size is
        ``(N - nperseg + 1) * nperseg * 8`` bytes; the case below is chosen so
        that value comfortably exceeds ``2**31-1``."""
        N, nperseg, noverlap = 88200, 4096, 2048   # ~2 s @ 44.1 kHz, max UI nFFT
        swv_nominal = (N - nperseg + 1) * nperseg * 8
        assert swv_nominal > 2**31 - 1             # would overflow 32-bit WASM
        rng = np.random.default_rng(99)
        y = rng.standard_normal((N, 1))
        fs = 44100.0
        f_ref, t_ref, S_ref = signal.spectrogram(
            y, fs=fs, window='hann', nperseg=nperseg, noverlap=noverlap,
            axis=0, mode='complex')
        f2, t2, S2 = analysis._spectrogram_complex_lowmem(y, fs, nperseg, noverlap)
        np.testing.assert_array_equal(S2, S_ref)
        np.testing.assert_array_equal(f2, f_ref)
        np.testing.assert_array_equal(t2, t_ref)

    def test_nperseg_longer_than_record_clamps_like_scipy(self):
        """scipy clamps nperseg to the record length (with a warning) rather
        than erroring; the helper must do the same and stay byte-identical."""
        fs, N = 1000, 300
        rng = np.random.default_rng(5)
        y = rng.standard_normal((N, 2))
        with pytest.warns(UserWarning):
            f_ref, t_ref, S_ref = signal.spectrogram(
                y, fs=fs, window='hann', nperseg=400, noverlap=0,
                axis=0, mode='complex')
        with pytest.warns(UserWarning):
            f2, t2, S2 = analysis._spectrogram_complex_lowmem(y, fs, 400, 0)
        np.testing.assert_array_equal(S2, S_ref)


# ---------- calculate_cwt (complex Morlet CWT sonogram) ----------

def _decaying_sine(fs, n_samples, fn, Q, amp=1.0, phase=0.0):
    """A single decaying sinusoid with known fn (Hz) and Q = 1/(2*zeta)."""
    t = np.arange(n_samples) / fs
    zeta = 1.0 / (2.0 * Q)
    w0 = 2.0 * np.pi * fn
    wd = w0 * np.sqrt(1.0 - zeta ** 2)
    return amp * np.exp(-zeta * w0 * t) * np.cos(wd * t + phase)


class TestCalculateCwt:
    """Pin the complex Morlet CWT: shape/SonoData parity, amplitude
    normalisation convention, pure-tone log-bin localisation, chirp ridge
    tracking, and the uniform-vs-native frequency-axis behaviour."""

    def test_returns_sonodata_shaped_like_sonogram(self):
        """calculate_cwt returns a SonoData with the same (n_freq, n_frames,
        n_channels) sono_data layout and matching axis lengths, so the whole
        SonoData pipeline reuses unchanged."""
        fs, N = 2000, 8000
        rng = np.random.default_rng(3)
        td = _make_time_data(rng.standard_normal((N, 3)), fs)
        sd = analysis.calculate_cwt(td, max_time_columns=500)
        assert sd.__class__.__name__ == 'SonoData'
        n_freq = sd.freq_axis.shape[0]
        n_frames = sd.time_axis.shape[0]
        assert sd.sono_data.shape == (n_freq, n_frames, 3)
        assert np.iscomplexobj(sd.sono_data)
        assert n_frames <= 500
        assert sd.id_link == td.unique_id

    def test_time_columns_capped(self):
        """The output time axis is decimated to <= max_time_columns."""
        fs, N = 4000, 40000
        td = _make_time_data(np.zeros((N, 1)) + 1.0, fs)
        sd = analysis.calculate_cwt(td, max_time_columns=1000)
        assert sd.time_axis.shape[0] <= 1000

    def test_uniform_freq_axis_is_uniform(self):
        """Default (uniform_freq=True) returns an evenly-spaced freq axis (the
        web-UI heat renderer assumes uniform bins); native mode is log-spaced."""
        fs, N = 2000, 8000
        td = _make_time_data(_decaying_sine(fs, N, 100.0, 40)[:, None], fs)
        sd_u = analysis.calculate_cwt(td, uniform_freq=True)
        d = np.diff(sd_u.freq_axis)
        assert np.allclose(d, d[0], rtol=1e-6)
        sd_l = analysis.calculate_cwt(td, uniform_freq=False)
        dl = np.diff(sd_l.freq_axis)
        # log-spaced: ratios (not differences) are constant
        ratios = sd_l.freq_axis[1:] / sd_l.freq_axis[:-1]
        assert np.allclose(ratios, ratios[0], rtol=1e-6)
        assert not np.allclose(dl, dl[0], rtol=1e-3)

    def test_voices_per_octave_sets_density(self):
        """The native log grid has ~voices_per_octave samples per octave."""
        fs, N = 2000, 8000
        td = _make_time_data(_decaying_sine(fs, N, 100.0, 40)[:, None], fs)
        for vpo in (8, 16, 24):
            f = analysis._cwt_default_frequencies(fs, N, None, vpo)
            octaves = np.log2(f[-1] / f[0])
            got = (len(f) - 1) / octaves
            assert abs(got - vpo) < 1.0

    def test_amplitude_normalisation_is_frequency_independent(self):
        """CONVENTION (pinned): a real cosine of amplitude A at the wavelet's
        centre frequency yields a coefficient of peak magnitude ~= A,
        independent of frequency (L-infinity / amplitude normalisation)."""
        fs, N = 2000, 16000
        freqs = np.geomspace(10, 800, 400)
        mid = slice(N // 4, 3 * N // 4)   # avoid cone-of-influence edges
        for amp, f0 in [(1.0, 50.0), (1.0, 100.0), (2.0, 200.0), (0.5, 400.0)]:
            t = np.arange(N) / fs
            x = amp * np.cos(2 * np.pi * f0 * t)
            W, _ = analysis._morlet_cwt_1d(x, fs, freqs, w0=6.0)
            peak = np.abs(W[:, mid]).max()
            assert abs(peak - amp) < 0.05 * amp + 0.02

    def test_pure_tone_localises_at_right_log_bin(self):
        """A pure tone puts its CWT energy at the frequency bin nearest the
        tone; the mean power spectrum peaks within one voice of the true f."""
        fs, N = 2000, 16000
        t = np.arange(N) / fs
        f0 = 137.0
        x = np.cos(2 * np.pi * f0 * t)
        freqs = analysis._cwt_default_frequencies(fs, N, None, 16)
        W, _ = analysis._morlet_cwt_1d(x, fs, freqs, w0=6.0)
        mid = slice(N // 4, 3 * N // 4)
        power = (np.abs(W[:, mid]) ** 2).mean(axis=1)
        f_peak = freqs[np.argmax(power)]
        # within one voice (2^(1/16)) of the true tone
        assert abs(np.log2(f_peak / f0)) < 1.0 / 16 + 1e-3

    def test_chirp_ridge_tracks_instantaneous_frequency(self):
        """For a linear chirp, the ridge (arg-max over frequency at each time)
        follows the instantaneous frequency f(t) = f0 + k t."""
        fs, N = 4000, 8000
        t = np.arange(N) / fs
        f0, f1 = 100.0, 500.0
        k = (f1 - f0) / t[-1]
        inst = f0 + k * t
        phase = 2 * np.pi * (f0 * t + 0.5 * k * t ** 2)
        x = np.cos(phase)
        freqs = np.geomspace(50, 800, 400)
        W, _ = analysis._morlet_cwt_1d(x, fs, freqs, w0=8.0)
        ridge = freqs[np.abs(W).argmax(axis=0)]
        mid = slice(N // 5, 4 * N // 5)   # ignore chirp edges (COI)
        rel_err = np.abs(ridge[mid] - inst[mid]) / inst[mid]
        assert np.median(rel_err) < 0.05


class TestCwtBandResolution:
    """The analysis band `_cwt_default_frequencies` resolves: its w0-aware low
    end, partial (one-sided) ranges, and the refusal to invent a band."""

    def test_low_end_keeps_the_lowest_wavelet_inside_the_record(self):
        """The lowest wavelet's e-folding time (sqrt(2)*w0/(2 pi f)) must stay
        below T/2 for EVERY analysis frequency, at every wavelet Q — otherwise
        the bottom rows are pure cone-of-influence / circular-wrap artefact.
        The old fixed 4/T low end was calibrated for w0=6 only: at w0=64 it put
        137 of 700 default rows past that bound."""
        fs, N = 2000, 8000
        T = N / fs
        for w0 in (6.0, 32.0, 64.0, 128.0):
            f = analysis._cwt_default_frequencies(fs, N, None, 16, w0=w0)
            e_fold = np.sqrt(2.0) * w0 / (2.0 * np.pi * f)
            assert e_fold.max() <= T / 2, f'w0={w0}: {int((e_fold > T / 2).sum())} rows past T/2'

    def test_w0_6_band_is_bit_for_bit_the_historic_one(self):
        """The w0-aware scaling must not move the DEFAULT band."""
        fs, N = 2000, 8000
        f = analysis._cwt_default_frequencies(fs, N, None, 16, w0=6.0)
        assert f[0] == pytest.approx(4.0 / (N / fs))
        assert f[-1] == pytest.approx(0.4 * fs)
        # ... and the parameter defaults to the historic behaviour when omitted.
        np.testing.assert_allclose(
            f, analysis._cwt_default_frequencies(fs, N, None, 16))

    def test_one_sided_f_range_keeps_the_other_side_automatic(self):
        """A LONE bound is meaningful (the web UI's freq-range boxes are
        independent): the missing side keeps its automatic value."""
        fs, N = 2000, 8000
        auto = analysis._cwt_default_frequencies(fs, N, None, 16)
        lo_only = analysis._cwt_default_frequencies(fs, N, (100.0, None), 16)
        hi_only = analysis._cwt_default_frequencies(fs, N, (None, 300.0), 16)
        assert lo_only[0] == pytest.approx(100.0)
        assert lo_only[-1] == pytest.approx(auto[-1])
        assert hi_only[0] == pytest.approx(auto[0])
        assert hi_only[-1] == pytest.approx(300.0)

    def test_reversed_or_degenerate_f_range_raises(self):
        """A reversed band used to be silently replaced by (f_min, 2*f_min) —
        a plausible-looking analysis of a band nobody asked for."""
        fs, N = 2000, 8000
        for bad in [(400.0, 100.0), (100.0, 100.0), (-5.0, 100.0), (0.0, 100.0)]:
            with pytest.raises(ValueError, match='increasing'):
                analysis._cwt_default_frequencies(fs, N, bad, 16)

    def test_band_entirely_above_nyquist_raises(self):
        fs, N = 2000, 8000
        with pytest.raises(ValueError, match='Nyquist'):
            analysis._cwt_default_frequencies(fs, N, (1500.0, 3000.0), 16)

    def test_reversed_f_range_raises_through_the_public_entry_points(self):
        fs, N = 2000, 4000
        td = _make_time_data(_decaying_sine(fs, N, 90.0, 40)[:, None], fs)
        with pytest.raises(ValueError, match='increasing'):
            analysis.calculate_damping_from_cwt(td, n_chan=0, f_range=(400.0, 100.0))
        with pytest.raises(ValueError, match='increasing'):
            analysis.calculate_cwt(td, f_range=(400.0, 100.0))


class TestCwtMemoryGuard:
    """The CWT damping fit at LAB record sizes (the "CWT sonogram not working"
    report): the transform is bounded, and an impossible request fails with a
    pydvma message naming the remedy — never numpy's bare "array is too big",
    which is what reached the user through the 32-bit WASM engine."""

    @staticmethod
    def _implied_bytes(fs, N, f_range, vpo, w0=6.0):
        """Bytes `calculate_damping_from_cwt` would allocate for this request."""
        freqs = analysis._cwt_default_frequencies(fs, N, f_range, vpo, w0=w0)
        step = analysis._cwt_damping_time_step(fs, freqs[-1])
        n_out = len(range(0, N, step))
        return len(freqs) * n_out * 16

    def test_guard_fires_before_allocating_anything(self):
        """The check is a pre-flight: a 1.6e11-byte image is refused without
        the transform ever running (a tiny signal, an enormous grid)."""
        fs, N = 2000, 100000
        freqs = np.geomspace(1.0, 800.0, 100000)
        with pytest.raises(ValueError) as exc:
            analysis._morlet_cwt_1d(np.zeros(N), fs, freqs)
        msg = str(exc.value)
        assert 'too big' not in msg.lower()          # not numpy's opaque phrase
        assert 'CWT image too large' in msg
        for remedy in ('SHORTER', 'NARROW', 'voices', 'time_step'):
            assert remedy in msg
        assert 'w0=6' in msg and '100000 samples' in msg

    @pytest.mark.parametrize('secs,vpo', [(30, 16), (5, 48)])
    def test_lab_size_default_band_is_bounded_or_named(self, secs, vpo):
        """30 s @ 48 kHz (default band) and 5 s @ 48 kHz at 48 voices: either
        the request fits the ceiling, or it raises the actionable pydvma error.
        Never numpy's "array is too big", and never a silent 16 GB attempt."""
        fs = 48000
        N = fs * secs
        implied = self._implied_bytes(fs, N, None, vpo)
        td = _make_time_data(np.zeros((N, 1)), fs)
        if implied <= analysis.CWT_MAX_IMAGE_BYTES:
            analysis.calculate_damping_from_cwt(td, n_chan=0, voices_per_octave=vpo)
            assert implied <= 2 ** 31 - 1
        else:
            with pytest.raises(ValueError) as exc:
                analysis.calculate_damping_from_cwt(td, n_chan=0, voices_per_octave=vpo)
            msg = str(exc.value)
            assert 'array is too big' not in msg
            assert 'NARROW the frequency range' in msg
            assert '{:g} Hz'.format(fs) in msg

    def test_narrowing_the_band_makes_a_lab_record_fittable(self):
        """The remedy the message names actually works: the SAME 5 s, 48 kHz
        record fits inside the ceiling once a band is given (fewer rows AND a
        decimated time axis), and still recovers the modes."""
        fs, secs = 48000, 5
        N = fs * secs
        # Equal decay times (Q ~ f) so both modes are still alive at the fit
        # start, 5% into the record.
        modes = [(37.0, 50.0), (210.0, 280.0)]
        x = sum(_decaying_sine(fs, N, f, q) for f, q in modes)[:, None]
        td = _make_time_data(x, fs)
        implied = self._implied_bytes(fs, N, (20.0, 500.0), 16)
        assert implied <= analysis.CWT_MAX_IMAGE_BYTES
        assert implied <= 2 ** 31 - 1
        # An order of magnitude smaller than the same band at full time
        # resolution (step 12 for a 500 Hz top at 48 kHz).
        n_rows = len(analysis._cwt_default_frequencies(fs, N, (20.0, 500.0), 16))
        assert implied * 10 <= n_rows * N * 16

        fn, Qn, fd = analysis.calculate_damping_from_cwt(
            td, n_chan=0, f_range=(20.0, 500.0))
        assert len(fn) >= 2
        assert np.all((fn > 20.0) & (fn < 500.0))       # nothing outside the band
        for f_true, q_true in modes:
            j = np.argmin(np.abs(fn - f_true))
            assert abs(fn[j] - f_true) / f_true < 0.05
            assert abs(Qn[j] - q_true) / q_true < 0.3
        assert fd['t'].size == len(range(0, N, analysis._cwt_damping_time_step(fs, 500.0)))

    def test_default_band_fit_is_still_undecimated(self):
        """The decimation must not change any case that already worked: a
        default-band fit tops out at 0.4*fs, whose phase unwrap tolerates no
        decimation at all, so time_step stays 1."""
        for fs in (2000, 8000, 48000):
            assert analysis._cwt_damping_time_step(fs, 0.4 * fs) == 1
        # 4x oversampling of the band top, floored.
        assert analysis._cwt_damping_time_step(48000, 500.0) == 12
        assert analysis._cwt_damping_time_step(48000, 50.0) == 120

    def test_decimated_fit_matches_the_full_rate_fit(self):
        """The decimation is a size bound, not a change of answer: over a band
        it is allowed to decimate, the fitted fn / zeta match the full-rate fit
        of the same image to well inside the fit's own accuracy."""
        fs, N = 8000, 16000                     # 2 s
        fn_true, Q = 60.0, 45.0
        x = (_decaying_sine(fs, N, fn_true, Q)
             + 0.5 * _decaying_sine(fs, N, 180.0, 70.0))
        td = _make_time_data(x[:, None], fs)
        freqs = analysis._cwt_default_frequencies(fs, N, (20.0, 300.0), 16)
        step = analysis._cwt_damping_time_step(fs, freqs[-1])
        assert step > 1

        out = {}
        for ts in (1, step):
            W, t_idx = analysis._morlet_cwt_1d(x, fs, freqs, w0=6.0, time_step=ts)
            t = np.asarray(td.time_axis)[t_idx]
            sl = analysis._resolve_damping_start_slice(
                t, None, td.settings, default_start_frac=0.05)
            out[ts] = analysis._fit_modes_from_image(
                t, freqs, W, sl, phase_has_carrier=True)

        fn_full, Q_full, _ = out[1]
        fn_dec, Q_dec, _ = out[step]
        assert len(fn_dec) == len(fn_full) >= 1
        np.testing.assert_allclose(fn_dec, fn_full, rtol=1e-3)
        zeta_full, zeta_dec = 1.0 / (2 * Q_full), 1.0 / (2 * Q_dec)
        np.testing.assert_allclose(zeta_dec, zeta_full, rtol=0.02)


class Test3c6Envelope:
    """The 3c6 teaching-lab operating envelope, pinned as a regression floor
    (round 11): fs = 3 kHz (typically decimated from a 48 kHz native
    capture), 30 s logs, 2 channels; damping fits come from ~6 s impulse
    records at the same rate. These must run over the DEFAULT band with no
    band-narrowing or other remedy — the CWT size bounds exist for the
    demanding research cases, and must never constrain routine lab use."""

    def test_damping_fit_6s_at_3k_runs_over_the_default_band(self):
        fs, secs = 3000, 6
        N = fs * secs
        # Q ~ f so both modes are still alive at the fit start.
        modes = [(45.0, 60.0), (320.0, 400.0)]
        x = sum(_decaying_sine(fs, N, f, q) for f, q in modes)[:, None]
        td = _make_time_data(x, fs)
        fn, Qn, _fd = analysis.calculate_damping_from_cwt(td, n_chan=0)
        assert len(fn) >= 2
        for f_true, q_true in modes:
            j = np.argmin(np.abs(fn - f_true))
            assert abs(fn[j] - f_true) / f_true < 0.05
            assert abs(Qn[j] - q_true) / q_true < 0.3

    @pytest.mark.parametrize('secs', [6, 30])
    def test_3k_default_band_stays_inside_the_ceiling(self, secs):
        """Even the 30 s log's default-band fit is comfortably under the
        allocation ceiling at 3 kHz — no remedy required, at any length the
        lab uses."""
        fs = 3000
        N = fs * secs
        freqs = analysis._cwt_default_frequencies(fs, N, None, 16)
        step = analysis._cwt_damping_time_step(fs, freqs[-1])
        n_out = len(range(0, N, step))
        assert len(freqs) * n_out * 16 <= analysis.CWT_MAX_IMAGE_BYTES


class TestCwtProgressCallback:
    """The optional `progress_callback` (round-11 P7): a lab-length CWT can run
    for tens of seconds in the browser engine, and the ONLY thing a busy
    worker can do is post frames out. The callback is what produces them —
    counted exactly, monotone, covering the whole call, and with NO effect on
    the numbers."""

    @staticmethod
    def _record(fs=2000, n=6000, n_chans=1):
        x = np.column_stack([
            _decaying_sine(fs, n, 90.0 + 30.0 * c, 40.0) for c in range(n_chans)
        ])
        return _make_time_data(x, fs)

    def test_morlet_reports_one_frame_per_scale(self):
        """`_morlet_cwt_1d` calls back once per scale, counting 1..len(freqs)
        with a constant total — the transform's only natural progress unit."""
        fs, N = 2000, 4000
        freqs = np.geomspace(20.0, 500.0, 37)
        calls = []
        analysis._morlet_cwt_1d(np.zeros(N), fs, freqs,
                                progress_callback=lambda d, t: calls.append((d, t)))
        assert calls == [(i + 1, 37) for i in range(37)]

    @pytest.mark.parametrize('n_chans', [1, 3])
    def test_calculate_cwt_counts_channels_times_scales(self, n_chans):
        """`calculate_cwt` re-bases the per-channel frames onto the WHOLE call:
        total = n_chans * n_freqs, done strictly increasing 1..total, ending
        exactly at total (a bar that reaches its end)."""
        fs, N = 2000, 6000
        td = self._record(fs, N, n_chans)
        calls = []
        sd = analysis.calculate_cwt(td, max_time_columns=200,
                                    progress_callback=lambda d, t: calls.append((d, t)))
        n_freqs = sd.freq_axis.shape[0]
        total = n_chans * n_freqs
        assert len(calls) == total
        assert {t for _, t in calls} == {total}                  # one constant total
        done = [d for d, _ in calls]
        assert done == sorted(done) and done == list(range(1, total + 1))

    def test_result_is_bit_identical_with_and_without_the_callback(self):
        """The callback is observation only: same image, same axes, to the
        bit — so no caller ever pays for progress in accuracy."""
        td = self._record(n_chans=2)
        quiet = analysis.calculate_cwt(td, max_time_columns=200)
        noisy = analysis.calculate_cwt(td, max_time_columns=200,
                                       progress_callback=lambda d, t: None)
        np.testing.assert_array_equal(quiet.sono_data, noisy.sono_data)
        np.testing.assert_array_equal(quiet.freq_axis, noisy.freq_axis)
        np.testing.assert_array_equal(quiet.time_axis, noisy.time_axis)

    def test_damping_fit_reports_its_transform(self):
        """The CWT damping fit — the slow path that started this — reports the
        transform: one frame per analysis frequency, ending at the total. The
        per-mode curve fits are deliberately uncounted (the mode count is
        unknown until the peaks are picked, so counting them would grow
        `total` mid-call), and the result is unchanged."""
        fs, N = 2000, 8000
        td = _make_time_data(_decaying_sine(fs, N, 90.0, 40.0)[:, None], fs)
        calls = []
        fn, Qn, _ = analysis.calculate_damping_from_cwt(
            td, n_chan=0, f_range=(30.0, 400.0),
            progress_callback=lambda d, t: calls.append((d, t)))
        n_freqs = len(analysis._cwt_default_frequencies(fs, N, (30.0, 400.0), 16))
        assert len(calls) == n_freqs
        assert calls[0] == (1, n_freqs) and calls[-1] == (n_freqs, n_freqs)

        fn_q, Qn_q, _ = analysis.calculate_damping_from_cwt(
            td, n_chan=0, f_range=(30.0, 400.0))
        np.testing.assert_array_equal(fn, fn_q)
        np.testing.assert_array_equal(Qn, Qn_q)

    def test_no_callback_means_no_calls(self):
        """Default None is a true no-op — nothing is invoked per scale, so the
        desktop/native path pays nothing for a browser-only feature."""
        sentinel = []

        class Boom:
            def __call__(self, *a):        # pragma: no cover - must never run
                sentinel.append(a)
                raise AssertionError('progress_callback called when none was given')

        td = self._record()
        analysis.calculate_cwt(td, max_time_columns=100)
        assert sentinel == []


class TestDampingBothMethods:
    """Damping recovery via BOTH the STFT and the CWT paths, and the
    demonstrated CWT advantage: it separates two close low-frequency modes
    that a single-window STFT smears into one."""

    def test_stft_recovers_single_mode(self):
        fs, N = 2000, 8000
        fn, Q = 90.0, 40.0
        x = _decaying_sine(fs, N, fn, Q)[:, None]
        td = _make_time_data(x, fs)
        rfn, rQ, _ = analysis.calculate_damping_from_sono(td, n_chan=0, nperseg=256)
        assert len(rfn) >= 1
        j = np.argmin(np.abs(rfn - fn))
        assert abs(rfn[j] - fn) / fn < 0.05
        assert abs(rQ[j] - Q) / Q < 0.25

    def test_cwt_recovers_single_mode(self):
        fs, N = 2000, 8000
        fn, Q = 90.0, 40.0
        x = _decaying_sine(fs, N, fn, Q)[:, None]
        td = _make_time_data(x, fs)
        rfn, rQ, _ = analysis.calculate_damping_from_cwt(td, n_chan=0)
        assert len(rfn) >= 1
        j = np.argmin(np.abs(rfn - fn))
        assert abs(rfn[j] - fn) / fn < 0.05
        assert abs(rQ[j] - Q) / Q < 0.25

    def test_cwt_separates_close_low_modes_that_stft_merges(self):
        """Two close low-frequency modes (18 & 30 Hz): a single-window STFT
        whose bin spacing is comparable to the separation cannot resolve both,
        while the constant-Q CWT recovers both frequencies within tolerance.
        This is the demonstrated added value of the wavelet method."""
        fs, N = 2000, 8000
        f1, f2, Q = 18.0, 30.0, 60.0
        rng = np.random.default_rng(7)
        x = (_decaying_sine(fs, N, f1, Q) + _decaying_sine(fs, N, f2, Q)
             + 1e-4 * rng.standard_normal(N))[:, None]
        td = _make_time_data(x, fs)

        # CWT: both modes recovered.
        cfn, cQ, _ = analysis.calculate_damping_from_cwt(td, n_chan=0)
        near1 = np.any(np.abs(cfn - f1) / f1 < 0.10)
        near2 = np.any(np.abs(cfn - f2) / f2 < 0.10)
        assert near1 and near2, f'CWT should resolve both modes, got {cfn}'

        # STFT with a coupled-resolution window (~N/50, the UI default) whose
        # low-frequency bin spacing merges the two modes: it recovers strictly
        # fewer well-matched modes than the CWT.
        sfn, sQ, _ = analysis.calculate_damping_from_sono(td, n_chan=0, nperseg=N // 50)
        s_hits = int(np.any(np.abs(sfn - f1) / f1 < 0.10)) + \
            int(np.any(np.abs(sfn - f2) / f2 < 0.10)) if len(sfn) else 0
        assert s_hits < 2, f'STFT should NOT resolve both modes, got {sfn}'


class TestDampingPeakThresholdAndFitContext:
    """Round-7 interactive damping UI surface: the promoted `peak_threshold`
    parameter and the peak-picking context returned in `fit_data` (start
    slice/time, threshold used, slice spectrum, candidate peaks)."""

    @staticmethod
    def _two_mode_td():
        fs, N = 2000, 8000
        x = (_decaying_sine(fs, N, 90.0, 40.0)
             + 0.4 * _decaying_sine(fs, N, 400.0, 60.0))[:, None]
        return _make_time_data(x, fs)

    def test_default_threshold_unchanged_and_echoed(self):
        """peak_threshold=None keeps the historic automatic choice, and
        fit_data echoes exactly the value used plus the resolved start."""
        td = self._two_mode_td()
        fn, Qn, fd = analysis.calculate_damping_from_sono(td, n_chan=0, nperseg=256)
        assert len(fn) >= 1
        for key in ('time_slice', 'start_time', 'threshold',
                    'slice_freq', 'slice_mag', 'peaks_freq', 'peaks_mag'):
            assert key in fd, f'fit_data missing {key}'
        assert fd['start_time'] == fd['t'][fd['time_slice']]
        assert fd['slice_freq'].shape == fd['slice_mag'].shape
        assert fd['peaks_freq'].shape == fd['peaks_mag'].shape
        # Candidate peaks include (at least) every successfully fitted mode.
        assert len(fd['peaks_freq']) >= len(fd['fits'])
        assert 0 <= fd['threshold']

    def test_explicit_threshold_gates_candidate_peaks(self):
        """A permissive threshold finds at least as many candidates as a
        strict one, and a maximal threshold finds none."""
        td = self._two_mode_td()
        _, _, lo = analysis.calculate_damping_from_sono(
            td, n_chan=0, nperseg=256, peak_threshold=0.05)
        _, _, hi = analysis.calculate_damping_from_sono(
            td, n_chan=0, nperseg=256, peak_threshold=0.9)
        assert lo['threshold'] == 0.05 and hi['threshold'] == 0.9
        assert len(lo['peaks_freq']) >= len(hi['peaks_freq'])
        fn_max, _, top = analysis.calculate_damping_from_sono(
            td, n_chan=0, nperseg=256, peak_threshold=1.0)
        assert len(fn_max) == 0 and len(top['fits']) == 0

    def test_threshold_is_clipped_to_unit_range(self):
        """Out-of-range explicit thresholds clip to 0..1 rather than being
        passed raw to peakutils."""
        td = self._two_mode_td()
        _, _, fd = analysis.calculate_damping_from_sono(
            td, n_chan=0, nperseg=256, peak_threshold=7.5)
        assert fd['threshold'] == 1.0

    def test_cwt_accepts_threshold_too(self):
        td = self._two_mode_td()
        fn, _, fd = analysis.calculate_damping_from_cwt(
            td, n_chan=0, peak_threshold=0.1)
        assert fd['threshold'] == 0.1
        assert len(fn) >= 1
        # The 90 Hz mode survives a permissive threshold on the CWT path.
        assert np.any(np.abs(fd['peaks_freq'] - 90.0) / 90.0 < 0.1)


class TestDampingByBand:
    """Band-pass filter bank + Schroeder integral decay metrics (round-7):
    EDT / T20 / T30 / T60 and the equivalent band-centred Q."""

    FS = 8000
    N = 32000   # 4 s

    @classmethod
    def _noise_decay_td(cls, t60):
        """Broadband noise with an exact exponential energy decay: the
        amplitude envelope 10**(-3 t / T60) makes the EDC slope -60/T60 dB/s
        in EVERY band."""
        rng = np.random.default_rng(11)
        t = np.arange(cls.N) / cls.FS
        y = rng.standard_normal(cls.N) * 10.0 ** (-3.0 * t / t60)
        return _make_time_data(y[:, None], cls.FS)

    def test_octave_bands_recover_uniform_t60(self):
        t60 = 0.5
        td = self._noise_decay_td(t60)
        out = analysis.calculate_damping_by_band(
            td, n_chan=0, bands='octave', f_range=(80.0, 3000.0))
        assert out['bands'] == 'octave'
        assert len(out['fc']) >= 4
        # Octave ladder anchors at 1000 Hz and doubles.
        assert np.any(np.isclose(out['fc'], 1000.0))
        np.testing.assert_allclose(out['fc'][1:] / out['fc'][:-1], 2.0)
        ok = np.isfinite(out['T60'])
        assert ok.sum() >= 4
        np.testing.assert_allclose(out['T60'][ok], t60, rtol=0.15)
        # Q consistency: Q = pi*fc*T60/(3 ln10) at each finite band.
        expect_q = np.pi * out['fc'][ok] * out['T60'][ok] / (3 * np.log(10))
        np.testing.assert_allclose(out['Qn'][ok], expect_q, rtol=1e-12)
        # Plotting payload: EDC + T60 fit line per finite band.
        band = out['band_data'][int(np.flatnonzero(ok)[0])]
        assert band['edc_t'].shape == band['edc_db'].shape
        assert band['edc_db'][0] <= 0.0 + 1e-9
        assert 'fit_t' in band and band['fit_db'].shape == (2,)

    def test_single_mode_q_in_its_band(self):
        """A decaying 200 Hz tone of known Q: the octave band containing it
        recovers T60 = 3 ln10 / (zeta wn) and hence Q within tolerance."""
        fs, N = 2000, 16000
        fn, Q = 200.0, 50.0
        x = _decaying_sine(fs, N, fn, Q)[:, None]
        td = _make_time_data(x, fs)
        out = analysis.calculate_damping_by_band(
            td, n_chan=0, bands='octave', f_range=(60.0, 800.0))
        j = int(np.argmin(np.abs(out['fc'] - fn)))
        # 200 Hz falls in the 250 Hz octave band (177..354 Hz).
        assert out['f_lo'][j] < fn < out['f_hi'][j]
        t60_true = 3 * np.log(10) / (1.0 / (2 * Q) * 2 * np.pi * fn)
        assert np.isfinite(out['T60'][j])
        assert abs(out['T60'][j] - t60_true) / t60_true < 0.15
        # Q referred to the BAND CENTRE fc (not fn): scale expectation.
        q_expect = np.pi * out['fc'][j] * t60_true / (3 * np.log(10))
        assert abs(out['Qn'][j] - q_expect) / q_expect < 0.15

    def test_all_gives_one_broadband_band(self):
        td = self._noise_decay_td(0.4)
        out = analysis.calculate_damping_by_band(
            td, n_chan=0, bands='all', f_range=(100.0, 2000.0))
        assert len(out['fc']) == 1
        assert out['f_lo'][0] == 100.0 and out['f_hi'][0] == 2000.0
        assert abs(out['T60'][0] - 0.4) / 0.4 < 0.15

    def test_third_octave_and_tenth_decade_ladders(self):
        td = self._noise_decay_td(0.5)
        third = analysis.calculate_damping_by_band(
            td, n_chan=0, bands='third-octave', f_range=(200.0, 2000.0))
        tenth = analysis.calculate_damping_by_band(
            td, n_chan=0, bands='tenth-decade', f_range=(200.0, 2000.0))
        np.testing.assert_allclose(
            third['fc'][1:] / third['fc'][:-1], 2.0 ** (1 / 3))
        np.testing.assert_allclose(
            tenth['fc'][1:] / tenth['fc'][:-1], 10.0 ** 0.1)
        # Whole bands stay inside the requested range.
        for out in (third, tenth):
            assert np.all(out['f_lo'] >= 200.0 * 0.999)
            assert np.all(out['f_hi'] <= 2000.0 * 1.001)

    def test_start_time_skips_leading_silence(self):
        """Leading silence before the decay: without start_time the EDC's
        top window spans the silent head and the fit misreads; an explicit
        start_time recovers the true T60."""
        t60 = 0.4
        rng = np.random.default_rng(3)
        n_head = self.FS // 2   # 0.5 s of (near) silence
        t = np.arange(self.N) / self.FS
        y = rng.standard_normal(self.N) * 10.0 ** (-3.0 * t / t60)
        y = np.concatenate([1e-8 * rng.standard_normal(n_head), y])
        td = _make_time_data(y[:, None], self.FS)
        out = analysis.calculate_damping_by_band(
            td, n_chan=0, bands='all', f_range=(100.0, 2000.0),
            start_time=0.5)
        assert out['start_time'] == pytest.approx(0.5, abs=1.0 / self.FS)
        assert abs(out['T60'][0] - t60) / t60 < 0.15

    def test_rejects_unknown_ladder(self):
        td = self._noise_decay_td(0.4)
        with pytest.raises(ValueError, match='bands'):
            analysis.calculate_damping_by_band(td, n_chan=0, bands='decade')


class TestResampleToFs:
    """`resample_to_fs` — the round-9 band-limited resampler behind the
    logging digital low-pass, the Time-view Resample tool, and
    'resample to match'. Pure DSP, Mac-runnable."""

    FS = 51200.0

    def _tone(self, f0, seconds=2.0, fs=None):
        fs = fs or self.FS
        t = np.arange(int(fs * seconds)) / fs
        return np.sin(2 * np.pi * f0 * t)

    @staticmethod
    def _core_rms_db(y):
        """dBFS of the middle half (clear of FIR edge transients)."""
        core = y[len(y) // 4: -len(y) // 4]
        return 20 * np.log10(np.sqrt(2) * core.std() + 1e-16)

    def test_downsample_passband_unity_stopband_killed(self):
        # 51200 -> 2000 Hz: passband ends at 2000/2.56 = 781 Hz.
        for f0, expect_pass in ((200.0, True), (700.0, True),
                                (1050.0, False), (3000.0, False)):
            y_out, fs_out, _ = analysis.resample_to_fs(
                self._tone(f0), self.FS, 2000.0)
            level = self._core_rms_db(y_out)
            assert fs_out == pytest.approx(2000.0)
            if expect_pass:
                assert abs(level) < 0.1          # unity gain
            else:
                assert level < -80.0             # alias-protected

    def test_rational_ratio_hits_target_exactly(self):
        # The 48k -> 44.1k audio-world ratio is 147/160.
        y_out, fs_out, (up, down) = analysis.resample_to_fs(
            self._tone(1000.0, seconds=1.0, fs=48000.0), 48000.0, 44100.0)
        assert (up, down) == (147, 160)
        assert fs_out == pytest.approx(44100.0)
        assert len(y_out) == 44100
        assert abs(self._core_rms_db(y_out)) < 0.1

    def test_upsample_unity_gain_no_imaging(self):
        # 2000 -> 8000 Hz: a 300 Hz tone passes at unity, and NOTHING may
        # appear above the ORIGINAL Nyquist (the linear-interp failure
        # mode this method exists to avoid).
        y_out, fs_out, (up, down) = analysis.resample_to_fs(
            self._tone(300.0, seconds=4.0, fs=2000.0), 2000.0, 8000.0)
        assert (up, down) == (4, 1)
        assert fs_out == pytest.approx(8000.0)
        assert abs(self._core_rms_db(y_out)) < 0.1
        core = y_out[len(y_out) // 4: -len(y_out) // 4]
        spec = np.abs(np.fft.rfft(core * np.hanning(len(core))))
        f = np.fft.rfftfreq(len(core), 1 / fs_out)
        imaging = spec[f > 1100.0].max() / spec.max()
        assert 20 * np.log10(imaging) < -90.0

    def test_zero_phase_impulse_position_maps_exactly(self):
        imp = np.zeros(20000)
        imp[7000] = 1.0
        y_out, _, (up, down) = analysis.resample_to_fs(imp, self.FS, 2000.0)
        assert np.argmax(np.abs(y_out)) == round(7000 * up / down)

    def test_two_d_shape_and_noop(self):
        y = np.stack([self._tone(200.0), self._tone(700.0)], axis=1)
        y_out, fs_out, _ = analysis.resample_to_fs(y, self.FS, 2000.0)
        assert y_out.shape == (int(2000.0 * 2.0), 2)
        same, fs_same, ratio = analysis.resample_to_fs(y, self.FS, self.FS)
        assert ratio == (1, 1) and fs_same == self.FS
        np.testing.assert_array_equal(same, y)

    def test_downsample_reduces_broadband_noise(self):
        # White noise: rejecting everything above the new band buys
        # ~10*log10(fs/fs_new) dB of process gain; require most of it.
        rng = np.random.default_rng(42)
        y = rng.standard_normal(int(self.FS * 2))
        y_out, fs_out, _ = analysis.resample_to_fs(y, self.FS, 2000.0)
        gain_db = 20 * np.log10(y.std() / y_out[500:-500].std())
        assert gain_db > 10 * np.log10(self.FS / 2000.0) - 2.0

    def test_rejects_nonpositive_rates(self):
        with pytest.raises(ValueError):
            analysis.resample_to_fs(np.zeros(100), self.FS, 0.0)
        with pytest.raises(ValueError):
            analysis.resample_to_fs(np.zeros(100), -1.0, 100.0)

    def test_coerced_capture_rate_lands_exactly_on_target(self):
        # Hardware-measured case (USB-6003, 2026-07-10): its 80 MHz
        # timebase coerces the digital-low-pass capture request of
        # 48 kHz (6 x 8000) to 80e6/1666 = 48019.2077 Hz. The exact
        # back-ratio 8000/48019.2077 = 833/5000 needs a denominator
        # past the coarse limit_denominator(1024) bound (which returns
        # 1/6 and landed logs at 8003.2 Hz).
        fs_capture = 80e6 / 1666
        y_out, fs_out, (up, down) = analysis.resample_to_fs(
            self._tone(700.0, seconds=1.0, fs=fs_capture), fs_capture, 8000.0)
        assert (up, down) == (833, 5000)
        assert fs_out == pytest.approx(8000.0, abs=1e-6)
        assert abs(self._core_rms_db(y_out)) < 0.1   # passband unity holds

    def test_match_between_near_identical_rates_is_not_a_noop(self):
        # 'Resample to match' from a coerced-capture set (8003.2 Hz =
        # 80e6/9996) onto a clean 8000 Hz set: ratio 2499/2500, which
        # the coarse bound rounds to 1/1 — previously a silent no-op.
        fs_a = 80e6 / 9996
        y_out, fs_out, (up, down) = analysis.resample_to_fs(
            self._tone(700.0, seconds=1.0, fs=fs_a), fs_a, 8000.0)
        assert (up, down) == (2499, 2500)
        assert fs_out == pytest.approx(8000.0, abs=1e-6)
        assert abs(self._core_rms_db(y_out)) < 0.1

    def test_pathological_ratio_degrades_to_coarse_fraction(self):
        # A ratio whose simplest in-tolerance fraction would need a
        # monster FIR must fall back to the coarse 1024-bound fraction
        # (32-bit WASM runs this code — graceful, not exact). pi is as
        # irrational as it gets; the coarse fraction still lands within
        # ~1e-6 relative of the target.
        fs_src = 8000.0 * np.pi / 3.0   # ~8377.58; ratio target/src = 3/pi
        y_out, fs_out, (up, down) = analysis.resample_to_fs(
            self._tone(700.0, seconds=1.0, fs=fs_src), fs_src, 8000.0)
        assert max(up, down) <= 1024
        assert fs_out == pytest.approx(8000.0, rel=1e-5)
