# -*- coding: utf-8 -*-
"""Tests for `pydvma.verify` — absolute input-chain scaling verification
against a known-level source (NI/soundcard loopback, or an external
SCPI source such as `RigolDG1022Z`).

All headless/mockable: no NI hardware, no sound card, no real VISA
instrument required. See `dev/bla_soundcard_check.py` for the sibling
pattern of a headless hardware-adjacent check in this repo, and
TODO.md's "Input-scaling verification tool" item for the design intent.
"""
import numpy as np
import pytest

import pydvma as dvma
from pydvma import options, streams, verify


# ---------------------------------------------------------------------------
# Tone-estimation math
# ---------------------------------------------------------------------------

class TestMeasureToneVrms:

    def test_pure_tone_measured_within_1_percent(self):
        fs = 10000.0
        freq = 997.0
        vrms = 0.25
        duration = 1.0
        N = int(round(duration * fs))
        t = np.arange(N) / fs
        x = vrms * np.sqrt(2) * np.sin(2 * np.pi * freq * t)

        measured = verify._measure_tone_vrms(x, fs, freq)
        assert measured == pytest.approx(vrms, rel=0.01)

    def test_broadband_noise_at_minus_30db_does_not_bias_estimate(self):
        fs = 10000.0
        freq = 997.0
        vrms = 0.25
        duration = 1.0
        N = int(round(duration * fs))
        t = np.arange(N) / fs
        rng = np.random.default_rng(20260811)
        # -30 dB relative to the tone's RMS in AMPLITUDE terms.
        noise_rms = vrms * 10 ** (-30.0 / 20.0)
        x = (vrms * np.sqrt(2) * np.sin(2 * np.pi * freq * t)
             + rng.normal(0, noise_rms, N))

        measured = verify._measure_tone_vrms(x, fs, freq)
        assert measured == pytest.approx(vrms, rel=0.01)

    def test_second_far_away_tone_does_not_bias_estimate(self):
        fs = 10000.0
        freq = 997.0
        vrms = 0.1
        duration = 1.0
        N = int(round(duration * fs))
        t = np.arange(N) / fs
        # A second, unrelated tone well outside the +-2 bin neighbourhood
        # (bin spacing here is 1 Hz, so 200 Hz away is >>2 bins).
        x = (vrms * np.sqrt(2) * np.sin(2 * np.pi * freq * t)
             + 0.5 * np.sqrt(2) * np.sin(2 * np.pi * (freq - 200) * t))

        measured = verify._measure_tone_vrms(x, fs, freq)
        assert measured == pytest.approx(vrms, rel=0.01)


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------

class TestVerdict:

    def test_within_tolerance_is_ok(self):
        r = verify._verdict(0, measured_vrms=0.103, expected_vrms=0.1, tol=0.05)
        assert r['ok'] is True
        assert r['channel'] == 0
        assert r['ratio'] == pytest.approx(1.03)

    def test_exactly_at_tolerance_boundary_is_ok(self):
        # ratio = 1.05 -> abs(ratio - 1) == tol exactly -> ok (uses <=).
        r = verify._verdict(0, measured_vrms=0.105, expected_vrms=0.1, tol=0.05)
        assert r['ok'] is True

    def test_reading_high_gives_positive_error_db(self):
        r = verify._verdict(1, measured_vrms=0.15, expected_vrms=0.1, tol=0.05)
        assert r['ok'] is False
        assert r['error_db'] > 0
        assert r['error_db'] == pytest.approx(20 * np.log10(1.5))

    def test_reading_low_gives_negative_error_db(self):
        r = verify._verdict(2, measured_vrms=0.05, expected_vrms=0.1, tol=0.05)
        assert r['ok'] is False
        assert r['error_db'] < 0
        assert r['error_db'] == pytest.approx(20 * np.log10(0.5))

    def test_zero_measurement_does_not_raise(self):
        # A garbage/absent measurement should fail gracefully, not blow
        # up log10(0).
        r = verify._verdict(0, measured_vrms=0.0, expected_vrms=0.1, tol=0.05)
        assert r['ok'] is False
        assert np.isfinite(r['error_db'])


# ---------------------------------------------------------------------------
# RigolDG1022Z SCPI wrapper (fake pyvisa)
# ---------------------------------------------------------------------------

class _FakeResource:
    """Records every SCPI write in order; no I/O."""

    def __init__(self):
        self.writes = []
        self.timeout = None
        self.closed = False

    def write(self, cmd):
        self.writes.append(cmd)

    def close(self):
        self.closed = True


