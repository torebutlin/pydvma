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
