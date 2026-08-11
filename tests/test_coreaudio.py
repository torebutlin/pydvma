"""Tests for the macOS CoreAudio hardware-clock helper.

The pure-logic paths are exercised against a fake CoreAudio so they run
everywhere; the handful of tests that need a real device are marked and
skip off macOS.
"""

import ctypes
import sys

import pytest

from pydvma import _coreaudio


class _FakeCoreAudio:
    """Minimal stand-in for the CoreAudio framework calls used by the module.

    Models one device whose clock changes only after ``settle_calls``
    further reads, so the asynchronous set/verify path is exercised
    rather than assumed instantaneous.
    """

    def __init__(self, rate=192000.0, settle_calls=0, refuse_set=False):
        self.rate = float(rate)
        self.pending = None
        self.settle_calls = settle_calls
        self.refuse_set = refuse_set
        self.set_calls = []

    # -- the two entry points the module calls for a scalar double --
    def AudioObjectGetPropertyData(self, obj, addr, a, b, size, out):
        import ctypes
        if self.pending is not None:
            if self.settle_calls <= 0:
                self.rate = self.pending
                self.pending = None
            else:
                self.settle_calls -= 1
        ctypes.cast(out, ctypes.POINTER(ctypes.c_double))[0] = self.rate
        return 0

    def AudioObjectSetPropertyData(self, obj, addr, a, b, size, val):
        import ctypes
        want = ctypes.cast(val, ctypes.POINTER(ctypes.c_double))[0]
        self.set_calls.append(want)
        if self.refuse_set:
            return -1
        self.pending = float(want)
        return 0


@pytest.fixture
def fake_ca(monkeypatch):
    fake = _FakeCoreAudio()
    monkeypatch.setattr(_coreaudio, '_ca', fake)
    monkeypatch.setattr(_coreaudio, '_cf', object())
    return fake


class TestAvailability:
    def test_unavailable_when_frameworks_missing(self, monkeypatch):
        monkeypatch.setattr(_coreaudio, '_ca', None)
        monkeypatch.setattr(_coreaudio, '_cf', None)
        assert _coreaudio.available() is False

    def test_query_helpers_are_inert_when_unavailable(self, monkeypatch):
        """Off macOS every entry point degrades quietly, so callers need
        no platform branch of their own."""
        monkeypatch.setattr(_coreaudio, '_ca', None)
        monkeypatch.setattr(_coreaudio, '_cf', None)
        assert _coreaudio.device_ids() == []
        assert _coreaudio.device_name(1) is None
        assert _coreaudio.find_device('Scarlett') == (None, None)
        assert _coreaudio.native_rates(1) == []
        assert _coreaudio.get_nominal_rate(1) is None
        assert _coreaudio.set_nominal_rate(1, 44100) is False
        assert _coreaudio.input_volume_db(1) == {}
        assert _coreaudio.set_input_volume_db(1, 0.0) is False
        assert _coreaudio.input_bit_depth(1) is None
        assert _coreaudio.set_input_bit_depth(1, 24) is False

    def test_pinned_rate_yields_false_when_unavailable(self, monkeypatch):
        monkeypatch.setattr(_coreaudio, '_ca', None)
        monkeypatch.setattr(_coreaudio, '_cf', None)
        with _coreaudio.pinned_rate(1, 44100) as ok:
            assert ok is False


class TestSetNominalRate:
    def test_returns_true_once_the_clock_reports_the_new_rate(self, fake_ca):
        assert _coreaudio.set_nominal_rate(1, 44100) is True
        assert _coreaudio.get_nominal_rate(1) == pytest.approx(44100.0)

    def test_waits_for_an_asynchronous_change(self, fake_ca):
        """CoreAudio reconfigures the device asynchronously; the helper
        must poll rather than trust the first read back."""
        fake_ca.settle_calls = 3
        assert _coreaudio.set_nominal_rate(1, 48000, timeout=2.0) is True
        assert _coreaudio.get_nominal_rate(1) == pytest.approx(48000.0)

    def test_returns_false_when_the_device_refuses(self, fake_ca):
        fake_ca.refuse_set = True
        assert _coreaudio.set_nominal_rate(1, 44100) is False

    def test_returns_false_when_the_rate_never_takes(self, fake_ca):
        """A clock that never reaches the requested rate must report
        failure, not let the caller assume a rate it did not get."""
        fake_ca.settle_calls = 10**6
        assert _coreaudio.set_nominal_rate(1, 44100, timeout=0.2) is False


