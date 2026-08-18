# tests/test_journal.py
"""SessionJournal: the serve process's in-memory session store.

Pure-Python (no websockets, no asyncio): doc replace, capture
registration, the clears-pending contract, listener fan-out, the
best-effort spill file and the crash-recovery adoption surface.
"""
import threading

import numpy as np
import pytest

import pydvma.journal as journal_module
from pydvma import container, datastructure, options
from pydvma.journal import SessionJournal


def _capture_bytes(n_samples=8):
    """Real ``.dvma`` bytes holding one TimeData — a capture as
    `serve` registers it. Returns ``(bytes, unique_id_str)``."""
    settings = options.MySettings.__new__(options.MySettings)
    td = datastructure.TimeData(
        np.arange(n_samples, dtype=float),
        np.zeros((n_samples, 1)), settings, test_name='cap')
    ds = datastructure.DataSet(td)
    return container.save_bytes(ds), str(td.unique_id)


def _doc_bytes(*capture_blobs):
    """A session document containing exactly the given captures — what
    the app posts once it has received them."""
    ds = datastructure.DataSet()
    for blob in capture_blobs:
        for td in container.load_bytes(blob).time_data_list:
            ds.add_to_dataset(td)
    return container.save_bytes(ds)


class TestDocAndCaptures:

    def test_empty_state(self):
        j = SessionJournal()
        doc, captures, _ = j.state()
        assert doc is None
        assert captures == []

    def test_set_doc_replaces(self):
        j = SessionJournal()
        j.set_doc(b'v1')
        j.set_doc(b'v2')
        doc, _, _ = j.state()
        assert doc == b'v2'

    def test_add_capture_accumulates_in_order(self):
        j = SessionJournal()
        j.add_capture(b'c1')
        j.add_capture(b'c2')
        _, captures, _ = j.state()
        assert captures == [b'c1', b'c2']

    def test_set_doc_clears_pending_captures(self):
        # A doc posted by the app AFTER a capture arrived includes that
        # capture (the app serialises its dataset at post time), so the
        # pending copy is redundant the moment a doc lands.
        j = SessionJournal()
        j.add_capture(b'c1')
        j.set_doc(b'doc')
        _, captures, _ = j.state()
        assert captures == []

    def test_capture_after_doc_stays_pending(self):
        j = SessionJournal()
        j.set_doc(b'doc')
        j.add_capture(b'c1')
        doc, captures, _ = j.state()
        assert doc == b'doc'
        assert captures == [b'c1']

    def test_state_returns_copies(self):
        j = SessionJournal()
        j.add_capture(b'c1')
        _, captures, _ = j.state()
        captures.append(b'evil')
        assert j.state()[1] == [b'c1']


