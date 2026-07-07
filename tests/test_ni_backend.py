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


# Real nidaqmx (observed on 2026 Q2) spells the chassis category
# `COMPACT_DAQ_CHASSIS`; we also accept `C_DAQ_CHASSIS` for forward-compat.
FAKE_CHASSIS = _FakeEnumValue('COMPACT_DAQ_CHASSIS')
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

    def test_accepts_legacy_chassis_enum_name(self, patch_ni):
        # Older / alternate nidaqmx builds may expose `C_DAQ_CHASSIS`
        # instead of `COMPACT_DAQ_CHASSIS`. Both must be treated as chassis.
        mod = FakeDevice('cDAQ1Mod1', 'NI 9215', ai=4)
        chassis = FakeDevice('cDAQ1', 'cDAQ-9185', chassis=True, modules=[mod])
        chassis.product_category = _FakeEnumValue('C_DAQ_CHASSIS')
        entries = _ni.enumerate_devices(system=FakeSystem([chassis, mod]))
        assert len(entries) == 1 and entries[0]['is_chassis'] is True

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


class TestAIChannelModuleMap:

    def test_usb_all_same_device(self):
        assert _ni.ai_channel_module_map(_usb_entry(), 3) == [
            'Dev1', 'Dev1', 'Dev1',
        ]

    def test_chassis_single_module(self):
        entry = _chassis_entry('cDAQ1', 'cDAQ-9185',
                               [('cDAQ1Mod1', 4, 0)])
        assert _ni.ai_channel_module_map(entry, 3) == [
            'cDAQ1Mod1', 'cDAQ1Mod1', 'cDAQ1Mod1',
        ]

    def test_chassis_spans_two_modules(self):
        # Mirrors the lab rig: two 4-ch AI modules either side of a
        # middle AO module. Channels 0-3 -> Mod1, 4-7 -> Mod4.
        entry = _chassis_entry('cDAQ1', 'cDAQ-9174',
                               [('cDAQ1Mod1', 4, 0),
                                ('cDAQ1Mod2', 0, 2),
                                ('cDAQ1Mod4', 4, 0)])
        assert _ni.ai_channel_module_map(entry, 8) == (
            ['cDAQ1Mod1'] * 4 + ['cDAQ1Mod4'] * 4
        )

    def test_chassis_partial_into_second_module(self):
        entry = _chassis_entry('cDAQ1', 'cDAQ-9174',
                               [('cDAQ1Mod1', 4, 0),
                                ('cDAQ1Mod2', 0, 2),
                                ('cDAQ1Mod4', 4, 0)])
        # 6 channels: all of Mod1 then the first two of Mod4.
        assert _ni.ai_channel_module_map(entry, 6) == (
            ['cDAQ1Mod1'] * 4 + ['cDAQ1Mod4'] * 2
        )

    def test_consistent_with_channel_string(self):
        # The map's module order must agree with the channel string the
        # AI task is actually built from.
        entry = _chassis_entry('cDAQ1', 'cDAQ-9174',
                               [('cDAQ1Mod1', 4, 0),
                                ('cDAQ1Mod2', 0, 2),
                                ('cDAQ1Mod4', 4, 0)])
        mapped = _ni.ai_channel_module_map(entry, 5)
        chan_str = _ni.build_ai_channel_string(entry, 5)
        # First module in the map is the first fragment's device.
        assert mapped[0] == chan_str.split(',')[0].split('/')[0]
        assert mapped[-1] == chan_str.split(',')[-1].split('/')[0]

    def test_over_request_raises(self):
        with pytest.raises(ValueError):
            _ni.ai_channel_module_map(_usb_entry(ai=2), 4)

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            _ni.ai_channel_module_map(_usb_entry(), 0)


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

    def test_chassis_returns_none(self):
        # Per-module AI sample clocks are not routable as AO sources on
        # cDAQ; callers fall back to the default (chassis timebase).
        entry = _chassis_entry('cDAQ1', 'cDAQ-9185',
                               [('cDAQ1Mod1', 4, 0), ('cDAQ1Mod3', 0, 4)])
        assert _ni.ai_sample_clock_source(entry) is None