class TestPinnedRate:
    def test_restores_the_previous_rate(self, fake_ca):
        with _coreaudio.pinned_rate(1, 44100) as ok:
            assert ok is True
            assert _coreaudio.get_nominal_rate(1) == pytest.approx(44100.0)
        assert _coreaudio.get_nominal_rate(1) == pytest.approx(192000.0)

    def test_restores_even_when_the_body_raises(self, fake_ca):
        with pytest.raises(RuntimeError):
            with _coreaudio.pinned_rate(1, 44100):
                raise RuntimeError('capture blew up')
        assert _coreaudio.get_nominal_rate(1) == pytest.approx(192000.0)

    def test_leaves_clock_pinned_when_restore_is_false(self, fake_ca):
        with _coreaudio.pinned_rate(1, 44100, restore=False):
            pass
        assert _coreaudio.get_nominal_rate(1) == pytest.approx(44100.0)

    def test_no_op_when_already_at_the_requested_rate(self, fake_ca):
        """Re-pinning a clock that is already correct must not issue a
        set at all — a needless rate change interrupts other audio."""
        with _coreaudio.pinned_rate(1, 192000) as ok:
            assert ok is True
        assert fake_ca.set_calls == []

    def test_yields_false_and_skips_restore_when_the_pin_fails(self, fake_ca):
        fake_ca.refuse_set = True
        with _coreaudio.pinned_rate(1, 44100) as ok:
            assert ok is False
        assert _coreaudio.get_nominal_rate(1) == pytest.approx(192000.0)


def _obj_id(obj):
    """Unwrap a ``ctypes.c_uint32`` object id argument to a plain int.

    The module always passes object ids as ``ctypes.c_uint32(...)``, never
    a bare int, so every dispatch method below needs this to compare
    against the device/stream ids the fake tracks.
    """
    return obj.value if hasattr(obj, 'value') else obj


