"""A Windows audio endpoint that opens but never delivers (round 14d).

Measured three times on Scarlett 2i2 4th Gen interfaces (2026-09-04 lab
and office, 2026-09-10 lab): every NEW stream on the device opened and
started normally but delivered no callback at all — on MME, DirectSound,
WDM-KS and WASAPI shared alike — until the device's WASAPI endpoint was
opened in EXCLUSIVE mode, streamed for a moment and closed, after which
every host API delivered again. `Recorder.init_stream` now waits
`FIRST_SAMPLES_GRACE_S` for the first callback and, on silence, performs
that exclusive cycle on the WASAPI twin and reopens the live stream,
reporting the outcome in ``wedge_note``.

The sounddevice stand-in here models the wedge: shared-mode streams
deliver callbacks only while ``fake.wedged`` is False, and an
exclusive-mode open clears the flag.
"""
from types import SimpleNamespace

import numpy as np
import pytest

from pydvma import options, streams


def _device(name, n_in, hostapi, default_fs=48000.0):
    return {'name': name, 'max_input_channels': n_in, 'max_output_channels': 0,
            'hostapi': hostapi, 'default_samplerate': default_fs}


def _fake_sd(wedged=True, with_wasapi=True, exclusive_clears=True):
    """``with_wasapi=False`` models a Windows sounddevice (it still has
    ``WasapiSettings``) whose enumeration holds no WASAPI twin of the
    device, so there is nothing to reset through."""
    devices = [
        _device('Analogue 1 + 2 (Focusrite USB A', 4, 0),      # MME, truncated name
        _device('Analogue 1 + 2 (Focusrite USB Audio)', 2, 1),  # WASAPI
    ]
    hostapis = [{'name': 'MME'}, {'name': 'Windows WASAPI' if with_wasapi else 'Windows DirectSound'}]

    class WasapiSettings:
        def __init__(self, exclusive=False):
            self.exclusive = exclusive

    class FakeInputStream:
        def __init__(self, **kw):
            self.kw = kw
            self.active = False
            fake.opened.append(self)

        @property
        def exclusive(self):
            es = self.kw.get('extra_settings')
            return bool(es is not None and getattr(es, 'exclusive', False))

        def start(self):
            self.active = True
            if self.exclusive:
                if exclusive_clears:
                    fake.wedged = False
                return
            if not fake.wedged:
                cb = self.kw['callback']
                n, ch = int(self.kw['blocksize']), int(self.kw['channels'])
                for _ in range(3):
                    cb(np.full((n, ch), 0.01, dtype='float32'), n, None, None)

        def stop(self):
            self.active = False

        def close(self):
            self.active = False

        @property
        def samplerate(self):
            return self.kw.get('samplerate')

    def query_devices(index=None, kind=None):
        return devices if index is None else devices[int(index)]

    fake = SimpleNamespace(
        query_devices=query_devices,
        query_hostapis=lambda: hostapis,
        default=SimpleNamespace(device=[0, 0]),
        PortAudioError=Exception,
        InputStream=FakeInputStream,
        Stream=FakeInputStream,
        opened=[],
        wedged=wedged,
        WasapiSettings=WasapiSettings,
    )
    return fake


@pytest.fixture
def bench(monkeypatch):
    monkeypatch.setattr(streams, 'FIRST_SAMPLES_GRACE_S', 0.05)
    monkeypatch.setattr(streams._coreaudio, 'available', lambda: False)
    monkeypatch.setattr(streams, '_volume_backend', lambda: None)

    def make(**kw):
        fake = _fake_sd(**kw)
        monkeypatch.setattr(streams, 'sd', fake)
        s = options.MySettings(device_driver='soundcard', device_index=0, channels=2,
                               fs=48000, chunk_size=100, num_chunks=4, stored_time=0.1)
        return fake, streams.Recorder(s), s
    return make


def _shared_opens(fake):
    return [st for st in fake.opened if not st.exclusive]


def _exclusive_opens(fake):
    return [st for st in fake.opened if st.exclusive]


def test_silent_stream_is_cleared_by_a_wasapi_exclusive_cycle(bench, capsys):
    fake, rec, s = bench(wedged=True)
    rec.init_stream(s)
    assert rec.osc_samples_seen > 0                       # samples flow now
    ex = _exclusive_opens(fake)
    assert len(ex) == 1 and ex[0].kw['device'] == 1       # the WASAPI twin, by name
    assert ex[0].kw['samplerate'] == 48000.0 and not ex[0].active
    assert len(_shared_opens(fake)) == 2                  # closed and reopened
    assert not _shared_opens(fake)[0].active and _shared_opens(fake)[1].active
    assert 'cleared' in rec.wedge_note and 'exclusive' in rec.wedge_note
    assert 'note:' in capsys.readouterr().out


def test_healthy_stream_is_left_alone(bench):
    fake, rec, s = bench(wedged=False)
    rec.init_stream(s)
    assert rec.osc_samples_seen > 0
    assert len(fake.opened) == 1 and not _exclusive_opens(fake)
    assert rec.wedge_note is None


def test_silence_without_a_wasapi_twin_is_only_reported(bench, capsys):
    fake, rec, s = bench(wedged=True, with_wasapi=False)
    rec.init_stream(s)
    assert rec.osc_samples_seen == 0
    assert len(fake.opened) == 1                          # nothing to reset through
    assert 'no WASAPI' in rec.wedge_note
    assert 'WARNING' in capsys.readouterr().out


def test_still_silent_after_the_reset_is_reported(bench, capsys):
    fake, rec, s = bench(wedged=True, exclusive_clears=False)
    rec.init_stream(s)
    assert rec.osc_samples_seen == 0
    assert len(_exclusive_opens(fake)) == 1 and len(_shared_opens(fake)) == 2
    assert 'still none' in rec.wedge_note
    assert 'WARNING' in capsys.readouterr().out


def test_wasapi_twin_lookup_matches_truncated_mme_names(bench):
    fake, _rec, _s = bench()
    assert streams._wasapi_input_twin('Analogue 1 + 2 (Focusrite USB A') == 1
    assert streams._wasapi_input_twin('Analogue 1 + 2 (Focusrite USB Audio)') == 1
    assert streams._wasapi_input_twin('Something else') is None
    assert streams._wasapi_input_twin('') is None
