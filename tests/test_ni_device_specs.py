"""Unit tests for pydvma._ni_device_specs.

Mac-runnable: uses mocked nidaqmx Device objects, no hardware or
nidaqmx install required. Loads _ni_device_specs via importlib to
avoid pulling the full pydvma package (gui, pyqtgraph, etc.).
"""
import importlib.util
from pathlib import Path

import pytest


_SPECS_PATH = Path(__file__).resolve().parent.parent / 'pydvma' / '_ni_device_specs.py'
_spec = importlib.util.spec_from_file_location('_ni_device_specs', _SPECS_PATH)
_specs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_specs)


# --- Fake nidaqmx.system.Device -------------------------------------------

class FakeDevice(object):
    """Mimic the properties `get_device_info` queries.

    Setting a value to the sentinel `_specs._try` raises is achieved by
    using the `_UNSUPPORTED` flag on specific attributes so they raise
    on access — modelling DAQmx error -200197 for AI/AO properties on
    modules without that axis.
    """
    _UNSUPPORTED = object()

    def __init__(self, name, product_type, *,
                 ai_voltage_rngs=(),
                 ai_max_single_chan_rate=None, ai_min_rate=None,
                 ao_voltage_rngs=(),
                 ao_max_rate=None, ao_min_rate=None,
                 product_category=None):
        self.name = name
        self.product_type = product_type
        self._ai_voltage_rngs = list(ai_voltage_rngs)
        self._ai_max_single_chan_rate = ai_max_single_chan_rate
        self._ai_min_rate = ai_min_rate
        self._ao_voltage_rngs = list(ao_voltage_rngs)
        self._ao_max_rate = ao_max_rate
        self._ao_min_rate = ao_min_rate
        self._product_category = product_category

    def _get_or_raise(self, val, propname):
        if val is self._UNSUPPORTED or val is None:
            if val is self._UNSUPPORTED:
                raise RuntimeError('DAQmx -200197: %s not supported' % propname)
            return val
        return val

    @property
    def ai_voltage_rngs(self):
        if not self._ai_voltage_rngs:
            raise RuntimeError('DAQmx -200197: AI not supported')
        return self._ai_voltage_rngs

    @property
    def ai_max_single_chan_rate(self):
        if self._ai_max_single_chan_rate is None:
            raise RuntimeError('DAQmx -200197')
        return self._ai_max_single_chan_rate

    @property
    def ai_min_rate(self):
        if self._ai_min_rate is None:
            raise RuntimeError('DAQmx -200197')
        return self._ai_min_rate

    @property
    def ao_voltage_rngs(self):
        if not self._ao_voltage_rngs:
            raise RuntimeError('DAQmx -200197: AO not supported')
        return self._ao_voltage_rngs

    @property
    def ao_max_rate(self):
        if self._ao_max_rate is None:
            raise RuntimeError('DAQmx -200197')
        return self._ao_max_rate

    @property
    def ao_min_rate(self):
        if self._ao_min_rate is None:
            raise RuntimeError('DAQmx -200197')
        return self._ao_min_rate

    @property
    def product_category(self):
        return self._product_category


def _make_usb_6003():
    return FakeDevice(
        'Dev3', 'USB-6003',
        ai_voltage_rngs=[-10.0, 10.0],
        ai_max_single_chan_rate=100000.0, ai_min_rate=0.019,
        ao_voltage_rngs=[-10.0, 10.0],
        ao_max_rate=5000.0, ao_min_rate=0.019,
    )


def _make_usb_6212():
    return FakeDevice(
        'Dev2', 'USB-6212',
        ai_voltage_rngs=[-0.2, 0.2, -1.0, 1.0, -5.0, 5.0, -10.0, 10.0],
        ai_max_single_chan_rate=400000.0, ai_min_rate=0.005,
        ao_voltage_rngs=[-10.0, 10.0],
        ao_max_rate=250000.0, ao_min_rate=0.005,
    )


def _make_9234():
    return FakeDevice(
        'cDAQ1Mod1', 'NI 9234',
        ai_voltage_rngs=[-5.0, 5.0],
        ai_max_single_chan_rate=51200.0, ai_min_rate=1651.6,
    )


def _make_9260():
    return FakeDevice(
        'cDAQ1Mod2', 'NI 9260 (BNC)',
        ao_voltage_rngs=[-4.24264068712, 4.24264068712],
        ao_max_rate=51200.0, ao_min_rate=1612.9,
    )