# ---- device_capabilities / entry_capabilities ----------------------------
#
# These exercise the Wave-C capability probe against fake devices exposing
# the real nidaqmx Device / PhysicalChannel property names (verified
# against nidaqmx-python's device.py / physical_channel.py):
#   ai_max_multi_chan_rate, ai_max_single_chan_rate, ai_min_rate,
#   ao_max_rate, ao_min_rate, ai_simultaneous_sampling_supported,
#   ai_current_int_excit_discrete_vals, and (per physical channel)
#   ai_term_cfgs.


class _FakeTermCfg(object):
    """Stand-in for an nidaqmx TerminalConfiguration enum member."""
    def __init__(self, name):
        self.name = name


class _FakeCapPhysChan(object):
    def __init__(self, name, term_cfgs):
        self.name = name
        self.ai_term_cfgs = list(term_cfgs)


class FakeCapDevice(object):
    """Fake nidaqmx Device exposing the capability properties.

    Defaults model an NI 9234-class DSA AI module (simultaneous
    sampling, 2 mA IEPE, pseudo-differential only).
    """
    def __init__(self, name, product_type='NI 9234', ai=4, ao=0,
                 ai_max_multi=51200.0, ai_max_single=51200.0, ai_min=1000.0,
                 ao_max=None, ao_min=None, simultaneous=True,
                 iepe_vals=(0.0, 0.002), term_cfg_names=('PSEUDO_DIFF',),
                 ai_rngs=(-5.0, 5.0), ao_rngs=()):
        self.name = name
        self.product_type = product_type
        self.ai_max_multi_chan_rate = ai_max_multi
        self.ai_max_single_chan_rate = ai_max_single
        self.ai_min_rate = ai_min
        self.ao_max_rate = ao_max
        self.ao_min_rate = ao_min
        self.ai_simultaneous_sampling_supported = simultaneous
        self.ai_current_int_excit_discrete_vals = list(iepe_vals)
        # flat [min, max, min, max, ...] like the real ai/ao_voltage_rngs
        self.ai_voltage_rngs = list(ai_rngs)
        self.ao_voltage_rngs = list(ao_rngs)
        term = [_FakeTermCfg(n) for n in term_cfg_names]
        self.ai_physical_chans = [
            _FakeCapPhysChan('%s/ai%d' % (name, i), term) for i in range(ai)
        ]
        self.ao_physical_chans = [
            FakePhysChan('%s/ao%d' % (name, i)) for i in range(ao)
        ]


class _MissingAxisDevice(object):
    """AO-only module: every ``ai_*`` property raises (mimics DAQmx
    -200197 'requested property not supported'), like the NI 9260."""
    name = 'AOonly'
    product_type = 'NI 9260'
    ai_physical_chans = []

    def __init__(self):
        self.ao_physical_chans = [FakePhysChan('AOonly/ao0'),
                                  FakePhysChan('AOonly/ao1')]
        self.ao_max_rate = 51200.0
        self.ao_min_rate = 1613.0

    @property
    def ai_max_multi_chan_rate(self):
        raise RuntimeError('DAQmx -200197')

    @property
    def ai_max_single_chan_rate(self):
        raise RuntimeError('DAQmx -200197')

    @property
    def ai_min_rate(self):
        raise RuntimeError('DAQmx -200197')

    @property
    def ai_simultaneous_sampling_supported(self):
        raise RuntimeError('DAQmx -200197')

    @property
    def ai_current_int_excit_discrete_vals(self):
        raise RuntimeError('DAQmx -200197')


