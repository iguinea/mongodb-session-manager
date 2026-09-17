"""Sample statistics of the benchmark harness (issue #60).

Two decisions are pinned here because they are what makes a run comparable with
another one:

- Warmup repetitions never reach the percentiles. They exist to fill the
  connection pool and the WiredTiger cache, so counting them would report the
  cost of starting up as if it were the steady state.
- Percentiles use nearest-rank on the sorted sample. With 30 repetitions an
  interpolated p99 is an invention: nearest-rank returns an observation that
  actually happened.
"""

from __future__ import annotations

import pytest

from benchmarks.instruments import Samples, summarize


class TestWarmup:
    def test_warmup_samples_are_excluded_from_percentiles(self):
        samples = Samples(warmups=2)
        for value in (1000.0, 900.0, 1.0, 2.0, 3.0):
            samples.record(value)

        measured = samples.summary()
        assert measured.n == 3
        assert measured.min_ms == pytest.approx(1.0)
        assert measured.max_ms == pytest.approx(3.0)
        assert measured.p50_ms == pytest.approx(2.0)

    def test_warmup_is_reported_on_its_own(self):
        """The issue asks to separate warmup time, not to throw it away."""
        samples = Samples(warmups=2)
        for value in (1000.0, 900.0, 1.0, 2.0, 3.0):
            samples.record(value)

        assert samples.warmup_summary().n == 2
        assert samples.warmup_summary().max_ms == pytest.approx(1000.0)

    def test_completed_counts_every_repetition(self):
        """Guards against a silently partial run: the invariant compares this."""
        samples = Samples(warmups=2)
        for value in (1.0, 2.0, 3.0, 4.0):
            samples.record(value)

        assert samples.completed == 4

    def test_a_run_without_measured_samples_has_no_summary(self):
        samples = Samples(warmups=2)
        samples.record(1.0)

        with pytest.raises(ValueError, match="no measured samples"):
            samples.summary()


class TestPercentiles:
    def test_nearest_rank_returns_an_observed_value(self):
        values = [float(v) for v in range(1, 101)]

        distribution = summarize(values)

        assert distribution.p50_ms == pytest.approx(50.0)
        assert distribution.p95_ms == pytest.approx(95.0)
        assert distribution.p99_ms == pytest.approx(99.0)
        assert distribution.min_ms == pytest.approx(1.0)
        assert distribution.max_ms == pytest.approx(100.0)
        assert distribution.n == 100

    def test_order_of_arrival_does_not_matter(self):
        ordered = summarize([1.0, 2.0, 3.0, 4.0, 5.0])
        shuffled = summarize([4.0, 1.0, 5.0, 3.0, 2.0])

        assert ordered == shuffled

    def test_a_single_sample_is_every_percentile(self):
        distribution = summarize([7.5])

        assert distribution.n == 1
        assert distribution.min_ms == pytest.approx(7.5)
        assert distribution.p99_ms == pytest.approx(7.5)
        assert distribution.max_ms == pytest.approx(7.5)

    def test_summarizing_nothing_raises(self):
        with pytest.raises(ValueError, match="no measured samples"):
            summarize([])

    def test_a_distribution_reports_no_mean(self):
        """Means hide the tail this benchmark exists to expose."""
        distribution = summarize([1.0, 2.0, 300.0])

        assert not hasattr(distribution, "mean_ms")
