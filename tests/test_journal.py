# tests/test_journal.py
"""SessionJournal: the serve process's in-memory session store.

Pure-Python (no websockets, no asyncio): doc replace, capture
registration, the clears-pending contract, listener fan-out, the
best-effort spill file and the crash-recovery adoption surface.
"""
import threading

import pytest

import pydvma.journal as journal_module
from pydvma.journal import SessionJournal


class TestDocAndCaptures:

    def test_empty_state(self):
        j = SessionJournal()
        doc, captures = j.state()
        assert doc is None
        assert captures == []

    def test_set_doc_replaces(self):
        j = SessionJournal()
        j.set_doc(b'v1')
        j.set_doc(b'v2')
        doc, _ = j.state()
        assert doc == b'v2'

    def test_add_capture_accumulates_in_order(self):
        j = SessionJournal()
        j.add_capture(b'c1')
        j.add_capture(b'c2')
        _, captures = j.state()
        assert captures == [b'c1', b'c2']

    def test_set_doc_clears_pending_captures(self):
        # A doc posted by the app AFTER a capture arrived includes that
        # capture (the app serialises its dataset at post time), so the
        # pending copy is redundant the moment a doc lands.
        j = SessionJournal()
        j.add_capture(b'c1')
        j.set_doc(b'doc')
        _, captures = j.state()
        assert captures == []

    def test_capture_after_doc_stays_pending(self):
        j = SessionJournal()
        j.set_doc(b'doc')
        j.add_capture(b'c1')
        doc, captures = j.state()
        assert doc == b'doc'
        assert captures == [b'c1']

    def test_state_returns_copies(self):
        j = SessionJournal()
        j.add_capture(b'c1')
        _, captures = j.state()
        captures.append(b'evil')
        assert j.state()[1] == [b'c1']


class TestListeners:

    def test_notify_fans_out(self):
        j = SessionJournal()
        hits = []
        j.add_listener(lambda: hits.append(1))
        j.add_listener(lambda: hits.append(2))
        j.set_doc(b'doc', notify=True)
        assert sorted(hits) == [1, 2]

    def test_set_doc_without_notify_is_silent(self):
        j = SessionJournal()
        hits = []
        j.add_listener(lambda: hits.append(1))
        j.set_doc(b'doc')
        assert hits == []

    def test_remove_listener(self):
        j = SessionJournal()
        hits = []
        unsub = j.add_listener(lambda: hits.append(1))
        unsub()
        j.set_doc(b'doc', notify=True)
        assert hits == []

    def test_listener_error_does_not_break_others(self):
        j = SessionJournal()
        hits = []

        def bad():
            raise RuntimeError('boom')

        j.add_listener(bad)
        j.add_listener(lambda: hits.append(1))
        j.set_doc(b'doc', notify=True)
        assert hits == [1]

    def test_double_unsubscribe_is_safe(self):
        j = SessionJournal()
        hits = []
        unsub = j.add_listener(lambda: hits.append(1))
        unsub()
        unsub()                    # must not raise
        j.set_doc(b'doc', notify=True)
        assert hits == []