class TestDeviceCapabilities:

    def test_dsa_ai_module(self):
        dev = FakeCapDevice('cDAQ1Mod1')  # 9234-like defaults
        caps = _ni.device_capabilities('cDAQ1Mod1', device=dev)
        assert caps['ai_max_rate'] == 51200.0
        assert caps['ai_max_single_chan_rate'] == 51200.0
        assert caps['ai_min_rate'] == 1000.0
        assert caps['simultaneous'] is True
        assert caps['iepe_supported'] is True
        assert caps['iepe_currents'] == [0.002]      # 0.0 dropped
        assert caps['terminal_configs'] == ['DAQmx_Val_PseudoDiff']
        assert caps['ao_supported'] is False         # AI-only module
        assert caps['ai_vmax'] == 5.0                # 9234 fixed ±5 V
        assert caps['ao_vmax'] is None               # no AO axis

    def test_ai_max_rate_falls_back_to_single(self):
        dev = FakeCapDevice('Dev1', ai_max_multi=None, ai_max_single=100000.0)
        caps = _ni.device_capabilities('Dev1', device=dev)
        assert caps['ai_max_rate'] == 100000.0

    def test_multiplexed_usb_no_iepe(self):
        dev = FakeCapDevice(
            'Dev1', product_type='USB-6003', ai=8, ao=2,
            ai_max_multi=100000.0, ai_max_single=100000.0, ai_min=0.0,
            simultaneous=False, iepe_vals=(), term_cfg_names=('RSE', 'DIFF'),
        )
        caps = _ni.device_capabilities('Dev1', device=dev)
        assert caps['simultaneous'] is False
        assert caps['iepe_supported'] is False
        assert caps['iepe_currents'] == []
        assert caps['terminal_configs'] == ['DAQmx_Val_RSE', 'DAQmx_Val_Diff']
        assert caps['ao_supported'] is True          # 2 AO channels

    def test_missing_ai_axis_degrades_to_none(self):
        # An AO-only module must not raise — the _safe guard swallows the
        # -200197 and reports None / empty for the absent AI axis.
        caps = _ni.device_capabilities('AOonly', device=_MissingAxisDevice())
        assert caps['ai_max_rate'] is None
        assert caps['ai_min_rate'] is None
        assert caps['simultaneous'] is None
        assert caps['iepe_supported'] is False
        assert caps['terminal_configs'] == []
        assert caps['ao_supported'] is True
        assert caps['ao_max_rate'] == 51200.0

    def test_requires_nidaqmx_when_no_device_given(self, monkeypatch):
        monkeypatch.setattr(_ni, 'nidaqmx', None)
        with pytest.raises(RuntimeError):
            _ni.device_capabilities('Dev1')


class TestEntryCapabilities:

    def test_standalone_device(self):
        entry = _usb_entry('Dev1', 'USB-6212', ai=16, ao=2)
        dev = FakeCapDevice(
            'Dev1', product_type='USB-6212', ai=16, ao=2,
            ai_max_multi=400000.0, ai_max_single=400000.0, ai_min=0.0,
            ao_max=250000.0, ao_min=0.0, simultaneous=False,
            iepe_vals=(), term_cfg_names=('RSE', 'NRSE', 'DIFF'),
        )
        caps = _ni.entry_capabilities(entry, resolver=lambda n: dev)
        assert caps['ai_max_rate'] == 400000.0
        assert caps['ao_max_rate'] == 250000.0
        assert caps['simultaneous'] is False
        assert caps['ao_supported'] is True

    def test_chassis_merges_ai_and_ao_modules(self):
        # cDAQ-9174: Mod1 = 9234 AI (IEPE, simultaneous, pseudo-diff);
        # Mod2 = 9260 AO. Chassis-level caps come from the modules.
        entry = _chassis_entry(
            'cDAQ1', 'cDAQ-9174',
            [('cDAQ1Mod1', 4, 0), ('cDAQ1Mod2', 0, 2)],
        )
        ai_dev = FakeCapDevice('cDAQ1Mod1')  # 9234-like
        ao_dev = FakeCapDevice(
            'cDAQ1Mod2', product_type='NI 9260', ai=0, ao=2,
            ai_max_multi=None, ai_max_single=None, ai_min=None,
            ao_max=51200.0, ao_min=1613.0, simultaneous=True,
            iepe_vals=(), term_cfg_names=(),
            ai_rngs=(), ao_rngs=(-4.242641, 4.242641),
        )
        resolver = {'cDAQ1Mod1': ai_dev, 'cDAQ1Mod2': ao_dev}.__getitem__
        caps = _ni.entry_capabilities(entry, resolver=resolver)
        # AI fields sourced from the AI module...
        assert caps['ai_max_rate'] == 51200.0
        assert caps['simultaneous'] is True
        assert caps['iepe_supported'] is True
        assert caps['iepe_currents'] == [0.002]
        assert caps['terminal_configs'] == ['DAQmx_Val_PseudoDiff']
        assert caps['ai_vmax'] == 5.0
        # ...AO fields from the AO module.
        assert caps['ao_max_rate'] == 51200.0
        assert caps['ao_min_rate'] == 1613.0
        assert caps['ao_supported'] is True
        assert caps['ao_vmax'] == pytest.approx(4.242641)  # 9260 rail

    def test_chassis_ai_only(self):
        entry = _chassis_entry('cDAQ1', 'cDAQ-9171',
                               [('cDAQ1Mod1', 4, 0)])
        ai_dev = FakeCapDevice('cDAQ1Mod1')
        caps = _ni.entry_capabilities(entry, resolver=lambda n: ai_dev)
        assert caps['ai_max_rate'] == 51200.0
        assert caps['ao_max_rate'] is None
        assert caps['ao_supported'] is False