class _FakeCoreAudioExt:
    """Fake CoreAudio for the volume-control and bit-depth entry points.

    Unlike ``_FakeCoreAudio`` (rate control, one property, one object) this
    one has to dispatch on the property *selector* baked into the
    ``AudioObjectPropertyAddress`` the module passes by reference, because
    ``input_volume_db``/``set_input_volume_db``/``input_bit_depth``/
    ``set_input_bit_depth`` each touch several distinct CoreAudio
    properties ('vold', 'volm', 'stm#', 'pft ') and, for streams, a
    *different* CoreAudio object id (the stream, not the device).

    Models one device (id ``DEVICE_ID``) with:

    - an input volume control on ``volume_elements`` (default ``{1, 2}``,
      matching "per-channel, no main element" as seen on the ESI U24 XL):
      ``AudioObjectHasProperty`` for 'vold' is True only for those
      elements/scope, 'vold' is a readable float, and 'volm' is a
      write-only scalar mapped through ``vol_map`` — a monotonic but
      nonlinear curve, by default matching no known device exactly, so
      that :func:`set_input_volume_db`'s scalar bisection is genuinely
      exercised rather than handed the answer on the first guess.
    - ``stream_ids`` input streams (default two), each with an
      independent bit depth in ``bits``, so 'stm#' / 'pft ' round-trip
      like a real multi-stream USB-audio-class interface. ``refuse_bits``
      makes a stream's 'pft ' set fail outright; ``stuck_bits`` makes the
      set report success but the readback never change, modelling a
      device that accepts the command but never actually retunes.
    """

    DEVICE_ID = 1

    def __init__(self, volume_elements=(1, 2), db=None, vol_map=None,
                stream_ids=(101, 102), bits=None, refuse_bits=(),
                stuck_bits=(), sample_rate=48000.0, channels=2):
        self.volume_elements = set(volume_elements)
        self.db = dict(db) if db is not None else {
            e: -15.0 for e in self.volume_elements}
        self.vol_map = vol_map if vol_map is not None else (
            lambda s: 52.0 * (s ** 1.3) - 40.0)
        self.stream_ids = list(stream_ids)
        self.bits = dict(bits) if bits is not None else {
            sid: 16 for sid in self.stream_ids}
        self.refuse_bits = set(refuse_bits)
        self.stuck_bits = set(stuck_bits)
        self.sample_rate = float(sample_rate)
        self.channels = int(channels)
        self.volm_writes = []   # [(element, scalar), ...]
        self.pft_writes = []    # [(stream_id, {asbd field: value}), ...]

    def _addr(self, addr_ref):
        return ctypes.cast(
            addr_ref, ctypes.POINTER(_coreaudio.AudioObjectPropertyAddress)
        ).contents

    def AudioObjectHasProperty(self, obj, addr_ref):
        addr = self._addr(addr_ref)
        if (addr.mSelector == _coreaudio.kAudioDevicePropertyVolumeDecibels
                and addr.mScope == _coreaudio.kAudioObjectPropertyScopeInput):
            return addr.mElement in self.volume_elements
        return False

    def AudioObjectGetPropertyDataSize(self, obj, addr_ref, a, b, size_ref):
        addr = self._addr(addr_ref)
        if addr.mSelector == _coreaudio.kAudioDevicePropertyStreams:
            n = len(self.stream_ids)
            ctypes.cast(size_ref, ctypes.POINTER(ctypes.c_uint32))[0] = (
                n * ctypes.sizeof(ctypes.c_uint32))
            return 0
        return -1

    def AudioObjectGetPropertyData(self, obj, addr_ref, a, b, size_ref, out):
        addr = self._addr(addr_ref)
        selector = addr.mSelector

        if selector == _coreaudio.kAudioDevicePropertyVolumeDecibels:
            val = self.db.get(addr.mElement)
            if val is None:
                return -1
            ctypes.cast(out, ctypes.POINTER(ctypes.c_float))[0] = val
            return 0

        if selector == _coreaudio.kAudioDevicePropertyStreams:
            ptr = ctypes.cast(out, ctypes.POINTER(ctypes.c_uint32))
            for i, sid in enumerate(self.stream_ids):
                ptr[i] = sid
            return 0

        if selector == _coreaudio.kAudioStreamPropertyPhysicalFormat:
            stream_id = _obj_id(obj)
            bits = self.bits.get(stream_id)
            if bits is None:
                return -1
            frame_bytes = self.channels * bits // 8
            fmt = ctypes.cast(
                out, ctypes.POINTER(_coreaudio.AudioStreamBasicDescription)
            )[0]
            fmt.mSampleRate = self.sample_rate
            fmt.mFormatID = _coreaudio.kAudioFormatLinearPCM
            fmt.mFormatFlags = _coreaudio._LPCM_INT_PACKED
            fmt.mBytesPerPacket = frame_bytes
            fmt.mFramesPerPacket = 1
            fmt.mBytesPerFrame = frame_bytes
            fmt.mChannelsPerFrame = self.channels
            fmt.mBitsPerChannel = bits
            fmt.mReserved = 0
            return 0

        return -1

    def AudioObjectSetPropertyData(self, obj, addr_ref, a, b, size, val):
        addr = self._addr(addr_ref)
        selector = addr.mSelector

        if selector == _coreaudio.kAudioDevicePropertyVolumeScalar:
            scalar = float(ctypes.cast(val, ctypes.POINTER(ctypes.c_float))[0])
            self.volm_writes.append((addr.mElement, scalar))
            self.db[addr.mElement] = float(self.vol_map(scalar))
            return 0

        if selector == _coreaudio.kAudioStreamPropertyPhysicalFormat:
            stream_id = _obj_id(obj)
            fmt = ctypes.cast(
                val, ctypes.POINTER(_coreaudio.AudioStreamBasicDescription)
            )[0]
            self.pft_writes.append((stream_id, {
                'mSampleRate': fmt.mSampleRate,
                'mFormatID': fmt.mFormatID,
                'mBitsPerChannel': fmt.mBitsPerChannel,
                'mBytesPerFrame': fmt.mBytesPerFrame,
                'mChannelsPerFrame': fmt.mChannelsPerFrame,
            }))
            if stream_id in self.refuse_bits:
                return -1
            if stream_id not in self.stuck_bits:
                self.bits[stream_id] = int(fmt.mBitsPerChannel)
            return 0

        return -1


