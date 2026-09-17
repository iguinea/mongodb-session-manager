"""Turning measurements into something a person and a diff can both read.

The JSON is the artifact: it carries the environment that makes it comparable,
the checks that make it credible and the numbers themselves. The text summary is
a convenience printed on top of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = 1

# What two runs must share before one may be subtracted from the other.
_COMPARABILITY_FIELDS = ("engine_hint", "server_version", "topology", "read_preference")


@dataclass
class ScenarioResult:
    """Everything one cell of the matrix produced."""

    scenario: str
    operation: str
    history: int
    concurrency: int
    latency: dict[str, Any]
    warmup: dict[str, Any] | None
    commands: dict[str, Any]
    server_ms: dict[str, Any]
    bytes: dict[str, int]
    pool: dict[str, Any]
    loop_lag: dict[str, Any] | None
    errors: int
    checks: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.checks

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "operation": self.operation,
            "history": self.history,
            "concurrency": self.concurrency,
            "latency": self.latency,
            "warmup": self.warmup,
            "commands": self.commands,
            "server_ms": self.server_ms,
            "bytes": self.bytes,
            "pool": self.pool,
            "loop_lag": self.loop_lag,
            "errors": self.errors,
            "checks": self.checks,
            "passed": self.passed,
        }


def build_document(
    *,
    run_id: str,
    environment: dict[str, Any],
    config: dict[str, Any],
    results: list[ScenarioResult],
    cleanup: dict[str, Any],
    ping_before: dict[str, Any],
    ping_after: dict[str, Any],
) -> dict[str, Any]:
    """The results file. `schema_version` is what a future reader checks first."""
    return {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "run_id": run_id,
            "finished_at": datetime.now(UTC).isoformat(),
            "ping_before": ping_before,
            "ping_after": ping_after,
        },
        "environment": environment,
        "config": config,
        "cleanup": cleanup,
        "results": [result.as_dict() for result in results],
        "failed_checks": [
            {"scenario": result.scenario, "reasons": result.checks}
            for result in results
            if not result.passed
        ],
    }


SATURATION_LEGEND = (
    "* the sample is too small to tell this percentile from the maximum; "
    "raise --repetitions (100 for a p99, 20 for a p95)"
)


def _marked(distribution: dict[str, Any], name: str) -> str:
    """One percentile, marked when the sample size cannot resolve it."""
    mark = "*" if name in (distribution.get("saturated") or []) else ""
    return f"{distribution.get(f'{name}_ms', 0):.1f}{mark}"


def _cell(latency: dict[str, Any], name: str) -> str:
    mark = "*" if name in (latency.get("saturated") or []) else ""
    return f"{latency.get(f'{name}_ms', 0):>9.3f}{mark:<1}"


def _any_saturated(document: dict[str, Any]) -> bool:
    """Whether any number in the summary carries the mark."""
    for result in document["results"]:
        parts = [
            result["latency"],
            (result.get("loop_lag") or {}).get("lag"),
            (result.get("loop_lag") or {}).get("baseline"),
            result.get("pool", {}).get("wait"),
        ]
        if any(part and part.get("saturated") for part in parts):
            return True
    return False


def _row(label: str, latency: dict[str, Any], extra: str) -> str:
    cells = "".join(_cell(latency, name) for name in ("p50", "p95", "p99"))
    return f"  {label:<26}{cells}  {extra}"


def human_summary(document: dict[str, Any]) -> str:
    """The same numbers as the JSON, for the terminal that launched the run."""
    environment = document["environment"]
    lines = [
        "",
        f"run {document['run']['run_id']} · {environment['engine_hint']} "
        f"{environment['server_version']} · {environment['topology']} · "
        f"read {environment['read_preference']}",
        f"  {'scenario':<26}{'p50':>9}{'p95':>9}{'p99':>9}  commands / bytes",
        f"  {'-' * 70}",
    ]
    for result in document["results"]:
        commands = result["commands"]
        extra = (
            f"{commands.get('per_operation', 0):.1f} cmd/op, "
            f"{result['bytes'].get('reply', 0):,} B reply"
        )
        lines.append(_row(result["scenario"], result["latency"], extra))
        lag = result["loop_lag"] or {}
        if lag.get("lag"):
            lines.append(
                f"  {'':<26}event-loop lag p99 {_marked(lag['lag'], 'p99')} ms "
                f"(idle baseline p99 {_marked(lag['baseline'], 'p99')} ms)"
            )
        elif lag.get("reason"):
            lines.append(f"  {'':<26}event-loop lag not measured: {lag['reason']}")
        if result["pool"].get("wait"):
            wait = result["pool"]["wait"]
            lines.append(
                f"  {'':<26}pool wait p99 {_marked(wait, 'p99')} ms, "
                f"{result['pool'].get('timeouts', 0)} timeouts"
            )

    if _any_saturated(document):
        lines.append("")
        lines.append(f"  {SATURATION_LEGEND}")

    failed = document["failed_checks"]
    lines.append("")
    if failed:
        lines.append("FAILED — the run did not prove it did the work:")
        lines.extend(
            f"  {entry['scenario']}: {reason}"
            for entry in failed
            for reason in entry["reasons"]
        )
    else:
        lines.append("every scenario proved the work it measured")
    lines.append(f"cleanup: {document['cleanup'].get('describe', '')}")
    return "\n".join(lines)


@dataclass(frozen=True)
class ComparisonRow:
    """One scenario, seen in both runs."""

    scenario: str
    base_p50: float | None
    head_p50: float | None
    base_p95: float | None
    head_p95: float | None
    base_bytes: int | None
    head_bytes: int | None
    p50_change_pct: float | None


@dataclass(frozen=True)
class Comparison:
    """Two runs next to each other, with deltas only when they are comparable."""

    rows: list[ComparisonRow]
    comparable: bool
    differences: dict[str, tuple[Any, Any]]

    def describe(self) -> str:
        lines = [""]
        if not self.comparable:
            lines.append("NOT COMPARABLE — showing both runs side by side.")
            lines.extend(
                f"  {name}: base={base!r} head={head!r}"
                for name, (base, head) in self.differences.items()
            )
            lines.append("")
        header = f"  {'scenario':<26}{'base p50':>11}{'head p50':>11}"
        lines.append(header if not self.comparable else f"{header}{'change':>10}")
        lines.append(f"  {'-' * (len(header) + 8)}")
        for row in self.rows:
            base = "—" if row.base_p50 is None else f"{row.base_p50:.3f}"
            head = "—" if row.head_p50 is None else f"{row.head_p50:.3f}"
            line = f"  {row.scenario:<26}{base:>11}{head:>11}"
            if row.p50_change_pct is not None:
                line += f"{row.p50_change_pct:>9.1f}%"
            lines.append(line)
        return "\n".join(lines)


def _comparability(base: dict[str, Any], head: dict[str, Any]) -> dict[str, tuple]:
    """Names every environment field that stops these two runs from subtracting."""
    differences = {}
    for name in _COMPARABILITY_FIELDS:
        if base.get(name) != head.get(name):
            differences[name] = (base.get(name), head.get(name))

    base_compressors = (base.get("uri_options") or {}).get("compressors")
    head_compressors = (head.get("uri_options") or {}).get("compressors")
    if base_compressors != head_compressors:
        differences["compressors"] = (base_compressors, head_compressors)
    return differences


def compare_runs(base: dict[str, Any], head: dict[str, Any]) -> Comparison:
    """Pairs two result files by scenario key.

    A delta between a local MongoDB and a tunnelled DocumentDB would be a number
    with no meaning: when the environments differ, both columns are printed and
    no change is computed.
    """
    differences = _comparability(base["environment"], head["environment"])
    comparable = not differences

    base_results = {r["scenario"]: r for r in base["results"]}
    head_results = {r["scenario"]: r for r in head["results"]}

    rows = []
    for scenario in sorted(base_results.keys() | head_results.keys()):
        in_base = base_results.get(scenario)
        in_head = head_results.get(scenario)
        base_p50 = in_base["latency"]["p50_ms"] if in_base else None
        head_p50 = in_head["latency"]["p50_ms"] if in_head else None
        change = None
        if comparable and base_p50 and head_p50 is not None:
            change = (head_p50 - base_p50) / base_p50 * 100
        rows.append(
            ComparisonRow(
                scenario=scenario,
                base_p50=base_p50,
                head_p50=head_p50,
                base_p95=in_base["latency"]["p95_ms"] if in_base else None,
                head_p95=in_head["latency"]["p95_ms"] if in_head else None,
                base_bytes=(in_base or {}).get("bytes", {}).get("reply"),
                head_bytes=(in_head or {}).get("bytes", {}).get("reply"),
                p50_change_pct=change,
            )
        )
    return Comparison(rows=rows, comparable=comparable, differences=differences)
