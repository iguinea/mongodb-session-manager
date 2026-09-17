"""What a scenario must have done for its numbers to mean anything (issue #60).

This is the acceptance criterion of the issue — "the benchmark does real work and
fails if the expected operations do not run" — and it is also the reason #60
exists: `examples/example_performance.py` counted ten operations per session
while its loop body was `pass`.

The contract deliberately checks work done, never a ceiling on commands. The
ceiling lives in `test_write_amplification_integration.py`, where it has its
history written down; duplicating it here would make every performance sub-issue
of #56 update two places, and would turn this harness red for the one reason it
should stay green: an optimisation landing.
"""

from __future__ import annotations

from benchmarks.invariants import Observation, check, expectation_for
from benchmarks.scenarios import Scenario


def _turn_scenario(**overrides) -> Scenario:
    fields = {"operation": "turn.simple", "history": 10, "concurrency": 1}
    fields.update(overrides)
    return Scenario(**fields)


def _healthy_observation(**overrides) -> Observation:
    fields = {
        "messages_written": 6,
        "commands": {"update": 6, "find": 3},
        "failures": 0,
        "completed_repetitions": 3,
        "last_messages_have_metrics": True,
    }
    fields.update(overrides)
    return Observation(**fields)


class TestWorkWasDone:
    def test_everything_in_order_passes(self):
        expectation = expectation_for(_turn_scenario(), repetitions=3)

        assert check(expectation, _healthy_observation()) == []

    def test_fewer_commands_than_the_previous_run_does_not_fail(self):
        """The whole point of #56 is to issue fewer commands. A harness that
        failed when that happened would be a harness nobody runs twice."""
        expectation = expectation_for(_turn_scenario(), repetitions=3)

        reasons = check(
            expectation, _healthy_observation(commands={"update": 1, "find": 1})
        )

        assert reasons == []

    def test_a_workload_that_wrote_nothing_fails(self):
        """The bug that motivated the issue: a loop body of `pass`."""
        expectation = expectation_for(_turn_scenario(), repetitions=3)

        reasons = check(
            expectation, _healthy_observation(messages_written=0, commands={})
        )

        assert reasons
        assert any("no commands" in reason for reason in reasons)

    def test_missing_messages_fail_even_when_commands_ran(self):
        expectation = expectation_for(_turn_scenario(), repetitions=3)

        reasons = check(expectation, _healthy_observation(messages_written=4))

        assert any("4" in reason and "6" in reason for reason in reasons)

    def test_a_turn_must_write(self):
        expectation = expectation_for(_turn_scenario(), repetitions=3)

        reasons = check(
            expectation,
            _healthy_observation(commands={"find": 3}, messages_written=6),
        )

        assert any("write" in reason for reason in reasons)

    def test_a_restore_must_read_and_writes_nothing(self):
        expectation = expectation_for(
            _turn_scenario(operation="restore"), repetitions=3
        )

        assert expectation.messages_written == 0
        reasons = check(
            expectation,
            _healthy_observation(
                messages_written=0, commands={"aggregate": 3, "find": 3}
            ),
        )
        assert reasons == []

    def test_a_restore_without_reads_fails(self):
        expectation = expectation_for(
            _turn_scenario(operation="restore"), repetitions=3
        )

        reasons = check(
            expectation,
            _healthy_observation(messages_written=0, commands={"update": 1}),
        )

        assert any("read" in reason for reason in reasons)


class TestTheRunWasClean:
    def test_a_partial_run_fails(self):
        """Silently dropping repetitions would quietly narrow the sample."""
        expectation = expectation_for(_turn_scenario(), repetitions=3)

        reasons = check(expectation, _healthy_observation(completed_repetitions=2))

        assert any("repetition" in reason for reason in reasons)

    def test_command_failures_fail_the_scenario(self):
        expectation = expectation_for(_turn_scenario(), repetitions=3)

        reasons = check(expectation, _healthy_observation(failures=1))

        assert any("failed" in reason for reason in reasons)

    def test_creating_indexes_inside_the_window_fails(self):
        """The measured window must run on a warm connection: an index created
        there means the warmups did not do their job, and the sample is cold."""
        expectation = expectation_for(_turn_scenario(), repetitions=3)

        reasons = check(
            expectation,
            _healthy_observation(commands={"update": 6, "createIndexes": 1}),
        )

        assert any("createIndexes" in reason for reason in reasons)

    def test_a_turn_whose_invocation_did_not_close_fails(self):
        """Metrics land on the last message when the invocation closes (#66).
        Their absence means the turn was cut short, whatever the timings say."""
        expectation = expectation_for(_turn_scenario(), repetitions=3)

        reasons = check(
            expectation, _healthy_observation(last_messages_have_metrics=False)
        )

        assert any("metrics" in reason for reason in reasons)

    def test_a_restore_is_not_asked_for_turn_metrics(self):
        expectation = expectation_for(
            _turn_scenario(operation="restore"), repetitions=3
        )

        reasons = check(
            expectation,
            _healthy_observation(
                messages_written=0,
                commands={"aggregate": 3},
                last_messages_have_metrics=False,
            ),
        )

        assert reasons == []


class TestExpectation:
    def test_messages_expected_follow_the_scenario_and_the_repetitions(self):
        expectation = expectation_for(
            _turn_scenario(operation="turn.supervisor", concurrency=4), repetitions=5
        )

        assert expectation.messages_written == 6 * 4 * 5

    def test_every_repetition_must_complete(self):
        expectation = expectation_for(_turn_scenario(concurrency=4), repetitions=5)

        assert expectation.completed_repetitions == 5
