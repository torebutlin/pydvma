"""Compute-chain signature: FNV-1a 64-bit over little-endian float64
sample bytes, hex-encoded. The SAME algorithm is implemented in
webui/src/lib/codec/signature.ts — the known-answer vectors here and
there MUST agree; change one and you must change both (the
cross-language fixture round-trip pins it end-to-end).

Large arrays are hashed through the REDUCTION RULE documented in
pydvma/_signature.py (a naive per-byte hash of a 30 s x 4 ch x 51.2 kHz
record measured 2.33 s — far too slow for a save click). The reduction
is part of the cross-language contract: the vectors below were verified
against a JavaScript prototype of the identical rule before being
frozen.
"""
import numpy as np
import pytest

from pydvma import _signature


class TestFnv1a64:

    def test_known_answer_empty(self):
        assert _signature.fnv1a64(b'') == 'cbf29ce484222325'

    def test_known_answer_abc(self):
        assert _signature.fnv1a64(b'abc') == 'e71fa2190541574b'

    def test_known_answer_float_vector(self):
        # THE cross-language vector: [0.0, 1.0, -1.5] as '<f8' bytes.
        # FROZEN — the twin of this assertion lives in
        # webui/tests/codec/signature.test.ts.
        data = np.array([0.0, 1.0, -1.5]).astype('<f8').tobytes()
        assert _signature.fnv1a64(data) == '7f08103e70108a2d'


class TestSignatureOfSamples:
    """The cross-language contract: samples + fs -> 16 hex chars.

    Every literal here is FROZEN and duplicated in
    webui/tests/codec/signature.test.ts (`sourceSignature`).
    """

    def test_known_answer_small_vector(self):
        # [0.0, 1.0, -1.5] at fs = 8000 — under the reduction threshold,
        # so every sample is hashed.
        assert _signature.signature_of_samples(
            np.array([0.0, 1.0, -1.5]), 8000.0) == 'fce9ee7c903fd2e2'

    def test_known_answer_multichannel_flat_order(self):
        # Pins the flattening convention: C-order (row-major), i.e. the
        # channels of one sample are adjacent, exactly as the .npy
        # payload is laid out. [[0,1],[2,3],[4,5]] at fs = 4.
        samples = np.arange(6, dtype=float).reshape(3, 2)
        assert _signature.signature_of_samples(
            samples, 4.0) == '9894565286e99acc'

    def test_known_answer_large_vector_uses_reduction(self):
        # 200000 samples > the 65536 threshold, so stride = 4 and the
        # final sample is appended. FROZEN cross-language vector.
        samples = np.arange(200000, dtype=float)
        assert _signature.signature_of_samples(
            samples, 1000.0) == '4256079fe531bdf3'

    def test_reduction_threshold_is_documented_constant(self):
        assert _signature.MAX_HASHED_SAMPLES == 65536

    def test_reduced_stream_is_bounded(self):
        # The whole point of the rule: the hashed byte count stays
        # bounded however long the record is.
        n = 4 * 30 * 51200
        stream = _signature._sample_stream(np.zeros(n), 51200.0)
        assert len(stream) <= (_signature.MAX_HASHED_SAMPLES + 3) * 8

    def test_fortran_order_hashes_like_c_order(self):
        # A non-contiguous / F-ordered input must hash as its logical
        # C-order flattening, not as its memory layout.
        c_order = np.arange(6, dtype=float).reshape(3, 2)
        f_order = np.asfortranarray(c_order)
        assert (_signature.signature_of_samples(f_order, 4.0)
                == _signature.signature_of_samples(c_order, 4.0))

    def test_float32_input_hashes_as_float64(self):
        small = np.array([0.0, 1.0, -1.5], dtype=np.float32)
        assert (_signature.signature_of_samples(small, 8000.0)
                == 'fce9ee7c903fd2e2')

    def test_sample_count_is_part_of_the_hash(self):
        # Appending a zero must change the signature even though the
        # leading samples are identical.
        a = _signature.signature_of_samples(np.zeros(8), 1000.0)
        b = _signature.signature_of_samples(np.zeros(9), 1000.0)
        assert a != b

    def test_empty_array_is_hashable(self):
        sig = _signature.signature_of_samples(np.zeros(0), 1000.0)
        assert isinstance(sig, str) and len(sig) == 16


def _time_data(n=16, channels=2, fs=8000, offset=0.0):
    from pydvma import datastructure, options
    s = options.MySettings(device_driver='mock', channels=channels, fs=fs)
    return datastructure.TimeData(
        time_axis=np.arange(n) / float(fs),
        time_data=np.arange(n * channels, dtype=float).reshape(
            n, channels) + offset,
        settings=s)


