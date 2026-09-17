"""Proof that a scenario did the work whose cost it reports.

A benchmark that measures nothing still prints a number. This module is what
turns that number into a claim: every scenario declares what must have happened,
and a run that cannot show it exits non-zero.

What is checked is work done, never a ceiling on commands. The ceiling belongs to
`tests/integration/test_write_amplification_integration.py`, which owns the
budget of a turn and the history of how it got there.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from benchmarks.scenarios import Scenario

WRITE_COMMANDS = frozenset({"update", "insert", "findAndModify", "delete"})
READ_COMMANDS = frozenset({"find", "aggregate", "getMore", "count", "distinct"})


@dataclass(frozen=True)
class Expectation:
    """What a scenario must have done for its numbers to mean anything."""

    messages_written: int
    completed_repetitions: int
    requires_write: bool
    requires_read: bool
    requires_metrics: bool


@dataclass(frozen=True)
class Observation:
    """What the scenario actually did, as seen from the probes and the database."""

    messages_written: int
    commands: dict[str, int]
    failures: int
    completed_repetitions: int
    last_messages_have_metrics: bool = True
    notes: list[str] = field(default_factory=list)


def expectation_for(scenario: Scenario, *, repetitions: int) -> Expectation:
    """Derives from the scenario what its run must be able to show."""
    writes = scenario.messages_per_repetition > 0
    return Expectation(
        messages_written=(
            scenario.messages_per_repetition * scenario.concurrency * repetitions
        ),
        completed_repetitions=repetitions,
        requires_write=writes,
        # A turn measures the invocation on an already restored agent, so reads
        # are not guaranteed inside its window; a restore is nothing but reads.
        requires_read=scenario.operation == "restore",
        requires_metrics=writes,
    )


def check(expectation: Expectation, observation: Observation) -> list[str]:
    """Reasons the scenario failed to prove its work. Empty means it proved it."""
    reasons: list[str] = []
    commands = observation.commands

    if not commands:
        reasons.append("no commands reached the server inside the measured window")

    if expectation.requires_write and not any(
        commands.get(name, 0) for name in WRITE_COMMANDS
    ):
        reasons.append(f"no write command was issued: {sorted(commands)}")

    if expectation.requires_read and not any(
        commands.get(name, 0) for name in READ_COMMANDS
    ):
        reasons.append(f"no read command was issued: {sorted(commands)}")

    if observation.messages_written != expectation.messages_written:
        reasons.append(
            f"{observation.messages_written} messages were persisted, "
            f"{expectation.messages_written} expected"
        )

    if observation.completed_repetitions != expectation.completed_repetitions:
        reasons.append(
            f"{observation.completed_repetitions} repetitions completed, "
            f"{expectation.completed_repetitions} expected"
        )

    if observation.failures:
        reasons.append(f"{observation.failures} commands failed")

    if commands.get("createIndexes"):
        reasons.append(
            "createIndexes ran inside the measured window: the sample is cold, "
            "not the warm connection this benchmark reports"
        )

    if expectation.requires_metrics and not observation.last_messages_have_metrics:
        reasons.append(
            "the last message of an agent carries no metrics: the invocation "
            "never closed (#66), so the turn was cut short"
        )

    return reasons
