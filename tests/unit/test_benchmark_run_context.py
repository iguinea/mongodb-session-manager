"""Isolation and removal of the synthetic data a run creates (issue #60).

"Temporary data is removed even on error" is an acceptance criterion, and the
testing guide is explicit about how: unique ids, deleted by exact id in a
`finally`, never dropping a shared database or collection
(`docs/development/testing.md:601-603`). The local MongoDB this runs against
holds real databases next to the benchmark one.

Driven against a double, so the rule is pinned without a server.
"""

from __future__ import annotations

import re

import pytest

from benchmarks.run_context import RunContext


class FakeCollection:
    """Enough of a pymongo collection to prove what the context deletes."""

    def __init__(self) -> None:
        self.documents: dict[str, dict] = {}
        self.dropped = False
        self.deleted_queries: list[dict] = []

    def insert(self, session_id: str) -> None:
        self.documents[session_id] = {"_id": session_id}

    def delete_many(self, query: dict):
        self.deleted_queries.append(query)
        ids = query["_id"]["$in"]
        removed = 0
        for session_id in ids:
            if self.documents.pop(session_id, None) is not None:
                removed += 1
        return type("Result", (), {"deleted_count": removed})()

    def count_documents(self, query: dict) -> int:
        pattern = re.compile(query["_id"]["$regex"])
        return sum(1 for key in self.documents if pattern.match(key))

    def drop(self) -> None:  # pragma: no cover - must never be called
        self.dropped = True


class TestCleanup:
    def test_ids_are_deleted_even_when_the_workload_raises(self):
        collection = FakeCollection()

        with (
            pytest.raises(RuntimeError, match="boom"),
            RunContext(collection) as run,
        ):
            collection.insert(run.session_id("turn.simple/h10/c1", 0))
            collection.insert(run.session_id("turn.simple/h10/c1", 1))
            raise RuntimeError("boom")

        assert collection.documents == {}

    def test_cleanup_reports_what_it_deleted(self):
        collection = FakeCollection()

        with RunContext(collection) as run:
            collection.insert(run.session_id("restore/h10/c1", 0))
            collection.insert(run.session_id("restore/h10/c1", 1))

        assert run.cleanup_report.registered == 2
        assert run.cleanup_report.deleted == 2
        assert run.cleanup_report.leftovers == 0

    def test_leftovers_are_reported_not_swallowed(self):
        """A document this run created and could not delete is a finding, and
        the JSON says so instead of the summary looking clean."""
        collection = FakeCollection()

        with RunContext(collection) as run:
            collection.insert(run.session_id("restore/h10/c1", 0))
            # Something the run created without registering it.
            collection.insert(f"bench-{run.run_id}-stray")

        assert run.cleanup_report.leftovers == 1

    def test_cleanup_deletes_by_exact_id_and_never_drops(self):
        collection = FakeCollection()

        with RunContext(collection) as run:
            collection.insert(run.session_id("restore/h10/c1", 0))

        assert collection.dropped is False
        assert list(collection.deleted_queries[0]) == ["_id"]
        assert "$in" in collection.deleted_queries[0]["_id"]

    def test_other_sessions_are_left_alone(self):
        collection = FakeCollection()
        collection.insert("a-real-session")

        with RunContext(collection) as run:
            collection.insert(run.session_id("restore/h10/c1", 0))

        assert "a-real-session" in collection.documents

    def test_keep_data_leaves_the_documents(self):
        collection = FakeCollection()

        with RunContext(collection, keep_data=True) as run:
            session_id = run.session_id("restore/h10/c1", 0)
            collection.insert(session_id)

        assert session_id in collection.documents
        assert run.cleanup_report.kept is True
        assert run.cleanup_report.deleted == 0

    def test_cleanup_is_idempotent(self):
        collection = FakeCollection()

        with RunContext(collection) as run:
            collection.insert(run.session_id("restore/h10/c1", 0))
        second = run.cleanup()

        assert second.deleted == 0
        assert second.leftovers == 0


class TestIdentity:
    def test_session_ids_are_namespaced_by_run(self):
        run = RunContext(FakeCollection())

        session_id = run.session_id("turn.simple/h10/c1", 0)

        assert session_id.startswith(f"bench-{run.run_id}-")

    def test_two_runs_do_not_share_ids(self):
        first = RunContext(FakeCollection())
        second = RunContext(FakeCollection())

        assert first.run_id != second.run_id
        assert first.session_id("restore/h10/c1", 0) != second.session_id(
            "restore/h10/c1", 0
        )

    def test_the_same_slot_asked_twice_is_the_same_session(self):
        """Repetitions reuse the session of their slot; only `create` needs new
        ones, and it asks for a new slot."""
        run = RunContext(FakeCollection())

        assert run.session_id("turn.simple/h10/c1", 2) == run.session_id(
            "turn.simple/h10/c1", 2
        )

    def test_an_id_survives_a_scenario_key_with_slashes_and_dots(self):
        run = RunContext(FakeCollection())

        session_id = run.session_id("turn.supervisor/h5000/c16", 3)

        assert "/" not in session_id
        assert session_id.count(".") == 0

    def test_every_id_handed_out_is_registered_for_deletion(self):
        collection = FakeCollection()
        run = RunContext(collection)
        for slot in range(3):
            collection.insert(run.session_id("restore/h10/c1", slot))

        report = run.cleanup()

        assert report.registered == 3
        assert report.deleted == 3
