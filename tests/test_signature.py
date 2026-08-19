"""Compute-chain signature: FNV-1a 64-bit over little-endian float64
sample bytes, hex-encoded. A TypeScript twin lands as
webui/src/lib/codec/signature.ts — the known-answer vectors here and
there MUST agree; change one and you must change both (the
cross-language fixture round-trip pins it end-to-end).

Large records are hashed through the ROW-STRIDED REDUCTION RULE
documented in pydvma/_signature.py (a naive per-byte hash of a
30 s x 4 ch x 51.2 kHz record measured 2.33 s — far too slow for a save
click). The reduction is part of the cross-language contract, so every
sample-based literal below was verified against an independent
JavaScript implementation written from the contract text, checked in as
``dev/prototypes/signature_prototype.mjs``: run

    node dev/prototypes/signature_prototype.mjs

and the printed table must match these literals row for row.
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
        # [0.0, 1.0, -1.5] as raw '<f8' bytes — the plain hash, with no
        # head and no row selection.
        data = np.array([0.0, 1.0, -1.5]).astype('<f8').tobytes()
        assert _signature.fnv1a64(data) == '7f08103e70108a2d'


class TestSignatureOfSamples:
    """The cross-language contract: samples + fs -> 16 hex chars.

    Every literal here is FROZEN, cross-checked against
    dev/prototypes/signature_prototype.mjs, and duplicated in the
    TypeScript twin's vitest.
    """

    def test_known_answer_1d_vector(self):
        # 1-D input => n_cols = 1; under the row cap, so every row.
        assert _signature.signature_of_samples(
            np.array([0.0, 1.0, -1.5]), 8000.0) == '9f7a0c2bcb86ac6f'

    def test_known_answer_two_column_row_order(self):
        # Pins row-major order AND n_cols in the head:
        # [[0,1],[2,3],[4,5]] at fs = 4.
        samples = np.arange(6, dtype=float).reshape(3, 2)
        assert _signature.signature_of_samples(
            samples, 4.0) == '3c8174748ef2be9c'

    def test_known_answer_single_column_boundary(self):
        # rows_cap = 65536 // 1: 65536 rows hash in full, 65537 reduce
        # (row_stride 2, final row appended).
        full = _signature.signature_of_samples(
            np.arange(65536, dtype=float), 1000.0)
        reduced = _signature.signature_of_samples(
            np.arange(65537, dtype=float), 1000.0)
        assert full == '2b034c2ef734e356'
        assert reduced == 'df601b6ef7b86797'
        assert full != reduced

    def test_known_answer_four_column_boundary(self):
        # rows_cap = 65536 // 4 = 16384 — reduction starts at 16384 TIME
        # samples on a 4-channel record, not 65536.
        full = _signature.signature_of_samples(
            np.arange(16384 * 4, dtype=float).reshape(16384, 4), 1000.0)
        reduced = _signature.signature_of_samples(
            np.arange(16385 * 4, dtype=float).reshape(16385, 4), 1000.0)
        assert full == 'cb10da3bede3b603'
        assert reduced == 'ede25f7b000d0f43'
        assert full != reduced

    def test_known_answer_large_reduced_vector(self):
        # 100000 rows x 2 cols: rows_cap 32768, row_stride 4.
        samples = np.arange(200000, dtype=float).reshape(100000, 2)
        assert _signature.signature_of_samples(
            samples, 1000.0) == 'b7720b7fdea6364f'

    def test_known_answer_special_values(self):
        # NaN / +inf / -inf / -0.0 hash as their stored bit patterns —
        # no normalisation, and the canonical NaN payload matches
        # between numpy and a DataView-written float64.
        samples = np.array([np.nan, np.inf, -np.inf, -0.0])
        assert _signature.signature_of_samples(
            samples, 1.0) == 'b4509e0c4f9f75f0'

    def test_reduction_budget_is_documented_constant(self):
        assert _signature.MAX_HASHED_VALUES == 65536

    def test_reduced_stream_is_bounded(self):
        # The whole point of the rule: the hashed byte count stays
        # bounded however long the record is. Head (3 values) + at most
        # rows_cap + 1 rows of n_cols values.
        n_cols = 4
        arr = np.zeros((30 * 51200, n_cols))
        stream = _signature._sample_stream(arr, 51200.0)
        assert len(stream) <= (3 + _signature.MAX_HASHED_VALUES + n_cols) * 8

    def test_one_dimensional_matches_single_column(self):
        flat = np.arange(10, dtype=float)
        assert (_signature.signature_of_samples(flat, 100.0)
                == _signature.signature_of_samples(flat.reshape(-1, 1),
                                                   100.0))

    def test_fortran_order_hashes_like_c_order(self):
        # A non-contiguous / F-ordered input must hash as its logical
        # row-major layout, not as its memory layout.
        c_order = np.arange(6, dtype=float).reshape(3, 2)
        f_order = np.asfortranarray(c_order)
        assert (_signature.signature_of_samples(f_order, 4.0)
                == _signature.signature_of_samples(c_order, 4.0))

    def test_float32_input_hashes_as_float64(self):
        small = np.array([0.0, 1.0, -1.5], dtype=np.float32)
        assert (_signature.signature_of_samples(small, 8000.0)
                == '9f7a0c2bcb86ac6f')

    def test_row_count_is_part_of_the_hash(self):
        # Appending a zero must change the signature even though the
        # leading samples are identical.
        a = _signature.signature_of_samples(np.zeros(8), 1000.0)
        b = _signature.signature_of_samples(np.zeros(9), 1000.0)
        assert a != b

    def test_channel_count_is_part_of_the_hash(self):
        # Same bytes, different shape: (4, 2) and (2, 4) must differ.
        flat = np.arange(8, dtype=float)
        assert (_signature.signature_of_samples(flat.reshape(4, 2), 1000.0)
                != _signature.signature_of_samples(flat.reshape(2, 4),
                                                   1000.0))

    def test_empty_array_is_hashable(self):
        sig = _signature.signature_of_samples(np.zeros(0), 1000.0)
        assert isinstance(sig, str) and len(sig) == 16

    def test_signatures_across_the_reduction_boundary_are_distinct(self):
        sizes = [1, 65535, 65536, 65537, 131072]
        sigs = [_signature.signature_of_samples(
            np.arange(n, dtype=float), 1000.0) for n in sizes]
        assert all(isinstance(s, str) and len(s) == 16 for s in sigs)
        assert len(set(sigs)) == len(sizes)


class TestReducedBranchSensitivity:
    """What the row-strided rule does and does not see above the cap.

    50000 rows x 4 channels: rows_cap = 16384, row_stride = 4, so rows
    0, 4, 8, ... (and the final row) are hashed IN FULL — every channel
    of every sampled time instant.
    """

    @staticmethod
    def _record():
        return np.arange(50000 * 4, dtype=float).reshape(50000, 4)

    @pytest.mark.parametrize('channel', [0, 1, 2, 3])
    def test_any_channel_of_a_sampled_row_is_visible(self, channel):
        arr = self._record()
        before = _signature.signature_of_samples(arr, 1000.0)
        arr[4, channel] += 1.0                 # row 4 is on the stride
        assert _signature.signature_of_samples(arr, 1000.0) != before

    def test_edit_inside_an_unsampled_gap_is_invisible(self):
        # The documented limitation, pinned so it stays a known
        # trade-off rather than a surprise: row 5 falls between two
        # sampled rows (stride 4) and is not hashed.
        arr = self._record()
        before = _signature.signature_of_samples(arr, 1000.0)
        arr[5, :] += 1.0
        assert _signature.signature_of_samples(arr, 1000.0) == before

    def test_single_channel_tail_edit_is_visible(self):
        # REGRESSION: the superseded flat-BYTE striding rule sampled
        # flat indices spaced gcd(stride, n_cols)-apart per channel —
        # for exactly this record (stride 4, 4 channels) it hashed
        # channel 0 only, so zeroing another channel entirely left the
        # signature unchanged and a broken chain read as intact.
        arr = self._record()
        before = _signature.signature_of_samples(arr, 1000.0)
        arr[45000:, 1] = 0.0                   # tail 10% of channel 1
        assert _signature.signature_of_samples(arr, 1000.0) != before

    def test_scaling_one_channel_is_visible(self):
        arr = self._record()
        before = _signature.signature_of_samples(arr, 1000.0)
        arr[:, 3] *= 2.0
        assert _signature.signature_of_samples(arr, 1000.0) != before

    def test_clean_impulse_on_a_non_zero_channel_is_visible(self):
        # The realistic case: clean_impulse deep-copies and keeps the
        # source unique_id, so the chain check is the only thing that
        # can notice it.
        import pydvma as dvma
        data = dvma.create_test_impulse_data(noise_level=0)
        td = data.time_data_list[0]
        before = _signature.source_signature(td)
        cleaned = dvma.clean_impulse(td, ch_impulse=1)
        assert _signature.source_signature(cleaned) != before


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