@pytest.fixture
def patch_nidaqmx_device(monkeypatch):
    """Replace nidaqmx.system.Device(name) with a FakeDevice lookup."""
    registry = {}

    def fake_Device(name):
        if name not in registry:
            raise KeyError('Unknown fake device %r' % name)
        return registry[name]

    class _FakeNidaqmxModule:
        class system:
            Device = staticmethod(fake_Device)

    monkeypatch.setattr(_specs, 'nidaqmx', _FakeNidaqmxModule)
    return registry


# --- get_device_info --------------------------------------------------------

class TestGetDeviceInfo:

    def test_usb_6003(self, patch_nidaqmx_device):
        patch_nidaqmx_device['Dev3'] = _make_usb_6003()
        info = _specs.get_device_info('Dev3')
        assert info['name'] == 'Dev3'
        assert info['product_type'] == 'USB-6003'
        assert info['ai_voltage_ranges'] == [(-10.0, 10.0)]
        assert info['ao_voltage_ranges'] == [(-10.0, 10.0)]
        assert info['ai_max_single_chan_rate'] == 100000.0
        assert info['ao_max_rate'] == 5000.0
        # QUIRKS note for USB-6003 is merged in
        assert 'software-timed' in info['notes']

    def test_usb_6212_multiple_ranges(self, patch_nidaqmx_device):
        patch_nidaqmx_device['Dev2'] = _make_usb_6212()
        info = _specs.get_device_info('Dev2')
        # four symmetric ranges on AI
        assert (-10.0, 10.0) in info['ai_voltage_ranges']
        assert (-0.2, 0.2) in info['ai_voltage_ranges']
        assert len(info['ai_voltage_ranges']) == 4

    def test_module_without_ao(self, patch_nidaqmx_device):
        # 9234 has no AO — properties raise -200197; info should reflect
        # that as empty ranges / None rates, not crash.
        patch_nidaqmx_device['cDAQ1Mod1'] = _make_9234()
        info = _specs.get_device_info('cDAQ1Mod1')
        assert info['ai_voltage_ranges'] == [(-5.0, 5.0)]
        assert info['ao_voltage_ranges'] == []
        assert info['ao_max_rate'] is None
        # QUIRKS entry for NI 9234
        assert info['terminal_configs'] == ['DAQmx_Val_PseudoDiff']
        assert info['ac_coupled_hpf_hz'] == 0.5

    def test_module_without_ai(self, patch_nidaqmx_device):
        patch_nidaqmx_device['cDAQ1Mod2'] = _make_9260()
        info = _specs.get_device_info('cDAQ1Mod2')
        assert info['ai_voltage_ranges'] == []
        assert info['ai_max_single_chan_rate'] is None
        assert info['ao_voltage_ranges'] == [(-4.24264068712, 4.24264068712)]
        assert info['ao_max_rate'] == 51200.0

    def test_no_nidaqmx(self, monkeypatch):
        monkeypatch.setattr(_specs, 'nidaqmx', None)
        with pytest.raises(RuntimeError, match='not installed'):
            _specs.get_device_info('Dev1')


# --- suggest_ni_settings (indirectly tests _pick_vmax, _pick_terminal_config,
#     _safe_fs) -------------------------------------------------------------

class TestPickHelpers:

    def test_pick_vmax_prefers_symmetric(self):
        # If symmetric ranges exist, use the largest of those.
        assert _specs._pick_vmax([(-10, 10), (-5, 5), (-1, 1)], default=99) == 10.0

    def test_pick_vmax_fallback(self):
        assert _specs._pick_vmax([], default=7.5) == 7.5

    def test_pick_terminal_config_quirked(self):
        assert _specs._pick_terminal_config(
            {'terminal_configs': ['DAQmx_Val_PseudoDiff']}
        ) == 'DAQmx_Val_PseudoDiff'

    def test_pick_terminal_config_default(self):
        assert _specs._pick_terminal_config({}) == 'DAQmx_Val_RSE'

    def test_safe_fs_caps_at_lower_max(self):
        # AI max 400 kS/s, AO max 5 kS/s -> ceiling = 5 kS/s,
        # fs = 5000/4 = 1250, rounded to nearest 100 = 1200.
        # The critical property: fs is well below AO max.
        ai = {'ai_max_single_chan_rate': 400000.0}
        ao = {'ao_max_rate': 5000.0}
        fs = _specs._safe_fs(ai, ao)
        assert fs <= 5000
        assert 1000 <= fs <= 1500

    def test_safe_fs_respects_ao_min(self):
        # If AO min is say 1612, fs must be at least that.
        ai = {'ai_max_single_chan_rate': 51200}
        ao = {'ao_max_rate': 51200, 'ao_min_rate': 1612.9}
        fs = _specs._safe_fs(ai, ao)
        # 51200/4 = 12800; ceiling capped by hard_ceiling 50000 so 50000/4=12500
        assert fs >= 1612.9
        assert fs <= 50000


