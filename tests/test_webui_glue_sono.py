"""Regression tests for the webui glue's sonogram ops (Task 5b).

The browser/native engine imports ``pydvma.engine`` and drives it with plain
dicts / flat float64 arrays. These tests import that same module directly under
CPython and exercise the two sonogram ops the way the JS side does:

- ``calc_sono`` — one channel, real MAGNITUDE image, what the heat display
  draws (unchanged behaviour, pinned here because Task 5b refactored its guts
  into the shared ``_sono_data`` helper);
- ``calc_sono_full`` — the same transform as the COMPLEX ``(Nf, Nt, Nc)`` cube a
  stored ``SonoData`` holds, for the "Include sonogram?" save prompt.

The pairing is the point: whatever the user saw on screen must be the modulus
of what lands in the file.
"""

import numpy as np
import pytest

from pydvma import engine as glue

FS = 2000
N = 4096


def _payload(n_channels=3):
    """Multi-channel time payload exactly as JS ``timePayload`` marshals it."""
    t = np.arange(N) / FS
    cols = [np.sin(2 * np.pi * f * t) for f in (100.0, 250.0, 400.0)[:n_channels]]
    y = np.stack(cols, axis=1)
    return {
        'time_axis': t.astype(np.float64),
        'time_data': y.astype(np.float64).ravel(),
        'n_channels': n_channels,
        'fs': FS,
    }


def _marsh(a):
    """Rebuild a numpy array from a glue ``_arr`` marshal."""
    data = np.asarray(a['data'], dtype=np.float64)
    if a['complex']:
        data = data[0::2] + 1j * data[1::2]
    return data.reshape(a['shape'])


def _full(p, channels, **kw):
    return glue.calc_sono_full(p['time_axis'], p['time_data'], p['n_channels'],
                               p['fs'], channels=channels, nperseg=256,
                               noverlap=128, **kw)


def _same_image(saved_plane, shown, why=''):
    """Assert two sonogram images agree to float precision.

    Not bit-equality: since `calc_sono_full` slices the requested COLUMNS
    before transforming, its STFT batches a narrower array than the
    all-channel display call, and a batched FFT's summation order is
    width-dependent. The images therefore differ by ~1 ULP OF THE IMAGE PEAK
    (measured ~2e-16 relative). Tolerance is scaled to the peak rather than
    per-element, because the near-null bins of a pure tone sit at 1e-16 where
    any relative test is meaningless noise.
    """
    peak = float(np.abs(shown).max())
    np.testing.assert_allclose(saved_plane, shown, rtol=0,
                               atol=1e-12 * max(peak, 1e-300), err_msg=why)


class TestCalcSonoFull:

    def test_returns_the_complex_cube_for_the_chosen_channels(self):
        p = _payload()
        out = _full(p, [0, 2])
        cube = _marsh(out['sono_data'])
        assert out['sono_data']['complex'] is True
        n_f = len(_marsh(out['freq_axis']))
        n_t = len(_marsh(out['time_axis']))
        assert cube.shape == (n_f, n_t, 2)
        assert np.iscomplexobj(cube)
        # not all-real: a windowed STFT of a sine has genuine phase
        assert np.abs(cube.imag).max() > 0

    def test_cube_plane_order_follows_the_requested_channel_list(self):
        p = _payload()
        forward = _marsh(_full(p, [0, 2])['sono_data'])
        reversed_ = _marsh(_full(p, [2, 0])['sono_data'])
        np.testing.assert_allclose(forward[:, :, 0], reversed_[:, :, 1])
        np.testing.assert_allclose(forward[:, :, 1], reversed_[:, :, 0])

    def test_single_channel_matches_what_the_display_op_showed(self):
        # The contract behind the save prompt: |saved cube| == the image the
        # user was looking at when they chose to include it.
        p = _payload()
        shown = glue.calc_sono(p['time_axis'], p['time_data'], p['n_channels'],
                               p['fs'], ch=1, nperseg=256, noverlap=128)
        saved = _full(p, [1])
        _same_image(np.abs(_marsh(saved['sono_data'])[:, :, 0]),
                    _marsh(shown['sono_data']))
        np.testing.assert_allclose(_marsh(saved['freq_axis']),
                                   _marsh(shown['freq_axis']))
        np.testing.assert_allclose(_marsh(saved['time_axis']),
                                   _marsh(shown['time_axis']))

    def test_cwt_method_also_yields_a_complex_cube(self):
        p = _payload(n_channels=1)
        out = _full(p, [0], method='cwt', voices_per_octave=4)
        cube = _marsh(out['sono_data'])
        assert cube.shape[2] == 1
        assert np.iscomplexobj(cube)
        # CWT keeps its NATIVE log grid here, as calc_sono does
        f = _marsh(out['freq_axis'])
        assert f[0] < f[-1] and len(f) == cube.shape[0]

    def test_cwt_matches_the_display_op_channel_for_channel(self):
        p = _payload(n_channels=2)
        shown = glue.calc_sono(p['time_axis'], p['time_data'], p['n_channels'],
                               p['fs'], ch=1, nperseg=256, noverlap=128,
                               method='cwt', voices_per_octave=4)
        saved = _full(p, [0, 1], method='cwt', voices_per_octave=4)
        # the CWT loops channels independently, so this one IS bit-identical
        np.testing.assert_allclose(
            np.abs(_marsh(saved['sono_data'])[:, :, 1]),
            _marsh(shown['sono_data']), rtol=0, atol=0)

    def test_out_of_range_channel_is_refused_not_clamped(self):
        p = _payload(n_channels=2)
        with pytest.raises(ValueError, match='out of range'):
            _full(p, [0, 5])

    def test_empty_channel_list_is_refused(self):
        p = _payload()
        with pytest.raises(ValueError, match='No channels'):
            _full(p, [])