class TestIdMatchedClearing:
    """A post clears only the captures the posted document PROVABLY
    contains (matched by TimeData unique_id), so a capture registered
    after the poster serialised its document -- or one belonging to
    another tab -- is never dropped without being anywhere.
    """

    def test_capture_inside_the_posted_doc_is_cleared(self):
        blob, _uid = _capture_bytes()
        j = SessionJournal()
        j.add_capture(blob)
        j.set_doc(_doc_bytes(blob))
        assert j.state()[1] == []

    def test_capture_absent_from_the_posted_doc_survives(self):
        # THE capture-loss window: registered after the app serialised
        # its document, cleared before this fix without ever being in
        # any document.
        early, _ = _capture_bytes()
        late, _ = _capture_bytes()
        j = SessionJournal()
        j.add_capture(early)
        doc = _doc_bytes(early)         # app serialises what it has...
        j.add_capture(late)             # ...capture lands...
        j.set_doc(doc)                  # ...post arrives
        assert j.state()[1] == [late]

    def test_two_tabs_do_not_clear_each_other(self):
        # Tab B posts a document that knows nothing of tab A's capture.
        a, _ = _capture_bytes()
        b, _ = _capture_bytes()
        j = SessionJournal()
        j.add_capture(a)
        j.add_capture(b)
        j.set_doc(_doc_bytes(b))        # only B's capture is inside
        assert j.state()[1] == [a]
        j.set_doc(_doc_bytes(a, b))     # a doc holding both clears both
        assert j.state()[1] == []

    def test_partial_overlap_keeps_only_the_missing_capture(self):
        a, _ = _capture_bytes()
        b, _ = _capture_bytes()
        c, _ = _capture_bytes()
        j = SessionJournal()
        for blob in (a, b, c):
            j.add_capture(blob)
        j.set_doc(_doc_bytes(a, c))
        assert j.state()[1] == [b]

    def test_multi_capture_bytes_need_every_id_present(self):
        # A capture blob holding two TimeData is only redundant once
        # the document holds BOTH (subset, not intersection).
        one, _ = _capture_bytes()
        two, _ = _capture_bytes()
        pair = _doc_bytes(one, two)     # one blob, two ids
        j = SessionJournal()
        j.add_capture(pair)
        j.set_doc(_doc_bytes(one))
        assert j.state()[1] == [pair]
        j.set_doc(_doc_bytes(one, two))
        assert j.state()[1] == []

    def test_malformed_capture_is_cleared_by_any_post(self):
        # No readable ids -> the old behaviour, so junk cannot pile up.
        j = SessionJournal()
        j.add_capture(b'not a dvma at all')
        j.set_doc(_doc_bytes())
        assert j.state()[1] == []

    def test_malformed_doc_clears_only_id_less_captures(self):
        good, _ = _capture_bytes()
        j = SessionJournal()
        j.add_capture(good)
        j.add_capture(b'junk')
        j.set_doc(b'not a dvma either')
        assert j.state()[1] == [good]

    def test_generation_semantics_unchanged(self):
        # Both writers still count, whatever the id matching decided.
        blob, _ = _capture_bytes()
        j = SessionJournal()
        j.add_capture(blob)
        assert j.generation == 1
        j.set_doc(_doc_bytes())          # clears nothing now
        assert j.generation == 2
        assert j.state()[1] == [blob]
        assert j.set_doc(_doc_bytes(blob), expect_generation=2) is True
        assert j.generation == 3

    def test_surviving_capture_still_evicts_under_the_budget(self, monkeypatch):
        # The pending list is still bounded: id-matching decides what a
        # POST clears, not what the budget evicts. Cap sized from BOTH
        # blobs -- zip payloads of two captures differ by a few bytes
        # (uuid/timestamp), so a cap taken from the first alone would
        # sometimes evict the second one too.
        first, _ = _capture_bytes()
        second, _ = _capture_bytes()
        monkeypatch.setattr(journal_module, 'PENDING_CAPTURES_MAX_BYTES',
                            max(len(first), len(second)))
        j = SessionJournal()
        j.add_capture(first)
        j.add_capture(second)
        assert j.state()[1] == [second]


class TestGeneration:
    """The optimistic-concurrency counter that lets a read-modify-write
    writer (`pydvma.session.Session.push`) detect that a capture or
    another writer's post landed while it was merging -- without which
    `set_doc`'s whole-document replace would silently drop it.
    """

    def test_starts_at_zero_and_state_reports_it(self):
        j = SessionJournal()
        assert j.generation == 0
        assert j.state()[2] == 0

    def test_set_doc_increments(self):
        j = SessionJournal()
        j.set_doc(b'v1')
        assert j.generation == 1
        j.set_doc(b'v2')
        assert j.generation == 2

    def test_add_capture_increments(self):
        # A capture is exactly the kind of change a merging writer must
        # not overwrite, so it counts as a generation too.
        j = SessionJournal()
        j.add_capture(b'c1')
        assert j.generation == 1
        j.add_capture(b'c2')
        assert j.generation == 2

    def test_matching_expect_generation_succeeds(self):
        j = SessionJournal()
        j.set_doc(b'v1')
        _, _, gen = j.state()
        assert j.set_doc(b'v2', expect_generation=gen) is True
        assert j.state()[0] == b'v2'

    def test_stale_expect_generation_refuses_and_preserves(self):
        j = SessionJournal()
        j.set_doc(b'v1')
        _, _, gen = j.state()
        j.add_capture(b'c1')            # the world moves under the writer
        assert j.set_doc(b'v2', expect_generation=gen) is False
        doc, captures, now = j.state()
        assert doc == b'v1'             # document untouched
        assert captures == [b'c1']      # capture NOT cleared
        assert now == gen + 1           # refusal did not itself count

    def test_refused_post_does_not_notify(self):
        j = SessionJournal()
        hits = []
        j.add_listener(lambda: hits.append(1))
        j.add_capture(b'c1')
        assert j.set_doc(b'v2', notify=True, expect_generation=0) is False
        assert hits == []

    def test_unconditional_post_returns_true(self):
        # The app's own autosave path: no expect_generation, always wins.
        j = SessionJournal()
        j.add_capture(b'c1')
        assert j.set_doc(b'v1') is True


