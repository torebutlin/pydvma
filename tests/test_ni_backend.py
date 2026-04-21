"""Unit tests for pydvma._ni_backend.

These run on any machine without NI hardware or nidaqmx installed — they
exercise the pure-Python device enumeration and channel-string construction
with fake Device objects.

We load `_ni_backend` directly from its path to avoid executing
`pydvma/__init__.py`, which would require every runtime dependency
(peakutils, pyqtgraph, etc.) just to run these tests.
"""
import importlib.util
from pathlib import Path

import pytest


_spec = importlib.util.spec_from_file_location(
    '_ni_backend',
    Path(__file__).resolve().parent.parent / 'pydvma' / '_ni_backend.py',
)
_ni = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ni)


class _FakeEnumValue(object):
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return isinstance(other, _FakeEnumValue) and self.name == other.name

    def __hash__(self):
        return hash(self.name)


FAKE_CHASSIS = _FakeEnumValue('C_DAQ_CHASSIS')
FAKE_USB = _FakeEnumValue('USB_DAQ')


class _FakeProductCategory(object):
    C_DAQ_CHASSIS = FAKE_CHASSIS


class FakePhysChan(object):
    def __init__(self, name):
        self.name = name


class FakeDevice(object):
    def __init__(self, name, product_type, ai=0, ao=0, chassis=False, modules=None):
        self.name = name
        self.product_type = product_type
        self.product_category = FAKE_CHASSIS if chassis else FAKE_USB
        self.ai_physical_chans = [FakePhysChan('%s/ai%d' % (name, i)) for i in range(ai)]
        self.ao_physical_chans = [FakePhysChan('%s/ao%d' % (name, i)) for i in range(ao)]
        self.chassis_module_devices = list(modules) if modules else []


class FakeSystem(object):
    def __init__(self, devices):
        self.devices = list(devices)


@pytest.fixture
def patch_ni(monkeypatch):
    """Make `_ni_backend` behave as if nidaqmx were installed with our fake
    ProductCategory and no real system connection."""
    monkeypatch.setattr(_ni, 'ProductCategory', _FakeProductCategory)
    monkeypatch.setattr(_ni, 'nidaqmx', object())


def _usb_entry(name='Dev1', product_type='USB-6003', ai=8, ao=2):
    return {
        'name': name, 'product_type': product_type,
        'is_chassis': False, 'ai_channel_count': ai, 'ao_channel_count': ao,
        'module_names': [], 'module_ai_counts': {}, 'module_ao_counts': {},
    }


def _chassis_entry(name, product_type, modules):
    """modules: list of (name, ai_count, ao_count) tuples in slot order."""
    return {
        'name': name, 'product_type': product_type, 'is_chassis': True,
        'ai_channel_count': sum(m[1] for m in modules),
        'ao_channel_count': sum(m[2] for m in modules),
        'module_names': [m[0] for m in modules],
        'module_ai_counts': {m[0]: m[1] for m in modules},
        'module_ao_counts': {m[0]: m[2] for m in modules},
    }


class TestEnumerateDevices:

    def test_empty_system(self, patch_ni):
        assert _ni.enumerate_devices(system=FakeSystem([])) == []

    def test_standalone_usb_devices(self, patch_ni):
        dev1 = FakeDevice('Dev1', 'USB-6003', ai=8, ao=2)
        dev2 = FakeDevice('Dev2', 'USB-6212', ai=16, ao=2)
        entries = _ni.enumerate_devices(system=FakeSystem([dev1, dev2]))
        assert [e['name'] for e in entries] == ['Dev1', 'Dev2']
        assert entries[0]['product_type'] == 'USB-6003'
        assert entries[0]['is_chassis'] is False
        assert entries[0]['ai_channel_count'] == 8
        assert entries[0]['ao_channel_count'] == 2
        assert entries[1]['ai_channel_count'] == 16

    def test_cdaq_chassis_collapses_modules(self, patch_ni):
        mod1 = FakeDevice('cDAQ1Mod1', 'NI 9215', ai=4, ao=0)
        mod3 = FakeDevice('cDAQ1Mod3', 'NI 9263', ai=0, ao=4)
        chassis = FakeDevice('cDAQ1', 'cDAQ-9185', chassis=True, modules=[mod1, mod3])
        entries = _ni.enumerate_devices(system=FakeSystem([chassis, mod1, mod3]))
        assert len(entries) == 1
        entry = entries[0]
        assert entry['name'] == 'cDAQ1'
        assert entry['is_chassis'] is True
        assert entry['ai_channel_count'] == 4
        assert entry['ao_channel_count'] == 4
        assert entry['module_names'] == ['cDAQ1Mod1', 'cDAQ1Mod3']
        assert entry['module_ai_counts'] == {'cDAQ1Mod1': 4, 'cDAQ1Mod3': 0}
        assert entry['module_ao_counts'] == {'cDAQ1Mod1': 0, 'cDAQ1Mod3': 4}

    def test_mixed_usb_and_chassis(self, patch_ni):
        usb = FakeDevice('Dev1', 'USB-6003', ai=8, ao=2)
        mod = FakeDevice('cDAQ1Mod1', 'NI 9215', ai=4)
        chassis = FakeDevice('cDAQ1', 'cDAQ-9185', chassis=True, modules=[mod])
        entries = _ni.enumerate_devices(system=FakeSystem([usb, chassis, mod]))
        assert [e['name'] for e in entries] == ['Dev1', 'cDAQ1']

    def test_returns_empty_when_nidaqmx_missing(self, monkeypatch):
        monkeypatch.setattr(_ni, 'nidaqmx', None)
        assert _ni.enumerate_devices() == []


