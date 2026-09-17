"""The scenario matrix and the guardrails that keep a run from surprising you (#60).

The cost of a run is computed before anything connects: a full matrix seeds tens
of thousands of synthetic messages, and against DocumentDB every write costs
40-55 ms. Finding that out halfway through is finding it out too late.
"""

from __future__ import annotations

import pytest

from benchmarks.scenarios import (
    LoadTooLarge,
    Scenario,
    build_matrix,
    plan_run,
)

PASSES = {"warmups": 5, "repetitions": 30, "volume_repetitions": 3}


class TestGuardrails:
    def test_large_history_requires_allow_large(self):
        scenarios = build_matrix("full")

        with pytest.raises(LoadTooLarge, match="--allow-large"):
            plan_run(scenarios, allow_large=False, **PASSES)

    def test_high_concurrency_requires_allow_large(self):
        scenarios = [Scenario(operation="turn.simple", history=10, concurrency=16)]

        with pytest.raises(LoadTooLarge, match="--allow-large"):
            plan_run(scenarios, allow_large=False, **PASSES)

    def test_allow_large_lets_the_full_matrix_through(self):
        plan = plan_run(build_matrix("full"), allow_large=True, **PASSES)

        assert plan.synthetic_messages > 20_000

    def test_the_smoke_profile_needs_no_permission(self):
        plan = plan_run(build_matrix("smoke"), allow_large=False, **PASSES)

        assert plan.scenarios
        assert plan.synthetic_messages <= 20_000

    def test_the_refusal_names_what_would_have_run(self):
        """A guardrail that does not say what it stopped just gets disabled."""
        with pytest.raises(LoadTooLarge) as refusal:
            plan_run(build_matrix("full"), allow_large=False, **PASSES)

        assert "synthetic messages" in str(refusal.value)


class TestCost:
    def test_the_cost_is_known_before_touching_the_database(self):
        """plan_run() takes no client: --dry-run must work with MongoDB down."""
        scenarios = [Scenario(operation="turn.simple", history=100, concurrency=1)]

        plan = plan_run(scenarios, allow_large=False, warmups=1, repetitions=2)

        # 100 seeded, plus 3 repetitions of a two-message turn.
        assert plan.synthetic_messages == 106

    def test_a_restore_writes_nothing_beyond_its_history(self):
        scenarios = [Scenario(operation="restore", history=100, concurrency=1)]

        plan = plan_run(scenarios, allow_large=False, warmups=1, repetitions=2)

        assert plan.synthetic_messages == 100

    def test_concurrency_multiplies_sessions_and_turns(self):
        scenarios = [Scenario(operation="turn.simple", history=10, concurrency=4)]

        plan = plan_run(scenarios, allow_large=True, warmups=1, repetitions=2)

        assert plan.synthetic_messages == 4 * 10 + 3 * 4 * 2

    def test_a_supervisor_turn_costs_six_messages(self):
        """Four from the supervisor and two from the sub-agent, as #54 measured."""
        scenarios = [Scenario(operation="turn.supervisor", history=0, concurrency=1)]

        plan = plan_run(scenarios, allow_large=False, warmups=0, repetitions=1)

        assert plan.synthetic_messages == 6


class TestMatrix:
    def test_the_full_matrix_covers_the_history_sizes_of_the_issue(self):
        histories = {s.history for s in build_matrix("full")}

        assert {10, 100, 1_000, 5_000} <= histories

    def test_the_full_matrix_covers_every_turn_shape(self):
        operations = {s.operation for s in build_matrix("full")}

        assert {
            "create",
            "restore",
            "turn.simple",
            "turn.tool",
            "turn.supervisor",
        } <= operations

    def test_the_full_matrix_grows_concurrency(self):
        concurrencies = {s.concurrency for s in build_matrix("full")}

        assert len(concurrencies) > 1

    def test_filters_select_a_subset(self):
        selected = build_matrix("full", histories=[10], operations=["turn.simple"])

        assert selected
        assert all(s.history == 10 for s in selected)
        assert all(s.operation == "turn.simple" for s in selected)

    def test_a_filter_that_matches_nothing_is_an_error(self):
        with pytest.raises(ValueError, match="no scenario"):
            build_matrix("smoke", histories=[9_999])

    def test_scenario_keys_are_unique_and_stable(self):
        """--compare pairs runs by this key, so it may not drift."""
        scenarios = build_matrix("full")
        keys = [s.key for s in scenarios]

        assert len(keys) == len(set(keys))
        assert "turn.simple/h100/c1" in keys

    def test_an_unknown_profile_is_an_error(self):
        with pytest.raises(ValueError, match="unknown profile"):
            build_matrix("everything")

    def test_there_is_no_profile_that_pretends_to_saturate_the_pool(self):
        """A saturation profile was tried and removed: measured on a local
        MongoDB, a four-connection pool driven by sixteen concurrent invocations
        still waited 0 ms. One event loop plus a synchronous driver never has two
        checkouts in flight, so nothing from a single worker can saturate it. The
        probe stays, and reports that zero with its reason."""
        with pytest.raises(ValueError, match="unknown profile"):
            build_matrix("pool")