class TestSourceSignature:

    def test_signature_of_time_data(self):
        td = _time_data()
        sig = _signature.source_signature(td)
        assert isinstance(sig, str) and len(sig) == 16
        # deterministic
        assert sig == _signature.source_signature(td)

    def test_signature_changes_when_samples_change(self):
        td = _time_data()
        before = _signature.source_signature(td)
        td.time_data[3, 1] += 1.0
        assert _signature.source_signature(td) != before

    def test_signature_ignores_display_state(self):
        td = _time_data()
        before = _signature.source_signature(td)
        td.channel_cal_factors = np.array([2.5, 0.4])
        td.units = ['V', 'm/s^2']
        td.test_name = 'renamed'
        assert _signature.source_signature(td) == before

    def test_signature_includes_fs(self):
        a = _time_data(fs=8000)
        b = _time_data(fs=16000)
        np.testing.assert_array_equal(a.time_data, b.time_data)
        assert (_signature.source_signature(a)
                != _signature.source_signature(b))

    def test_signature_matches_signature_of_samples(self):
        td = _time_data()
        assert (_signature.source_signature(td)
                == _signature.signature_of_samples(td.time_data,
                                                   td.settings.fs))

    def test_signature_of_a_list_of_sources(self):
        # calculate_tf_averaged has a TimeDataList source: the streams
        # are concatenated in list order (a Python-side extension; the
        # single-source form is the cross-language contract).
        a, b = _time_data(), _time_data(offset=1.0)
        sig = _signature.source_signature([a, b])
        assert isinstance(sig, str) and len(sig) == 16
        assert sig != _signature.source_signature([b, a])   # order matters
        assert sig != _signature.source_signature(a)

    def test_signature_survives_missing_settings(self):
        td = _time_data()
        td.settings = None
        sig = _signature.source_signature(td)
        assert sig == _signature.signature_of_samples(td.time_data, 0.0)

    @pytest.mark.parametrize('n_samples', [1, 65535, 65536, 65537])
    def test_signature_across_the_reduction_boundary(self, n_samples):
        # No crash and no duplicate signatures either side of the
        # threshold.
        samples = np.arange(n_samples, dtype=float)
        sig = _signature.signature_of_samples(samples, 1000.0)
        assert isinstance(sig, str) and len(sig) == 16


class TestStampedByAnalysis:
    """FFT/TF results carry the signature + settings provenance."""

    def test_fft_is_stamped(self):
        from pydvma import analysis
        td = _time_data(n=64)
        fd = analysis.calculate_fft(td, window='hann')
        assert fd.source_signature == _signature.source_signature(td)
        assert fd.source_settings['window'] == 'hann'
        assert len(fd.source_settings['time_range']) == 2

    def test_fft_signature_is_of_the_source_not_the_result(self):
        from pydvma import analysis
        td = _time_data(n=64)
        fd = analysis.calculate_fft(td)
        td.time_data[0, 0] += 1.0
        # the stamp is a snapshot: mutating the source afterwards makes
        # the chain STALE, which is exactly the signal we want
        assert fd.source_signature != _signature.source_signature(td)

    def test_tf_is_stamped(self):
        from pydvma import analysis
        td = _time_data(n=256)
        tf = analysis.calculate_tf(td, ch_in=0, N_frames=2, overlap=0.5,
                                   window='hann')
        assert tf.source_signature == _signature.source_signature(td)
        assert tf.source_settings['window'] == 'hann'
        assert tf.source_settings['ch_in'] == 0
        assert tf.source_settings['N_frames'] == 2
        assert tf.source_settings['overlap'] == 0.5

    def test_tf_averaged_is_stamped(self):
        from pydvma import analysis, datastructure
        tdl = datastructure.TimeDataList(
            [_time_data(n=256), _time_data(n=256, offset=0.5)])
        tf = analysis.calculate_tf_averaged(tdl, ch_in=0, window='hann')
        assert tf.source_signature == _signature.source_signature(tdl)
        assert tf.source_settings['window'] == 'hann'
        assert tf.source_settings['ch_in'] == 0

    def test_source_settings_are_json_safe(self):
        import json

        from pydvma import analysis
        td = _time_data(n=64)
        fd = analysis.calculate_fft(td)
        tf = analysis.calculate_tf(td)
        for item in (fd, tf):
            # plain scalars only — the container writes these into the
            # strict-JSON manifest
            json.dumps(item.source_settings, allow_nan=False)