@pytest.fixture
def patch_enumerate(monkeypatch):
    """Patch _ni_backend.enumerate_devices via sys.modules."""
    import sys
    # Create a minimal fake _ni_backend module that lives inside a fake
    # `pydvma` package so the `from . import _ni_backend` inside
    # _ni_device_specs.suggest_ni_settings resolves to our mock.
    fake_ni_backend = type(sys)('pydvma._ni_backend')
    fake_ni_backend.enumerate_devices = lambda: []
    fake_pydvma_pkg = type(sys)('pydvma')
    fake_pydvma_pkg._ni_backend = fake_ni_backend
    fake_pydvma_pkg.__path__ = []   # mark as package
    # Register the specs module as pydvma._ni_device_specs so the
    # relative import inside it resolves.
    _specs.__package__ = 'pydvma'
    sys.modules['pydvma'] = fake_pydvma_pkg
    sys.modules['pydvma._ni_backend'] = fake_ni_backend
    sys.modules['pydvma._ni_device_specs'] = _specs
    yield fake_ni_backend
    for name in ('pydvma', 'pydvma._ni_backend', 'pydvma._ni_device_specs'):
        sys.modules.pop(name, None)


class TestSuggestNiSettings:

    def test_usb_6003(self, patch_enumerate, patch_nidaqmx_device):
        patch_enumerate.enumerate_devices = lambda: [{
            'name': 'Dev3', 'product_type': 'USB-6003',
            'is_chassis': False, 'ai_channel_count': 8, 'ao_channel_count': 2,
            'module_names': [], 'module_ai_counts': {}, 'module_ao_counts': {},
        }]
        patch_nidaqmx_device['Dev3'] = _make_usb_6003()
        s = _specs.suggest_ni_settings(0)
        assert s['device_driver'] == 'nidaq'
        assert s['device_index'] == 0
        assert s['NI_mode'] == 'DAQmx_Val_RSE'
        assert s['VmaxNI'] == 10.0
        assert s['output_VmaxNI'] == 10.0
        # fs <= AO ceiling (5000/4 ~ 1250 -> rounded)
        assert s['fs'] <= 2000

    def test_usb_6212(self, patch_enumerate, patch_nidaqmx_device):
        patch_enumerate.enumerate_devices = lambda: [{
            'name': 'Dev2', 'product_type': 'USB-6212',
            'is_chassis': False, 'ai_channel_count': 16, 'ao_channel_count': 2,
            'module_names': [], 'module_ai_counts': {}, 'module_ao_counts': {},
        }]
        patch_nidaqmx_device['Dev2'] = _make_usb_6212()
        s = _specs.suggest_ni_settings(0)
        assert s['VmaxNI'] == 10.0
        assert s['output_VmaxNI'] == 10.0
        assert s['NI_mode'] == 'DAQmx_Val_RSE'

    def test_cdaq_chassis(self, patch_enumerate, patch_nidaqmx_device):
        patch_enumerate.enumerate_devices = lambda: [{
            'name': 'cDAQ1', 'product_type': 'cDAQ-9174',
            'is_chassis': True, 'ai_channel_count': 4, 'ao_channel_count': 2,
            'module_names': ['cDAQ1Mod1', 'cDAQ1Mod2'],
            'module_ai_counts': {'cDAQ1Mod1': 4, 'cDAQ1Mod2': 0},
            'module_ao_counts': {'cDAQ1Mod1': 0, 'cDAQ1Mod2': 2},
        }]
        patch_nidaqmx_device['cDAQ1Mod1'] = _make_9234()
        patch_nidaqmx_device['cDAQ1Mod2'] = _make_9260()
        s = _specs.suggest_ni_settings(0)
        # 9234 is pseudo-diff only, fixed ±5
        assert s['NI_mode'] == 'DAQmx_Val_PseudoDiff'
        assert s['VmaxNI'] == 5.0
        # 9260 AO limit ±4.24
        assert abs(s['output_VmaxNI'] - 4.24264068712) < 1e-6
        # fs within joint range: 1613 <= fs <= 51200/4 ~ 12800
        assert 1613 <= s['fs'] <= 15000

    def test_out_of_range_index_raises(self, patch_enumerate):
        patch_enumerate.enumerate_devices = lambda: []
        with pytest.raises(RuntimeError, match='No NI devices'):
            _specs.suggest_ni_settings(0)
