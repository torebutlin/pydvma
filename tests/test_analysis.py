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
        np.testing.assert_allclose(csd.Cxy, Cxy_ref, rtol=1e-12, atol=1e-12)

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
