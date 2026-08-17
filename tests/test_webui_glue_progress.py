"""Regression tests for the webui glue's mid-compute progress hook (round-11 P7).

The browser engine imports ``pydvma.engine`` from the installed wheel inside
pyodide. A long CWT cannot be interrupted (a busy worker reads no messages) but it CAN
report itself: ``engine.worker.ts`` installs a JS callback via
``set_progress_hook`` at boot, glue passes it to any pydvma function that
accepts ``progress_callback``, and each frame is posted to the main thread.

These tests drive that path under CPython with a plain Python function as the
hook — proving the glue is not pyodide-dependent (no ``import js``), that the
hook reaches BOTH CWT ops, and, most importantly, that glue PROBES the loaded
wheel's signature instead of passing the keyword blind: the browser can be
running a cached older wheel, and a ``TypeError`` there would take out the
whole calc for the sake of a progress bar.
"""

import numpy as np
import pytest

from pydvma import engine as glue

FS = 2000
N = 6000


def _payload(n_channels=1):
    """Time payload exactly as the JS ``timePayload`` marshals it."""
    t = np.arange(N) / FS
    cols = [np.sin(2 * np.pi * (90.0 + 40.0 * c) * t) * np.exp(-t * 3)
            for c in range(n_channels)]
    y = np.column_stack(cols)
    return {
        'time_axis': t.astype(np.float64),
        'time_data': y.astype(np.float64).ravel(),
        'n_channels': n_channels,
        'fs': FS,
    }


@pytest.fixture(autouse=True)
def _clear_hook():
    """No hook installed is the DEFAULT state (native pytest, and the browser
    between boots) — every test starts and ends there."""
    glue.set_progress_hook(None)
    yield
    glue.set_progress_hook(None)


class TestProgressHook:
    def test_cwt_sonogram_reports_progress(self):
        """`calc_sono(method='cwt')` drives the hook once per wavelet scale,
        with a constant total and a final frame at the total."""
        frames = []
        glue.set_progress_hook(lambda d, t: frames.append((d, t)))
        out = glue.calc_sono(**_payload(), ch=0, nperseg=256, noverlap=128,
                             method='cwt', voices_per_octave=8, w0=6.0,
                             f_min=30.0, f_max=400.0)
        n_freqs = out['freq_axis']['shape'][0]
        assert len(frames) == n_freqs
        assert frames[-1] == (n_freqs, n_freqs)
        assert [d for d, _ in frames] == list(range(1, n_freqs + 1))

    def test_cwt_damping_reports_progress(self):
        """`calc_damping(method='cwt')` reports its transform the same way —
        this is the fit that motivated P7 (tens of seconds on a lab record)."""
        frames = []
        glue.set_progress_hook(lambda d, t: frames.append((d, t)))
        out = glue.calc_damping(**_payload(), ch=0, nperseg=256, method='cwt',
                                voices_per_octave=8, w0=6.0,
                                f_min=30.0, f_max=400.0)
        assert frames, 'the CWT damping fit reported no progress at all'
        totals = {t for _, t in frames}
        assert len(totals) == 1                       # one constant total
        assert frames[-1][0] == frames[-1][1]         # ends at 100%
        assert out['fn']['shape'][0] >= 1             # and still fits the mode

    def test_stft_paths_report_nothing(self):
        """The STFT sonogram has no per-scale loop to report, so it stays
        silent rather than faking one frame — an unreported op simply never
        raises a bar."""
        frames = []
        glue.set_progress_hook(lambda d, t: frames.append((d, t)))
        glue.calc_sono(**_payload(), ch=0, nperseg=256, noverlap=128,
                       method='stft')
        assert frames == []

    def test_no_hook_installed_means_no_kwarg(self):
        """With no hook (native pytest, or before the worker installs one) the
        call is the pre-P7 call: `progress_callback` is not passed at all."""
        seen = {}
        real = glue.analysis.calculate_cwt

        def spy(td, **kw):
            seen.update(kw)
            return real(td, **kw)

        glue.analysis.calculate_cwt = spy
        try:
            glue.calc_sono(**_payload(), ch=0, nperseg=256, noverlap=128,
                           method='cwt', voices_per_octave=8, w0=6.0)
        finally:
            glue.analysis.calculate_cwt = real
        assert 'progress_callback' not in seen

    def test_old_wheel_without_the_kwarg_still_runs(self):
        """THE COMPATIBILITY CASE. A cached engine wheel that predates
        `progress_callback` must still compute — glue probes the signature and
        omits the keyword rather than raising TypeError for a progress bar."""
        frames = []
        glue.set_progress_hook(lambda d, t: frames.append((d, t)))
        real = glue.analysis.calculate_cwt

        def old_wheel(time_data, f_range=None, voices_per_octave=16, w0=6.0,
                      max_time_columns=2000, uniform_freq=True):
            return real(time_data, f_range=f_range,
                        voices_per_octave=voices_per_octave, w0=w0,
                        max_time_columns=max_time_columns,
                        uniform_freq=uniform_freq)

        glue.analysis.calculate_cwt = old_wheel
        try:
            out = glue.calc_sono(**_payload(), ch=0, nperseg=256, noverlap=128,
                                 method='cwt', voices_per_octave=8, w0=6.0)
        finally:
            glue.analysis.calculate_cwt = real
        assert out['sono_data']['shape'][0] > 0       # the calc still succeeded
        assert frames == []                           # silently, with no frames

    def test_hook_clears(self):
        """`set_progress_hook(None)` really disarms — the worker clears it the
        same way if the engine is ever re-initialised."""
        frames = []
        glue.set_progress_hook(lambda d, t: frames.append((d, t)))
        glue.set_progress_hook(None)
        glue.calc_sono(**_payload(), ch=0, nperseg=256, noverlap=128,
                       method='cwt', voices_per_octave=8, w0=6.0)
        assert frames == []

    def test_a_non_callable_hook_is_treated_as_no_hook(self):
        """JS ``null`` reaches Python as a ``JsNull`` PROXY, not ``None`` — a
        bare ``is None`` test would store it and the transform would then die
        mid-run with "'JsNull' object is not callable", i.e. only after the
        user had waited. Verified against a real pyodide FFI round-trip; any
        non-callable clears the hook instead."""

        class JsNullish:
            """Stand-in for the JsNull proxy: not None, and not callable."""

        glue.set_progress_hook(JsNullish())
        out = glue.calc_sono(**_payload(), ch=0, nperseg=256, noverlap=128,
                             method='cwt', voices_per_octave=8, w0=6.0)
        assert out['sono_data']['shape'][0] > 0

    def test_multichannel_total_spans_the_whole_call(self):
        """A 2-channel CWT counts channels x scales, so the bar does not reset
        to zero when the second channel starts."""
        frames = []
        glue.set_progress_hook(lambda d, t: frames.append((d, t)))
        out = glue.calc_sono(**_payload(n_channels=2), ch=1, nperseg=256,
                             noverlap=128, method='cwt', voices_per_octave=8,
                             w0=6.0, f_min=30.0, f_max=400.0)
        n_freqs = out['freq_axis']['shape'][0]
        assert len(frames) == 2 * n_freqs
        assert frames[-1] == (2 * n_freqs, 2 * n_freqs)
