"""Headless smoke test for the live Oscilloscope widget.

Verifies that after the Vmax refactor the oscilloscope still:

1. Constructs without error against a live NI stream.
2. Actually pumps data — `osc_time_data` accumulates non-zero samples.
3. Renders something — grabbing the window gives a QImage with
   non-background pixels (a bare white canvas would indicate the
   plot items aren't being updated).
4. Closes cleanly (no lingering Qt timers / resources).

Auto-skipped on machines without nidaqmx or with no NI devices.
"""
import time
import numpy as np
import pytest

try:
    import nidaqmx  # noqa: F401
    _NIDAQMX_AVAILABLE = True
except ImportError:
    _NIDAQMX_AVAILABLE = False

if not _NIDAQMX_AVAILABLE:
    pytest.skip('nidaqmx not installed', allow_module_level=True)

import pydvma as dvma
from pydvma import _ni_backend, streams


pytestmark = pytest.mark.hardware


_DEVICES = [e for e in _ni_backend.enumerate_devices()
            if e['ai_channel_count'] >= 1]
if not _DEVICES:
    pytest.skip('No NI devices with at least one AI channel',
                allow_module_level=True)


@pytest.fixture
def live_settings():
    """Pick the first available AI-capable device; set up modest
    rates that all our kit comfortably handles."""
    entry = _DEVICES[0]
    if entry['is_chassis']:
        cfg = dict(NI_mode='DAQmx_Val_PseudoDiff', VmaxNI=5)
    else:
        cfg = dict(NI_mode='DAQmx_Val_RSE', VmaxNI=10)
    idx = _ni_backend.enumerate_devices().index(entry)
    return dvma.MySettings(
        device_driver='nidaq', device_index=idx,
        channels=1, fs=5000, stored_time=0.3,
        **cfg,
    )


@pytest.fixture(autouse=True)
def _cleanup_stream():
    yield
    try:
        if streams.REC is not None:
            streams.REC.end_stream()
    except Exception:
        pass


def _pump(seconds):
    """Run the Qt event loop for `seconds` to let timers fire."""
    # Import lazily so a platform without qtpy doesn't crash at collection.
    from qtpy.QtWidgets import QApplication
    app = QApplication.instance()
    assert app is not None, 'QApplication was not created at pydvma import'
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.02)


def test_oscilloscope_constructs_and_renders(live_settings):
    """End-to-end: instantiate Oscilloscope, let the update timer fire
    a handful of times, grab the window, assert pixels + buffer filled.
    """
    # flag_standalone=False stops Oscilloscope.__init__ from calling
    # app.exec() (which would block the test forever).
    osc = dvma.Oscilloscope(live_settings, flag_standalone=False)
    try:
        # Let the AI stream warm up *and* the 60 ms QTimer fire a few
        # times (~10 times in 700 ms).
        _pump(0.7)

        # Buffer filled by the stream callback.
        assert osc.rec is not None, 'oscilloscope did not create a recorder'
        assert np.any(np.abs(osc.rec.osc_time_data) > 0), (
            'osc_time_data is still all zeros after 700 ms — '
            'stream callback not firing?'
        )
        assert np.isfinite(osc.rec.osc_time_data).all()

        # Window rendered something other than a blank background.
        pixmap = osc.win.grab()
        assert not pixmap.isNull(), 'window grab returned an empty pixmap'
        img = pixmap.toImage()
        assert img.width() > 100 and img.height() > 100, (
            'window too small to carry a meaningful plot: {}x{}'
            .format(img.width(), img.height())
        )
        # Count non-white pixels on a coarse grid (every 10 px). The
        # pyqtgraph background is white; axes/ticks/curves are darker.
        # A healthy plot easily produces hundreds of dark pixels on
        # this sparse sample.
        non_white = 0
        step = 10
        for x in range(0, img.width(), step):
            for y in range(0, img.height(), step):
                c = img.pixelColor(x, y)
                # "White-ish" = R, G, B all > 240. Anything below
                # counts as rendered plot content.
                if not (c.red() > 240 and c.green() > 240 and c.blue() > 240):
                    non_white += 1
        assert non_white > 50, (
            'only {} non-white pixels on a {}x{} grab — plot may be blank'
            .format(non_white, img.width(), img.height())
        )
    finally:
        # Clean shutdown: stop the QTimer + close the window so the
        # next test doesn't inherit a live one.
        osc.timer.stop()
        osc.win.close()