class _FakeResourceManager:
    def __init__(self, resources=('USB0::0x1AB1::0x0642::DG1ZA000001::INSTR',)):
        self._resources = list(resources)
        self.opened = []

    def list_resources(self):
        return list(self._resources)

    def open_resource(self, resource):
        inst = _FakeResource()
        self.opened.append((resource, inst))
        return inst


class _FakePyvisa:
    """Stands in for the `pyvisa` module: `ResourceManager('@py')`
    returns a `_FakeResourceManager`."""

    def __init__(self, resources=('USB0::0x1AB1::0x0642::DG1ZA000001::INSTR',)):
        self._resources = resources
        self.rm = None

    def ResourceManager(self, backend):
        assert backend == '@py'
        self.rm = _FakeResourceManager(self._resources)
        return self.rm


@pytest.fixture
def fake_pyvisa(monkeypatch):
    fake = _FakePyvisa()
    monkeypatch.setattr(verify, 'pyvisa', fake)
    return fake


class TestRigolDG1022Z:

    def test_missing_pyvisa_raises_clear_import_error(self, monkeypatch):
        monkeypatch.setattr(verify, 'pyvisa', None)
        with pytest.raises(ImportError) as excinfo:
            verify.RigolDG1022Z()
        msg = str(excinfo.value)
        assert 'pip install pyvisa pyvisa-py' in msg

    def test_auto_discovery_picks_first_dg1_match(self, fake_pyvisa):
        fake_pyvisa._resources = (
            'USB0::0x0000::0x0000::SOMETHING::INSTR',
            'USB0::0x1AB1::0x0642::DG1ZA000001::INSTR',
        )
        gen = verify.RigolDG1022Z()
        assert gen.resource == 'USB0::0x1AB1::0x0642::DG1ZA000001::INSTR'

    def test_auto_discovery_raises_with_found_list_when_no_match(self, fake_pyvisa):
        fake_pyvisa._resources = ('USB0::0x0000::0x0000::SOMETHING::INSTR',)
        with pytest.raises(ValueError) as excinfo:
            verify.RigolDG1022Z()
        msg = str(excinfo.value)
        assert 'SOMETHING' in msg

    def test_explicit_resource_bypasses_auto_discovery(self, fake_pyvisa):
        gen = verify.RigolDG1022Z(resource='USB0::MY::EXPLICIT::INSTR')
        assert gen.resource == 'USB0::MY::EXPLICIT::INSTR'

    def test_set_sine_writes_expected_scpi_sequence(self, fake_pyvisa):
        gen = verify.RigolDG1022Z()
        inst = gen._inst
        inst.writes.clear()
        gen.set_sine(997.0, 0.1)
        assert inst.writes == [
            ':SOUR1:FUNC SIN',
            ':OUTP1:LOAD INF',
            ':SOUR1:VOLT:UNIT VRMS',
            ':SOUR1:VOLT 0.1',
            ':SOUR1:VOLT:OFFS 0',
            ':SOUR1:FREQ 997.0',
        ]

    def test_set_sine_respects_channel_argument(self, fake_pyvisa):
        gen = verify.RigolDG1022Z()
        inst = gen._inst
        inst.writes.clear()
        gen.set_sine(1000.0, 0.5, channel=2)
        assert inst.writes[0] == ':SOUR2:FUNC SIN'
        assert all(':SOUR2' in w or ':OUTP2' in w for w in inst.writes)

    def test_output_on_writes_stat_on(self, fake_pyvisa):
        gen = verify.RigolDG1022Z()
        inst = gen._inst
        inst.writes.clear()
        gen.output(True)
        assert inst.writes == [':OUTP1:STAT ON']

    def test_output_off_writes_stat_off(self, fake_pyvisa):
        gen = verify.RigolDG1022Z()
        inst = gen._inst
        inst.writes.clear()
        gen.output(False)
        assert inst.writes == [':OUTP1:STAT OFF']

    def test_close_returns_to_local_and_closes(self, fake_pyvisa):
        gen = verify.RigolDG1022Z()
        inst = gen._inst
        gen.close()
        assert ':SYST:LOCal' in inst.writes
        assert inst.closed is True

    def test_context_manager_switches_output_off_on_normal_exit(self, fake_pyvisa):
        with verify.RigolDG1022Z() as gen:
            inst = gen._inst
            gen.set_sine(997.0, 0.1)
            gen.output(True)
        assert inst.writes[-2:] == [':OUTP1:STAT OFF', ':SYST:LOCal']
        assert inst.closed is True

    def test_context_manager_switches_output_off_even_after_exception(self, fake_pyvisa):
        inst_holder = {}
        with pytest.raises(RuntimeError):
            with verify.RigolDG1022Z() as gen:
                inst_holder['inst'] = gen._inst
                gen.output(True)
                raise RuntimeError('boom')
        inst = inst_holder['inst']
        assert ':OUTP1:STAT OFF' in inst.writes
        assert inst.writes[-2:] == [':OUTP1:STAT OFF', ':SYST:LOCal']
        assert inst.closed is True


