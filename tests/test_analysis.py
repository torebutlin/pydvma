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
