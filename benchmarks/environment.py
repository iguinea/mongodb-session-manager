"""What was on the other end of the connection, and how noisy the path was.

Two runs are only comparable if this matches. A DocumentDB cluster behind an SSH
tunnel and a local MongoDB in Docker produce numbers that are both true and
unrelated, so everything needed to tell them apart travels inside the results
file — and `--compare` refuses to subtract when it differs.
"""

from __future__ import annotations

import platform
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import pymongo
from pymongo.uri_parser import parse_uri

from benchmarks.instruments import Distribution, summarize

# Options worth recording from the URI. Credentials live in the same string and
# are never read, printed or stored.
_URI_OPTIONS = (
    "compressors",
    "readPreference",
    "replicaSet",
    "directConnection",
    "retryWrites",
    "tls",
)

# A run against a tunnelled cluster cannot be compared with a local one, and the
# reader should not have to infer that from the numbers.
_COMPARABILITY_NOTES = (
    "Bytes are re-encoded from the decoded reply: they exclude the OP_MSG header "
    "and do not reflect a negotiated compressor.",
    "Latency includes everything between this process and the server, tunnels "
    "and virtualised Docker networking included.",
)


@dataclass(frozen=True)
class Environment:
    """Everything that makes a run comparable with another one."""

    server_version: str
    engine_hint: str
    topology: str
    set_name: str | None
    max_wire_version: int | None
    read_preference: str
    uri_options: dict[str, Any]
    pool: dict[str, Any]
    pymongo_version: str
    python_version: str
    package_version: str
    label: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "server_version": self.server_version,
            "engine_hint": self.engine_hint,
            "topology": self.topology,
            "set_name": self.set_name,
            "max_wire_version": self.max_wire_version,
            "read_preference": self.read_preference,
            "uri_options": self.uri_options,
            "pool": self.pool,
            "pymongo_version": self.pymongo_version,
            "python_version": self.python_version,
            "package_version": self.package_version,
            "label": self.label,
            "notes": [*_COMPARABILITY_NOTES, *self.notes],
        }

    @property
    def comparability_key(self) -> tuple:
        """What two runs must share before their numbers may be subtracted."""
        return (
            self.engine_hint,
            self.server_version,
            self.topology,
            self.read_preference,
            tuple(self.uri_options.get("compressors") or ()),
        )


def _engine_hint(build_info: dict[str, Any], max_wire_version: int | None) -> str:
    """A label, never a branch.

    Amazon DocumentDB emulates the MongoDB API and reports its own version; it
    does not ship a `gitVersion`. The harness behaves identically either way —
    running the same scenarios on both engines is the point of the issue — so
    this is only here to stop a reader comparing two unrelated runs.
    """
    if "gitVersion" in build_info:
        return "mongodb"
    if max_wire_version is not None and max_wire_version <= 13:
        return "documentdb-or-compatible"
    return "unknown"


def capture(
    client: Any,
    *,
    connection_string: str,
    label: str = "",
    notes: list[str] | None = None,
) -> Environment:
    """Interrogates the server and the driver. Reads no credentials."""
    build_info = client.admin.command("buildInfo")
    hello = client.admin.command("hello")
    pool_options = client.options.pool_options
    uri_options = {
        key: value
        for key, value in parse_uri(connection_string)["options"].items()
        if key in _URI_OPTIONS
    }
    max_wire_version = hello.get("maxWireVersion")

    try:
        package_version = __import__("mongodb_session_manager").__version__
    except Exception:
        package_version = "unknown"

    return Environment(
        server_version=build_info.get("version", "unknown"),
        engine_hint=_engine_hint(build_info, max_wire_version),
        topology=client.topology_description.topology_type_name,
        set_name=hello.get("setName"),
        max_wire_version=max_wire_version,
        read_preference=str(client.read_preference),
        uri_options=uri_options,
        pool={
            "max_pool_size": pool_options.max_pool_size,
            "min_pool_size": pool_options.min_pool_size,
            "wait_queue_timeout": pool_options.wait_queue_timeout,
            "max_idle_time_seconds": pool_options.max_idle_time_seconds,
        },
        pymongo_version=pymongo.version,
        python_version=platform.python_version(),
        package_version=package_version,
        label=label or f"{platform.system()} {platform.machine()} · {sys.platform}",
        notes=notes or [],
    )


def ping_probe(client: Any, samples: int = 20) -> Distribution:
    """Round-trip of an empty command, taken before and after the matrix.

    If it drifts between the two, something outside the benchmark changed —
    a tunnel, a noisy neighbour, a laptop throttling — and the run is not
    comparable with itself, let alone with another one.
    """
    timings = []
    for _ in range(samples):
        started = time.perf_counter()
        client.admin.command("ping")
        timings.append((time.perf_counter() - started) * 1000)
    return summarize(timings)