@pytest.fixture
def fake_ext(monkeypatch):
    """A :class:`_FakeCoreAudioExt` wired in, with settling time removed.

    Real hardware needs 0.15 s between volume-bisection steps and 0.05 s
    between bit-depth polls; neither buys these tests anything, so
    ``time.sleep`` (as seen by the module) is patched to a no-op and both
    the convergence and the timeout paths run in milliseconds.
    """
    fake = _FakeCoreAudioExt()
    monkeypatch.setattr(_coreaudio, '_ca', fake)
    monkeypatch.setattr(_coreaudio, '_cf', object())
    monkeypatch.setattr(_coreaudio.time, 'sleep', lambda s: None)
    return fake


class TestInputVolumeDb:
    def test_returns_per_element_dict_from_the_device(self, fake_ext):
        fake_ext.volume_elements = {1, 2}
        fake_ext.db = {1: -6.0, 2: 3.5}
        result = _coreaudio.input_volume_db(_FakeCoreAudioExt.DEVICE_ID)
        assert result == pytest.approx({1: -6.0, 2: 3.5})

    def test_empty_dict_when_device_has_no_volume_control(self, fake_ext):
        fake_ext.volume_elements = set()
        assert _coreaudio.input_volume_db(_FakeCoreAudioExt.DEVICE_ID) == {}


class TestSetInputVolumeDb:
    def test_converges_to_target_via_scalar_bisection(self, fake_ext):
        """'vold' can't be written directly (real devices accept the set
        but never change) so the module bisects the 'volm' scalar against
        the 'vold' dB readback. Start both elements off zero and confirm
        the bisection lands within tolerance and actually wrote 'volm'."""
        fake_ext.db = {1: -15.0, 2: -15.0}
        ok = _coreaudio.set_input_volume_db(_FakeCoreAudioExt.DEVICE_ID, 0.0,
                                            tolerance=0.25)
        assert ok is True
        assert abs(fake_ext.db[1]) <= 0.25
        assert abs(fake_ext.db[2]) <= 0.25
        written_elements = {el for el, _ in fake_ext.volm_writes}
        assert written_elements == {1, 2}

    def test_elements_already_within_tolerance_make_no_writes(self, fake_ext):
        """The common already-at-0-dB case must not touch 'volm' at all."""
        fake_ext.db = {1: 0.1, 2: -0.2}
        ok = _coreaudio.set_input_volume_db(_FakeCoreAudioExt.DEVICE_ID, 0.0,
                                            tolerance=0.25)
        assert ok is True
        assert fake_ext.volm_writes == []

    def test_returns_false_when_there_are_no_volume_elements(self, fake_ext):
        fake_ext.volume_elements = set()
        assert _coreaudio.set_input_volume_db(
            _FakeCoreAudioExt.DEVICE_ID, 0.0) is False

    def test_returns_false_when_the_mapping_never_reaches_target(self, fake_ext):
        """A control that is stuck (or whose scalar<->dB mapping simply
        cannot reach the requested level) must report failure rather than
        silently leave the gain wrong."""
        fake_ext.db = {1: -50.0, 2: -50.0}
        fake_ext.vol_map = lambda s: -50.0  # clamped; never reaches 0 dB
        ok = _coreaudio.set_input_volume_db(_FakeCoreAudioExt.DEVICE_ID, 0.0,
                                            tolerance=0.25)
        assert ok is False


class TestInputBitDepth:
    def test_returns_minimum_across_streams_with_different_depths(self, fake_ext):
        fake_ext.stream_ids = [101, 102]
        fake_ext.bits = {101: 24, 102: 16}
        assert _coreaudio.input_bit_depth(_FakeCoreAudioExt.DEVICE_ID) == 16

    def test_returns_none_when_the_device_has_no_streams(self, fake_ext):
        fake_ext.stream_ids = []
        fake_ext.bits = {}
        assert _coreaudio.input_bit_depth(_FakeCoreAudioExt.DEVICE_ID) is None


