"""Who owns the synthetic data of a run, and who makes sure it disappears.

Every session this harness creates is named after the run, registered, and
deleted by its exact id when the run ends — including when it ends badly. The
collection it works on is shared with nothing else, but the local MongoDB it
runs against does hold real databases, so nothing here ever drops anything.
"""

from __future__ import annotations

import contextlib
import re
import signal
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from types import FrameType
from typing import Any

# Deleting ids one by one costs a round-trip each, and on DocumentDB that is
# 40-55 ms per document; a batched $in keeps teardown from dominating a run.
_DELETE_BATCH = 500


@dataclass(frozen=True)
class CleanupReport:
    """What teardown did, published in the JSON as evidence, not as a log line."""

    registered: int
    deleted: int
    leftovers: int
    kept: bool = False

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "registered": self.registered,
            "deleted": self.deleted,
            "leftovers": self.leftovers,
            "kept": self.kept,
        }

    def describe(self) -> str:
        if self.kept:
            return f"{self.registered} sessions kept on purpose (--keep-data)"
        line = f"{self.deleted}/{self.registered} synthetic sessions deleted"
        if self.leftovers:
            line += f" — {self.leftovers} LEFT BEHIND, delete them by hand"
        return line


class RunContext:
    """Names the sessions of a run and guarantees their removal.

    Used as a context manager so the removal survives an exception, and with a
    SIGINT/SIGTERM handler because a `finally` does not survive a signal.
    """

    def __init__(
        self,
        collection: Any,
        *,
        run_id: str | None = None,
        keep_data: bool = False,
    ) -> None:
        self._collection = collection
        self.run_id = run_id or (f"{datetime.now(UTC):%Y%m%d}-{uuid.uuid4().hex[:8]}")
        self.prefix = f"bench-{self.run_id}-"
        self.keep_data = keep_data
        self._registered: list[str] = []
        self._previous_handlers: dict[int, Any] = {}
        self.cleanup_report: CleanupReport | None = None

    def session_id(self, scenario_key: str, slot: int) -> str:
        """Id of one concurrency slot of a scenario, registered for deletion.

        The scenario key carries slashes and dots that a MongoDB field path
        would read as syntax; they are flattened here.
        """
        slug = re.sub(r"[^a-z0-9]+", "-", scenario_key.lower()).strip("-")
        session_id = f"{self.prefix}{slug}-{slot}"
        if session_id not in self._registered:
            self._registered.append(session_id)
        return session_id

    def __enter__(self) -> RunContext:
        self._install_signal_handlers()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._restore_signal_handlers()
        self.cleanup()

    def cleanup(self) -> CleanupReport:
        """Deletes every registered id, then proves nothing of this run remains."""
        if self.keep_data:
            self.cleanup_report = CleanupReport(
                registered=len(self._registered),
                deleted=0,
                leftovers=len(self._registered),
                kept=True,
            )
            return self.cleanup_report

        deleted = 0
        for start in range(0, len(self._registered), _DELETE_BATCH):
            batch = self._registered[start : start + _DELETE_BATCH]
            deleted += self._collection.delete_many(
                {"_id": {"$in": batch}}
            ).deleted_count

        self.cleanup_report = CleanupReport(
            registered=len(self._registered),
            deleted=deleted,
            leftovers=self._leftovers(),
        )
        self._registered = []
        return self.cleanup_report

    def _leftovers(self) -> int:
        """Anything still named after this run, registered or not."""
        return self._collection.count_documents(
            {"_id": {"$regex": f"^{re.escape(self.prefix)}"}}
        )

    def _install_signal_handlers(self) -> None:
        def handler(signum: int, frame: FrameType | None) -> None:
            report = self.cleanup()
            print(f"\ninterrupted: {report.describe()}")
            self._restore_signal_handlers()
            signal.raise_signal(signum)

        for signum in (signal.SIGINT, signal.SIGTERM):
            # Only the main thread can install handlers; a run driven from
            # another one still cleans up through __exit__.
            with contextlib.suppress(ValueError):
                self._previous_handlers[signum] = signal.signal(signum, handler)

    def _restore_signal_handlers(self) -> None:
        for signum, previous in self._previous_handlers.items():
            signal.signal(signum, previous)
        self._previous_handlers = {}
