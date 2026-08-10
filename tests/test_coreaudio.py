"""Tests for the macOS CoreAudio hardware-clock helper.

The pure-logic paths are exercised against a fake CoreAudio so they run
everywhere; the handful of tests that need a real device are marked and
skip off macOS.
"""

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