class _FakeTerminalConfiguration(object):
    """Stand-in for the nidaqmx TerminalConfiguration enum class."""
    RSE = _FakeEnumValue('RSE')
    NRSE = _FakeEnumValue('NRSE')
    DIFF = _FakeEnumValue('DIFF')
    PSEUDO_DIFF = _FakeEnumValue('PSEUDO_DIFF')


class TestResolveTerminalConfigForEntry:
    """Device-aware NI_mode resolution (found on the real cDAQ-9174:
    the MySettings default RSE is impossible on the 9234, which used to
    surface as raw DAQmx -200077 through the serve bridge)."""

    @pytest.fixture(autouse=True)
    def patch_term_cfg(self, monkeypatch):
        monkeypatch.setattr(_ni, 'TerminalConfiguration',
                            _FakeTerminalConfiguration)

    def test_supported_mode_passes_through(self, capsys):
        entry = _usb_entry('Dev1', 'USB-6212', ai=16, ao=2)
        dev = FakeCapDevice('Dev1', product_type='USB-6212', ai=16, ao=2,
                            iepe_vals=(), term_cfg_names=('RSE', 'DIFF'))
        cfg = _ni.resolve_terminal_config_for_entry(
            entry, 'DAQmx_Val_RSE', resolver=lambda n: dev)
        assert cfg is _FakeTerminalConfiguration.RSE
        assert capsys.readouterr().out == ''

    def test_unsupported_mode_falls_back_with_note(self, capsys):
        # 9234-like DSA module: pseudo-diff only. Requesting the default
        # RSE must fall back rather than crash at channel creation.
        entry = _chassis_entry('cDAQ1', 'cDAQ-9174',
                               [('cDAQ1Mod1', 4, 0)])
        ai_dev = FakeCapDevice('cDAQ1Mod1')  # pseudo-diff only
        cfg = _ni.resolve_terminal_config_for_entry(
            entry, 'DAQmx_Val_RSE', resolver=lambda n: ai_dev)
        assert cfg is _FakeTerminalConfiguration.PSEUDO_DIFF
        out = capsys.readouterr().out
        assert 'DAQmx_Val_RSE' in out and 'DAQmx_Val_PseudoDiff' in out
        assert 'cDAQ1' in out

    def test_no_capability_info_returns_requested(self):
        # Probe reports nothing (e.g. AO-only module) — DAQmx decides.
        entry = _usb_entry('Dev1', 'USB-6003', ai=8, ao=2)
        dev = _MissingAxisDevice()
        cfg = _ni.resolve_terminal_config_for_entry(
            entry, 'DAQmx_Val_Diff', resolver=lambda n: dev)
        assert cfg is _FakeTerminalConfiguration.DIFF

    def test_probe_failure_returns_requested(self):
        entry = _usb_entry('Dev1', 'USB-6003', ai=8, ao=2)

        def boom(name):
            raise RuntimeError('no driver')

        cfg = _ni.resolve_terminal_config_for_entry(
            entry, 'DAQmx_Val_RSE', resolver=boom)
        assert cfg is _FakeTerminalConfiguration.RSE

    def test_unknown_mode_still_raises(self):
        entry = _usb_entry('Dev1', 'USB-6003', ai=8, ao=2)
        with pytest.raises(ValueError):
            _ni.resolve_terminal_config_for_entry(
                entry, 'DAQmx_Val_Bogus', resolver=lambda n: None)
