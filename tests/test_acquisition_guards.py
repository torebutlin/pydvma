"""Input-validation tests for the trigger/pretrigger settings.

These don't need hardware — both guards fire before any stream is
opened, so these tests run on Mac too. The guards come in two layers:

* `MySettings.__init__` rejects invalid combinations at construction
  time (primary defence).
* `acquisition.log_data` re-checks at call time in case settings were
  mutated after construction — e.g. ``s.pretrig_samples = N`` is
  idiomatic in some of the hardware tests.
"""
import pytest

import pydvma as dvma
from pydvma import acquisition


class TestConstructionGuard:
    """`MySettings.__init__` should reject pretrig_samples > chunk_size
    at construction time with a ValueError carrying a clear message.
    """

    def test_raises_above_chunk_size(self):
        with pytest.raises(ValueError, match='pretrig_samples'):
            dvma.MySettings(
                device_driver='soundcard',
                fs=10000, channels=1, chunk_size=100, stored_time=0.5,
                pretrig_samples=200,
                pretrig_threshold=0.1,
            )

    def test_accepts_at_boundary(self):
        """pretrig_samples == chunk_size is the largest valid window."""
        s = dvma.MySettings(
            device_driver='soundcard',
            fs=10000, channels=1, chunk_size=100, stored_time=0.5,
            pretrig_samples=100,
            pretrig_threshold=0.1,
        )
        assert s.pretrig_samples == 100

    def test_accepts_below_boundary(self):
        s = dvma.MySettings(
            device_driver='soundcard',
            fs=10000, channels=1, chunk_size=100, stored_time=0.5,
            pretrig_samples=50,
            pretrig_threshold=0.1,
        )
        assert s.pretrig_samples == 50

    def test_none_bypasses_guard(self):
        """pretrig_samples=None disables triggering; the chunk_size
        constraint doesn't apply."""
        s = dvma.MySettings(
            device_driver='soundcard',
            fs=10000, channels=1, chunk_size=50, stored_time=0.3,
            pretrig_samples=None,
        )
        assert s.pretrig_samples is None


class TestCallSiteGuard:
    """`acquisition.log_data` re-checks pretrig_samples vs chunk_size
    at call time. Catches post-construction mutation that sneaks past
    the constructor check.
    """

    def _valid_settings(self):
        return dvma.MySettings(
            device_driver='soundcard',
            fs=10000, channels=1, chunk_size=100, stored_time=0.3,
            pretrig_samples=50, pretrig_threshold=0.1,
        )

    def test_mutated_above_chunk_size_raises(self):
        s = self._valid_settings()
        s.pretrig_samples = 200      # now inconsistent with chunk_size
        with pytest.raises(ValueError, match='pretrig_samples'):
            acquisition.log_data(s)

    def test_mutated_chunk_size_below_pretrig_raises(self):
        """Equivalent inconsistency the other way: shrinking chunk_size
        below pretrig_samples must also raise."""
        s = self._valid_settings()
        s.chunk_size = 10            # now pretrig_samples (50) > chunk_size
        with pytest.raises(ValueError, match='pretrig_samples'):
            acquisition.log_data(s)