class TestSpill:

    def test_set_doc_spills_to_file(self, tmp_path):
        spill = tmp_path / 'session.dvma'
        j = SessionJournal(spill_path=spill)
        j.set_doc(b'doc-bytes')
        assert spill.read_bytes() == b'doc-bytes'

    def test_spill_failure_is_swallowed(self, tmp_path):
        # Best-effort: an unwritable spill path must never break the op.
        j = SessionJournal(spill_path=tmp_path / 'no' / 'such' / 'dir' / 'f.dvma')
        j.set_doc(b'doc')          # must not raise
        assert j.state()[0] == b'doc'

    def test_spill_path_settable_after_construction(self, tmp_path):
        # BridgeServer only knows its real port after bind (port=0).
        j = SessionJournal()
        j.set_spill_path(tmp_path / 'late.dvma')
        j.set_doc(b'doc')
        assert (tmp_path / 'late.dvma').read_bytes() == b'doc'

    def test_spill_path_property_reflects_setter(self, tmp_path):
        j = SessionJournal()
        target = tmp_path / 'late.dvma'
        j.set_spill_path(target)
        assert j.spill_path == target

    def test_add_capture_alone_creates_no_spill_file(self, tmp_path):
        # The spill mirrors the DOCUMENT only, never pending captures.
        spill = tmp_path / 'session.dvma'
        j = SessionJournal(spill_path=spill)
        j.add_capture(b'c1')
        assert not spill.exists()

    def test_concurrent_spill_matches_final_doc(self, tmp_path):
        # Pins the serialised atomic spill against the real production
        # shape: two independent set_doc writers (app autosave thread +
        # notebook push thread) racing each other. Large,
        # single-byte-repeated payloads make a torn/interleaved write
        # fail deterministically -- an interleave of A's and B's could
        # never read back as a pure run of one byte value.
        spill = tmp_path / 'session.dvma'
        j = SessionJournal(spill_path=spill)
        payload_a = b'A' * 1_000_000
        payload_b = b'B' * 900_000
        rounds = 5

        def writer_a():
            for _ in range(rounds):
                j.set_doc(payload_a)

        def writer_b():
            for _ in range(rounds):
                j.set_doc(payload_b)

        threads = [threading.Thread(target=writer_a),
                   threading.Thread(target=writer_b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        on_disk = spill.read_bytes()
        assert on_disk == j.state()[0]
        distinct = set(on_disk)
        assert distinct <= {ord('A')} or distinct <= {ord('B')}

    def test_no_tmp_residue_after_normal_spill(self, tmp_path):
        spill = tmp_path / 'session.dvma'
        j = SessionJournal(spill_path=spill)
        j.set_doc(b'doc-bytes')
        names = {p.name for p in tmp_path.iterdir()}
        assert names == {'session.dvma'}

    def test_replace_failure_leaves_previous_file_intact(
            self, tmp_path, monkeypatch):
        spill = tmp_path / 'session.dvma'
        j = SessionJournal(spill_path=spill)
        j.set_doc(b'first')
        assert spill.read_bytes() == b'first'

        def boom(*args, **kwargs):
            raise OSError('simulated os.replace failure')

        monkeypatch.setattr(journal_module.os, 'replace', boom)
        j.set_doc(b'second')          # must not raise
        assert spill.read_bytes() == b'first'
        names = {p.name for p in tmp_path.iterdir()}
        assert names == {'session.dvma'}


class TestRecovered:
    """Crash recovery: a previous run's spill file is read into memory
    at startup and OFFERED; discard deletes the file."""

    def test_adopt_recovered_reads_bytes(self, tmp_path):
        old = tmp_path / 'pydvma-session-8765.dvma'
        old.write_bytes(b'old-session')
        j = SessionJournal()
        j.adopt_recovered(old)
        assert j.recovered() == b'old-session'

    def test_recovered_survives_file_overwrite(self, tmp_path):
        # Read-at-adopt: overwriting the same path later (same-port
        # restart spills onto it) must not corrupt the offer.
        old = tmp_path / 's.dvma'
        old.write_bytes(b'old-session')
        j = SessionJournal(spill_path=old)
        j.adopt_recovered(old)
        j.set_doc(b'new-live-doc')          # overwrites the file
        assert j.recovered() == b'old-session'

    def test_discard_recovered_deletes_file(self, tmp_path):
        old = tmp_path / 's.dvma'
        old.write_bytes(b'old')
        j = SessionJournal()
        j.adopt_recovered(old)
        j.discard_recovered()
        assert j.recovered() is None
        assert not old.exists()

    def test_adopt_missing_file_is_noop(self, tmp_path):
        j = SessionJournal()
        j.adopt_recovered(tmp_path / 'absent.dvma')
        assert j.recovered() is None

    def test_adopt_empty_file_is_noop(self, tmp_path):
        old = tmp_path / 'empty.dvma'
        old.write_bytes(b'')
        j = SessionJournal()
        j.adopt_recovered(old)
        assert j.recovered() is None

    def test_discard_recovered_twice_is_safe(self, tmp_path):
        old = tmp_path / 's.dvma'
        old.write_bytes(b'old')
        j = SessionJournal()
        j.adopt_recovered(old)
        j.discard_recovered()
        j.discard_recovered()      # must not raise
        assert j.recovered() is None

    def test_discard_keeps_file_that_is_the_live_spill_target(self, tmp_path):
        # A same-port restart adopts what is now its own live spill
        # file; discarding the OFFER must not delete the live mirror.
        live = tmp_path / 's.dvma'
        live.write_bytes(b'old-session')
        j = SessionJournal(spill_path=live)
        j.adopt_recovered(live)
        j.discard_recovered()
        assert j.recovered() is None
        assert live.exists()

    def test_discard_keeps_file_with_mixed_str_and_path_identity(
            self, tmp_path):
        # spill_path set as a str, adopted path passed as a Path (or
        # vice versa) must still be recognised as the SAME file -- the
        # raw objects compare unequal, but the guard normalises both
        # through os.path.abspath before comparing.
        live = tmp_path / 's.dvma'
        live.write_bytes(b'old-session')
        j = SessionJournal(spill_path=str(live))
        j.adopt_recovered(live)             # a pathlib.Path this time
        assert str(live) != live            # sanity: raw objects differ
        j.discard_recovered()
        assert j.recovered() is None
        assert live.exists()


class TestTypeGuards:

    def test_set_doc_rejects_non_bytes(self):
        j = SessionJournal()
        with pytest.raises(TypeError):
            j.set_doc(5)

    def test_add_capture_rejects_non_bytes(self):
        j = SessionJournal()
        with pytest.raises(TypeError):
            j.add_capture(5)


class TestThreadSafety:

    def test_concurrent_writers(self):
        j = SessionJournal()
        n = 200

        def capture_writer():
            for i in range(n):
                j.add_capture(b'c%d' % i)

        def doc_writer():
            for i in range(n):
                j.set_doc(b'd%d' % i)

        threads = [threading.Thread(target=capture_writer),
                   threading.Thread(target=doc_writer)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        doc, captures = j.state()
        assert doc == b'd%d' % (n - 1)
        # Pending list is consistent (no torn state); exact content
        # depends on interleaving.
        assert all(c.startswith(b'c') for c in captures)