class TestBuildAIChannelString:

    def test_usb_single_channel(self):
        assert _ni.build_ai_channel_string(_usb_entry(), 1) == 'Dev1/ai0'

    def test_usb_multi_channel(self):
        assert _ni.build_ai_channel_string(_usb_entry(), 4) == 'Dev1/ai0:3'

    def test_explicit_spec_overrides(self):
        assert (
            _ni.build_ai_channel_string(_usb_entry(), 4, explicit_spec='Dev1/ai2:5')
            == 'Dev1/ai2:5'
        )

    def test_chassis_single_module(self):
        entry = _chassis_entry('cDAQ1', 'cDAQ-9185',
                               [('cDAQ1Mod1', 4, 0)])
        assert _ni.build_ai_channel_string(entry, 4) == 'cDAQ1Mod1/ai0:3'

    def test_chassis_spans_modules_all_channels(self):
        entry = _chassis_entry('cDAQ1', 'cDAQ-9189',
                               [('cDAQ1Mod1', 4, 0), ('cDAQ1Mod2', 4, 0)])
        assert (
            _ni.build_ai_channel_string(entry, 8)
            == 'cDAQ1Mod1/ai0:3,cDAQ1Mod2/ai0:3'
        )

    def test_chassis_partial_across_modules(self):
        entry = _chassis_entry('cDAQ1', 'cDAQ-9189',
                               [('cDAQ1Mod1', 4, 0), ('cDAQ1Mod2', 4, 0)])
        assert (
            _ni.build_ai_channel_string(entry, 5)
            == 'cDAQ1Mod1/ai0:3,cDAQ1Mod2/ai0'
        )

    def test_chassis_skips_zero_ai_modules(self):
        entry = _chassis_entry('cDAQ1', 'cDAQ-9185',
                               [('cDAQ1Mod1', 4, 0), ('cDAQ1Mod3', 0, 4)])
        assert _ni.build_ai_channel_string(entry, 4) == 'cDAQ1Mod1/ai0:3'

    def test_over_request_raises(self):
        entry = _usb_entry(ai=2)
        with pytest.raises(ValueError):
            _ni.build_ai_channel_string(entry, 4)

    def test_zero_or_negative_raises(self):
        with pytest.raises(ValueError):
            _ni.build_ai_channel_string(_usb_entry(), 0)


class TestBuildAOChannelString:

    def test_usb_multi_channel(self):
        assert _ni.build_ao_channel_string(_usb_entry(), 2) == 'Dev1/ao0:1'

    def test_chassis_skips_zero_ao_modules(self):
        entry = _chassis_entry('cDAQ1', 'cDAQ-9185',
                               [('cDAQ1Mod1', 4, 0), ('cDAQ1Mod3', 0, 4)])
        assert _ni.build_ao_channel_string(entry, 2) == 'cDAQ1Mod3/ao0:1'


class TestSyncSupport:

    def test_cdaq_supports_sync(self):
        entry = _chassis_entry('cDAQ1', 'cDAQ-9185', [('cDAQ1Mod1', 4, 0)])
        assert _ni.supports_hw_ao_sync(entry) is True

    def test_usb_6212_supports_sync(self):
        assert _ni.supports_hw_ao_sync(_usb_entry('Dev2', 'USB-6212', ai=16, ao=2)) is True

    @pytest.mark.parametrize('product_type', [
        'USB-6001', 'USB-6002', 'USB-6003', 'USB-6008', 'USB-6009',
    ])
    def test_usb_600x_does_not_support_sync(self, product_type):
        assert _ni.supports_hw_ao_sync(_usb_entry('Dev1', product_type, ai=8, ao=2)) is False


class TestAISampleClockSource:

    def test_usb(self):
        entry = _usb_entry('Dev2', 'USB-6212', ai=16, ao=2)
        assert _ni.ai_sample_clock_source(entry) == '/Dev2/ai/SampleClock'

    def test_chassis_uses_first_ai_bearing_module(self):
        # Slot order Mod3 (AO-only) then Mod1 (AI): expect Mod1 chosen.
        entry = _chassis_entry('cDAQ1', 'cDAQ-9185',
                               [('cDAQ1Mod3', 0, 4), ('cDAQ1Mod1', 4, 0)])
        assert _ni.ai_sample_clock_source(entry) == '/cDAQ1Mod1/ai/SampleClock'

    def test_chassis_without_ai_returns_none(self):
        entry = _chassis_entry('cDAQ1', 'cDAQ-9185', [('cDAQ1Mod3', 0, 4)])
        assert _ni.ai_sample_clock_source(entry) is None