class TestCalcSonoFullCostsOnlyWhatIsAsked:
    """The requested channels are sliced out BEFORE the transform runs.

    "This channel" on a 4-channel record must not pay for four transforms —
    on a lab-length CWT that is the difference between seconds and minutes.
    The transform's own per-channel work is the cheap proxy for the cost
    claim: `calculate_cwt` reports ``total = n_channels * n_scales``, so the
    total it reports IS the number of channels it was handed.
    """

    def test_cwt_progress_total_counts_only_the_requested_channels(self):
        seen = []
        glue.set_progress_hook(lambda done, total: seen.append(total))
        try:
            p = _payload(n_channels=3)
            _full(p, [1], method='cwt', voices_per_octave=4)
            one = set(seen)
            seen.clear()
            _full(p, [0, 1, 2], method='cwt', voices_per_octave=4)
            three = set(seen)
        finally:
            glue.set_progress_hook(None)
        assert len(one) == len(three) == 1
        # one channel in ⇒ one channel's worth of scales, not three
        assert three.pop() == 3 * one.pop()

    def test_stft_transforms_only_the_requested_columns(self, monkeypatch):
        # The count of columns handed to the STFT is len(channels).
        from pydvma import analysis
        widths = []
        real = analysis._spectrogram_complex_lowmem

        def spy(y, *a, **kw):
            widths.append(np.asarray(y).shape[1])
            return real(y, *a, **kw)

        monkeypatch.setattr(analysis, '_spectrogram_complex_lowmem', spy)
        p = _payload(n_channels=3)
        _full(p, [2])
        _full(p, [0, 2])
        assert widths == [1, 2]

    def test_single_channel_plane_still_equals_the_display_image(self):
        # The slicing must not change the numbers: this is the contract the
        # save prompt rests on, re-asserted for the sliced path.
        p = _payload(n_channels=3)
        shown = glue.calc_sono(p['time_axis'], p['time_data'], p['n_channels'],
                               p['fs'], ch=2, nperseg=256, noverlap=128)
        saved = _full(p, [2])
        _same_image(np.abs(_marsh(saved['sono_data'])[:, :, 0]),
                    _marsh(shown['sono_data']))


class TestCalcSonoFullPreflight:
    """An over-size cube is refused BEFORE it is transformed or allocated."""

    def test_over_ceiling_request_refuses_with_the_remedies(self, monkeypatch):
        from pydvma import analysis
        monkeypatch.setattr(analysis, 'CWT_MAX_IMAGE_BYTES', 1024)   # 1 kB
        p = _payload(n_channels=2)
        with pytest.raises(ValueError) as e:
            _full(p, [0, 1])
        msg = str(e.value)
        assert 'too large' in msg
        assert 'frequency bins' in msg and 'time frames' in msg
        assert 'ONE channel' in msg and 'coarser nFFT' in msg
        assert 'three times' in msg

    def test_refusal_happens_before_any_transform(self, monkeypatch):
        from pydvma import analysis
        monkeypatch.setattr(analysis, 'CWT_MAX_IMAGE_BYTES', 1024)
        called = []
        monkeypatch.setattr(analysis, '_spectrogram_complex_lowmem',
                            lambda *a, **kw: called.append(1))
        p = _payload()
        with pytest.raises(ValueError, match='too large'):
            _full(p, [0])
        assert called == []

    def test_cwt_refusal_names_the_voices_remedy(self, monkeypatch):
        from pydvma import analysis
        monkeypatch.setattr(analysis, 'CWT_MAX_IMAGE_BYTES', 1024)
        p = _payload(n_channels=1)
        with pytest.raises(ValueError, match='voices per octave'):
            _full(p, [0], method='cwt', voices_per_octave=8)

    def test_predicted_shape_matches_the_real_transform(self):
        # The preflight is only worth having if its prediction is right.
        p = _payload(n_channels=2)
        for kw, chans in (({}, [0]), ({}, [0, 1]),
                          ({'method': 'cwt', 'voices_per_octave': 4}, [1])):
            got = _marsh(_full(p, chans, **kw)['sono_data']).shape
            pred = glue._sono_cube_shape(
                N, FS, len(chans), 256, 128,
                kw.get('method', 'stft'), kw.get('voices_per_octave', 16),
                6.0, None, None)
            assert pred + (len(chans),) == got, (kw, chans)

    def test_a_realistic_cube_passes_the_preflight(self):
        # Guard against a ceiling so tight it refuses ordinary work: the
        # 3c6 envelope (30 s x 3 kHz x 2 ch) must sail through.
        pred = glue._sono_cube_shape(30 * 3000, 3000, 2, 512, 256,
                                     'stft', 16, 6.0, None, None)
        from pydvma import analysis
        assert pred[0] * pred[1] * 2 * 16 < analysis.CWT_MAX_IMAGE_BYTES
