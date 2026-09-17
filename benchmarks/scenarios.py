"""What the harness runs, and how much it would cost to run it.

A scenario is one cell of the matrix: an operation, the history it runs against
and how many of them run at once. The cost of a whole run is derived from the
matrix alone, so `--dry-run` answers with the database down.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# Messages each repetition of an operation appends. A supervisor turn writes
# four messages for the supervisor and two for the sub-agent, the shape issue
# #54 measured and `test_write_amplification_integration.py` still pins.
CREATE = "create"
RESTORE = "restore"
SIMPLE_TURN = "turn.simple"
TOOL_TURN = "turn.tool"
SUPERVISOR_TURN = "turn.supervisor"

MESSAGES_PER_REPETITION = {
    CREATE: 2,
    RESTORE: 0,
    SIMPLE_TURN: 2,
    TOOL_TURN: 4,
    SUPERVISOR_TURN: 6,
}

# Above these, a run stops being something you launch by accident: a full matrix
# seeds tens of thousands of messages, and on DocumentDB each write costs 40-55 ms.
MAX_SYNTHETIC_MESSAGES = 20_000
MAX_CONCURRENCY = 8


class LoadTooLarge(RuntimeError):
    """Raised before connecting, when a run would write more than expected."""


@dataclass(frozen=True)
class Scenario:
    """One cell of the matrix."""

    operation: str
    history: int
    concurrency: int = 1

    def __post_init__(self) -> None:
        if self.operation not in MESSAGES_PER_REPETITION:
            raise ValueError(f"unknown operation: {self.operation}")
        if self.history < 0 or self.concurrency < 1:
            raise ValueError("history must be >= 0 and concurrency >= 1")

    @property
    def key(self) -> str:
        """Stable identity used to pair two runs in `--compare`."""
        return f"{self.operation}/h{self.history}/c{self.concurrency}"

    @property
    def messages_per_repetition(self) -> int:
        return MESSAGES_PER_REPETITION[self.operation]

    @property
    def seeded_messages(self) -> int:
        """A session per concurrency slot, each seeded with `history` messages."""
        return self.history * self.concurrency


_FULL_HISTORIES = (10, 100, 1_000, 5_000)
_FULL_TURNS = (SIMPLE_TURN, TOOL_TURN, SUPERVISOR_TURN)


def _smoke() -> list[Scenario]:
    scenarios = [Scenario(operation=CREATE, history=0)]
    for history in (10, 100):
        for operation in (RESTORE, SIMPLE_TURN, SUPERVISOR_TURN):
            scenarios.append(Scenario(operation=operation, history=history))
    return scenarios


def _full() -> list[Scenario]:
    scenarios = [Scenario(operation=CREATE, history=0)]
    for history in _FULL_HISTORIES:
        for operation in (RESTORE, *_FULL_TURNS):
            for concurrency in (1, 4, 16):
                scenarios.append(
                    Scenario(
                        operation=operation, history=history, concurrency=concurrency
                    )
                )
    return scenarios


_PROFILES = {"smoke": _smoke, "full": _full}


def build_matrix(
    profile: str,
    *,
    histories: Iterable[int] | None = None,
    operations: Iterable[str] | None = None,
    concurrencies: Iterable[int] | None = None,
) -> list[Scenario]:
    """Scenarios of a profile, narrowed by the filters the CLI passes through."""
    if profile not in _PROFILES:
        raise ValueError(
            f"unknown profile: {profile}. Available: {', '.join(sorted(_PROFILES))}"
        )
    scenarios = _PROFILES[profile]()

    if histories is not None:
        wanted = set(histories)
        scenarios = [s for s in scenarios if s.history in wanted]
    if operations is not None:
        wanted_ops = set(operations)
        scenarios = [s for s in scenarios if s.operation in wanted_ops]
    if concurrencies is not None:
        wanted_concurrency = set(concurrencies)
        scenarios = [s for s in scenarios if s.concurrency in wanted_concurrency]

    if not scenarios:
        raise ValueError(f"no scenario in profile '{profile}' matches those filters")
    return scenarios


@dataclass(frozen=True)
class RunPlan:
    """What a run would do, known before anything connects."""

    scenarios: list[Scenario]
    warmups: int
    repetitions: int
    volume_repetitions: int
    synthetic_messages: int

    def describe(self) -> str:
        lines = [
            f"{len(self.scenarios)} scenarios, "
            f"{self.warmups} warmups + {self.repetitions} timed + "
            f"{self.volume_repetitions} volume repetitions each",
            f"{self.synthetic_messages:,} synthetic messages will be written",
            "",
        ]
        lines.extend(
            f"  {s.key:<28} seeded={s.seeded_messages:>7,}  "
            f"per_repetition={s.messages_per_repetition}"
            for s in self.scenarios
        )
        return "\n".join(lines)


def plan_run(
    scenarios: list[Scenario],
    *,
    warmups: int,
    repetitions: int,
    volume_repetitions: int = 0,
    allow_large: bool,
) -> RunPlan:
    """Cost of a run, refusing it when it is larger than anyone meant to launch."""
    passes = warmups + repetitions + volume_repetitions
    synthetic = sum(
        s.seeded_messages + passes * s.concurrency * s.messages_per_repetition
        for s in scenarios
    )
    peak_concurrency = max(s.concurrency for s in scenarios)

    if not allow_large:
        reasons = []
        if synthetic > MAX_SYNTHETIC_MESSAGES:
            reasons.append(
                f"{synthetic:,} synthetic messages (limit {MAX_SYNTHETIC_MESSAGES:,})"
            )
        if peak_concurrency > MAX_CONCURRENCY:
            reasons.append(f"concurrency {peak_concurrency} (limit {MAX_CONCURRENCY})")
        if reasons:
            raise LoadTooLarge(
                f"this run would write {' and '.join(reasons)} across "
                f"{len(scenarios)} scenarios. Re-run with --allow-large if that "
                "is what you meant, or narrow it with --history/--operation."
            )

    return RunPlan(
        scenarios=scenarios,
        warmups=warmups,
        repetitions=repetitions,
        volume_repetitions=volume_repetitions,
        synthetic_messages=synthetic,
    )
