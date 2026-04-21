"""Shared pytest fixtures and configuration for pydvma tests.

Registers the `hardware` marker used by `test_acquisition_hardware.py`
so `pytest -m "not hardware"` selects the Mac-runnable subset.
"""


def pytest_configure(config):
    config.addinivalue_line(
        'markers',
        'hardware: requires a live NI device discoverable via nidaqmx; '
        'auto-skipped when none are present (e.g. on Mac).',
    )