# ---------------------------------------------------------------------------
# verify_input_scaling: loopback plumbing
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_streams_state():
    """Reset module-level recorder globals so state doesn't leak between
    tests via `streams.REC` (same pattern as test_acquisition_mock.py)."""
    streams.REC = None
    streams.REC_MOCK = None
    yield
    if streams.REC is not None:
        try:
            streams.REC.end_stream()
        except Exception:
            pass
    streams.REC = None
    streams.REC_MOCK = None


def _mock_settings(**kwargs):
    kwargs.setdefault('device_driver', 'mock')
    kwargs.setdefault('output_device_driver', 'mock')
    kwargs.setdefault('channels', 2)
    kwargs.setdefault('fs', 10000)
    kwargs.setdefault('chunk_size', 500)
    kwargs.setdefault('num_chunks', 4)
    kwargs.setdefault('output_channels', 1)
    return options.MySettings(**kwargs)


class TestVerifyInputScalingLoopbackMock:

    def test_runs_end_to_end_and_fails_gracefully_on_garbage_input(self, capsys):
        # The mock backend fills captures with its own deterministic
        # per-channel sine (100/200 Hz), unrelated to our commanded
        # 997 Hz tone -- so this must NOT raise, and must correctly
        # report ok=False rather than pretending success.
        s = _mock_settings()
        results = dvma.verify_input_scaling(
            s, source='loopback', freq=997.0, level_vrms=0.1, duration=0.05)

        assert isinstance(results, list)
        assert len(results) == s.channels
        for r in results:
            assert r['ok'] is False
            assert set(r.keys()) == {
                'channel', 'measured_vrms', 'expected_vrms', 'ratio',
                'error_db', 'ok',
            }

        out = capsys.readouterr().out
        assert 'FAIL' in out
        assert 'check the gain setting' in out

    def test_returns_all_channels_by_default(self, capsys):
        s = _mock_settings(channels=3)
        results = dvma.verify_input_scaling(
            s, source='loopback', freq=997.0, level_vrms=0.1, duration=0.05)
        assert [r['channel'] for r in results] == [0, 1, 2]

    def test_channels_argument_restricts_check(self, capsys):
        s = _mock_settings(channels=3)
        results = dvma.verify_input_scaling(
            s, source='loopback', freq=997.0, level_vrms=0.1, duration=0.05,
            channels=[1])
        assert [r['channel'] for r in results] == [1]

    def test_freq_too_close_to_nyquist_raises(self):
        s = _mock_settings(fs=2000)
        with pytest.raises(ValueError):
            dvma.verify_input_scaling(s, source='loopback', freq=997.0,
                                      level_vrms=0.1, duration=0.05)

    def test_peak_exceeding_output_vmax_raises(self):
        # 'mock' output_vmax() falls through to output_VmaxSC (it is
        # only 'nidaq' that reads output_VmaxNI) -- set it low to force
        # the peak guard.
        s = options.MySettings(device_driver='mock', output_device_driver='mock',
                               channels=1, fs=10000, output_channels=1,
                               output_VmaxSC=0.01)
        with pytest.raises(ValueError, match='output_vmax'):
            dvma.verify_input_scaling(s, source='loopback', freq=997.0,
                                      level_vrms=1.0, duration=0.05)

    def test_unrecognised_string_source_raises(self):
        s = _mock_settings()
        with pytest.raises(ValueError):
            dvma.verify_input_scaling(s, source='not-a-real-source')

    def test_source_without_expected_methods_raises_typeerror(self):
        s = _mock_settings()
        with pytest.raises(TypeError):
            dvma.verify_input_scaling(s, source=object())