class TestSetInputBitDepth:
    def test_changes_stream_preserving_rate_and_channel_count(self, fake_ext):
        """Only mBitsPerChannel (and the frame byte counts it implies)
        should change; mSampleRate and mChannelsPerFrame must come
        through from the stream's current format untouched."""
        fake_ext.stream_ids = [101]
        fake_ext.bits = {101: 16}
        fake_ext.sample_rate = 44100.0
        fake_ext.channels = 2
        ok = _coreaudio.set_input_bit_depth(_FakeCoreAudioExt.DEVICE_ID, 24)
        assert ok is True
        assert len(fake_ext.pft_writes) == 1
        stream_id, written = fake_ext.pft_writes[0]
        assert stream_id == 101
        assert written['mBitsPerChannel'] == 24
        assert written['mBytesPerFrame'] == 2 * 3
        assert written['mFormatID'] == _coreaudio.kAudioFormatLinearPCM
        assert written['mSampleRate'] == pytest.approx(44100.0)
        assert written['mChannelsPerFrame'] == 2
        assert _coreaudio.input_bit_depth(_FakeCoreAudioExt.DEVICE_ID) == 24

    def test_skips_streams_already_at_the_target_depth(self, fake_ext):
        fake_ext.stream_ids = [101, 102]
        fake_ext.bits = {101: 24, 102: 16}
        ok = _coreaudio.set_input_bit_depth(_FakeCoreAudioExt.DEVICE_ID, 24)
        assert ok is True
        assert [sid for sid, _ in fake_ext.pft_writes] == [102]

    def test_returns_false_when_a_stream_refuses_the_format(self, fake_ext):
        fake_ext.stream_ids = [101]
        fake_ext.bits = {101: 16}
        fake_ext.refuse_bits = {101}
        assert _coreaudio.set_input_bit_depth(
            _FakeCoreAudioExt.DEVICE_ID, 24) is False

    def test_returns_false_when_readback_never_reaches_target(self, fake_ext):
        """The set call can succeed while the device's physical format
        never actually reports the new depth; the poll must time out and
        report failure rather than hang or lie about the outcome. Real
        polling waits 0.05 s per iteration but the fixture no-ops
        time.sleep, so a short timeout still completes promptly."""
        fake_ext.stream_ids = [101]
        fake_ext.bits = {101: 16}
        fake_ext.stuck_bits = {101}
        ok = _coreaudio.set_input_bit_depth(_FakeCoreAudioExt.DEVICE_ID, 24,
                                            timeout=0.05)
        assert ok is False


@pytest.mark.skipif(sys.platform != 'darwin',
                    reason='CoreAudio clock control is macOS-only')
class TestRealCoreAudio:
    def test_available_on_macos(self):
        assert _coreaudio.available() is True

    def test_enumerates_devices_with_names(self):
        ids = _coreaudio.device_ids()
        assert ids, 'expected at least one CoreAudio device'
        assert any(_coreaudio.device_name(d) for d in ids)

    def test_every_device_reports_a_readable_clock_and_rate_list(self):
        """Whatever is plugged in, the two capability queries must agree:
        a device's current clock is one of the rates it advertises."""
        checked = 0
        for dev in _coreaudio.device_ids():
            rates = _coreaudio.native_rates(dev)
            current = _coreaudio.get_nominal_rate(dev)
            if not rates or current is None:
                continue
            checked += 1
            assert any(abs(current - r) < 1e-6 for r in rates), (
                '%r clock %s not in advertised rates %s'
                % (_coreaudio.device_name(dev), current, rates))
        assert checked, 'no device reported both a rate list and a clock'

    def test_find_device_resolves_by_substring(self):
        ids = _coreaudio.device_ids()
        name = next((_coreaudio.device_name(d) for d in ids
                     if _coreaudio.device_name(d)), None)
        assert name is not None
        dev, found = _coreaudio.find_device(name)
        assert dev is not None and found == name

    def test_input_volume_db_returns_dict_of_floats(self):
        """Read-only: whatever is plugged in, the volume dict (possibly
        empty, for a device with no input volume control) must be keyed
        by CoreAudio element with float dB values, and never raise."""
        for dev in _coreaudio.device_ids():
            vols = _coreaudio.input_volume_db(dev)
            assert isinstance(vols, dict)
            for element, db in vols.items():
                assert isinstance(element, int)
                assert isinstance(db, float)

    def test_input_bit_depth_returns_none_or_positive_int(self):
        """Read-only: every device either has no reportable input stream
        format (None) or a genuine positive bit depth — never 0 or a
        type other than int."""
        for dev in _coreaudio.device_ids():
            depth = _coreaudio.input_bit_depth(dev)
            assert depth is None or (isinstance(depth, int) and depth > 0)