class TestPendingCapturesBudget:
    """`add_capture` bounds the pending list's TOTAL bytes at
    `PENDING_CAPTURES_MAX_BYTES` -- the only backstop against unbounded
    growth for a client that never posts a clearing document (see the
    module docstring's "Pending-captures budget" paragraph). Every test
    here monkeypatches the module constant down to a tiny value so the
    eviction path is exercised without allocating real hundreds-of-MB
    payloads.
    """

    def test_oversized_accumulation_drops_oldest(self, monkeypatch):
        monkeypatch.setattr(journal_module, 'PENDING_CAPTURES_MAX_BYTES', 10)
        j = SessionJournal()
        j.add_capture(b'1234567890')       # exactly at the cap -- kept
        _, captures, _ = j.state()
        assert captures == [b'1234567890']
        j.add_capture(b'x')                # pushes total to 11 -- evicts it
        _, captures, _ = j.state()
        assert captures == [b'x']

    def test_budget_evicts_multiple_oldest_entries_as_needed(self, monkeypatch):
        monkeypatch.setattr(journal_module, 'PENDING_CAPTURES_MAX_BYTES', 5)
        j = SessionJournal()
        j.add_capture(b'aa')
        j.add_capture(b'bb')
        j.add_capture(b'cc')       # total 6 > 5 -- evicts 'aa' -> total 4
        _, captures, _ = j.state()
        assert captures == [b'bb', b'cc']

    def test_single_capture_over_budget_alone_is_evicted_too(self, monkeypatch):
        # No special case for the just-appended entry: with only one
        # entry in the list, "oldest" and "newest" are the same entry,
        # and the eviction loop still runs until back under budget.
        monkeypatch.setattr(journal_module, 'PENDING_CAPTURES_MAX_BYTES', 2)
        j = SessionJournal()
        j.add_capture(b'toolong')
        _, captures, _ = j.state()
        assert captures == []

    def test_doc_post_still_clears_everything_regardless_of_budget(
            self, monkeypatch):
        # The cap only ever matters when nothing posts a document; an
        # ordinary set_doc clears the pending list unconditionally, same
        # as always, however small the budget is set.
        monkeypatch.setattr(journal_module, 'PENDING_CAPTURES_MAX_BYTES', 1000)
        j = SessionJournal()
        j.add_capture(b'c1')
        j.add_capture(b'c2')
        j.set_doc(b'doc')
        doc, captures, _ = j.state()
        assert doc == b'doc'
        assert captures == []


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
        assert j.adopt_recovered(old) is True
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
        assert j.adopt_recovered(tmp_path / 'absent.dvma') is False
        assert j.recovered() is None

    def test_adopt_empty_file_is_noop(self, tmp_path):
        old = tmp_path / 'empty.dvma'
        old.write_bytes(b'')
        j = SessionJournal()
        assert j.adopt_recovered(old) is False
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
        doc, captures, _ = j.state()
        assert doc == b'd%d' % (n - 1)
        # Pending list is consistent (no torn state); exact content
        # depends on interleaving.
        assert all(c.startswith(b'c') for c in captures)