class TestVerifyInputScalingSoundcardWarning:

    def test_soundcard_loopback_prints_uncalibrated_warning(self, monkeypatch, capsys):
        # Avoid touching real hardware: stub out acquisition.log_data
        # entirely and hand back a synthetic capture so only the
        # warning-emission logic (gated on output_device_driver) is
        # under test.
        s = options.MySettings(device_driver='mock', output_device_driver='soundcard',
                               channels=1, fs=10000, output_channels=1)

        def fake_log_data(settings, output=None):
            n = int(round(settings.stored_time * settings.fs))
            t = np.arange(n) / settings.fs
            x = 0.1 * np.sqrt(2) * np.sin(2 * np.pi * 997.0 * t)
            td = dvma.TimeData(t, x[:, None], settings)
            ds = dvma.DataSet()
            ds.add_to_dataset(td)
            return ds

        monkeypatch.setattr(verify.acquisition, 'log_data', fake_log_data)

        dvma.verify_input_scaling(s, source='loopback', freq=997.0,
                                  level_vrms=0.1, duration=0.05)

        out = capsys.readouterr().out
        assert 'WARNING' in out
        assert 'sound card' in out.lower()

    def test_no_warning_on_nidaq_loopback(self, monkeypatch, capsys):
        s = options.MySettings(device_driver='mock', output_device_driver='nidaq',
                               channels=1, fs=10000, output_channels=1,
                               output_VmaxNI=5.0)

        def fake_log_data(settings, output=None):
            n = int(round(settings.stored_time * settings.fs))
            t = np.arange(n) / settings.fs
            x = 0.1 * np.sqrt(2) * np.sin(2 * np.pi * 997.0 * t)
            td = dvma.TimeData(t, x[:, None], settings)
            ds = dvma.DataSet()
            ds.add_to_dataset(td)
            return ds

        monkeypatch.setattr(verify.acquisition, 'log_data', fake_log_data)

        dvma.verify_input_scaling(s, source='loopback', freq=997.0,
                                  level_vrms=0.1, duration=0.05)

        out = capsys.readouterr().out
        assert 'WARNING' not in out


# ---------------------------------------------------------------------------
# verify_input_scaling: external-source (Rigol-like) plumbing
# ---------------------------------------------------------------------------

class _FakeSource:
    def __init__(self):
        self.calls = []
        self.is_on = False

    def set_sine(self, freq_hz, vrms):
        self.calls.append(('set_sine', freq_hz, vrms))

    def output(self, on):
        self.calls.append(('output', on))
        self.is_on = bool(on)


class TestVerifyInputScalingExternalSource:

    def test_commands_source_and_switches_output_off_after(self, monkeypatch):
        s = options.MySettings(device_driver='mock', channels=1, fs=10000)

        def fake_log_data(settings, output=None):
            assert output is None  # nothing played by pydvma on this path
            n = int(round(settings.stored_time * settings.fs))
            t = np.arange(n) / settings.fs
            x = 0.1 * np.sqrt(2) * np.sin(2 * np.pi * 997.0 * t)
            td = dvma.TimeData(t, x[:, None], settings)
            ds = dvma.DataSet()
            ds.add_to_dataset(td)
            return ds

        monkeypatch.setattr(verify.acquisition, 'log_data', fake_log_data)
        monkeypatch.setattr(verify.time, 'sleep', lambda _s: None)

        source = _FakeSource()
        results = dvma.verify_input_scaling(
            s, source=source, freq=997.0, level_vrms=0.1, duration=0.05)

        assert source.calls[0] == ('set_sine', 997.0, 0.1)
        assert ('output', True) in source.calls
        assert source.calls[-1] == ('output', False)
        assert source.is_on is False
        assert len(results) == 1
        assert results[0]['ok'] is True

    def test_source_output_switched_off_even_if_capture_raises(self, monkeypatch):
        s = options.MySettings(device_driver='mock', channels=1, fs=10000)

        def raising_log_data(settings, output=None):
            raise RuntimeError('capture boom')

        monkeypatch.setattr(verify.acquisition, 'log_data', raising_log_data)
        monkeypatch.setattr(verify.time, 'sleep', lambda _s: None)

        source = _FakeSource()
        with pytest.raises(RuntimeError):
            dvma.verify_input_scaling(s, source=source, freq=997.0,
                                      level_vrms=0.1, duration=0.05)

        assert source.calls[-1] == ('output', False)
