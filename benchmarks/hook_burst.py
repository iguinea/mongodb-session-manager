"""What a burst of hook events costs, by dispatch path (#62).

The rest of this package measures MongoDB. This module measures the other side
of a metadata write: the notification the hook sends afterwards, which travels
in the background and used to bring a thread of its own with it.

It needs no database. Run it with:

    uv run python -m benchmarks.hook_burst
    uv run python -m benchmarks.hook_burst --burst 500 --work-ms 20

Paths measured:

- `legacy`: what `dispatch_async()` did before #62 — one daemon thread with an
  event loop of its own per event. Reproduced here, not imported, so the two
  can be compared in the same process on the same machine.
- `reserve`: today's path when there is no loop to dispatch to. One shared loop.
- `bound`: a loop passed explicitly, the FastAPI lifespan case.

The work each event does is the shape the bundled hooks have: an
`asyncio.to_thread` around a blocking call, which is what a boto3 call is.
"""

import argparse
import asyncio
import statistics
import sys
import threading
import time

from mongodb_session_manager.hooks.background_work import BackgroundWork

DEFAULT_BURST = 200
DEFAULT_WORK_MS = 50.0
# Percentile of the dispatch cost, which is what the caller actually pays.
_P99 = 0.99


class _BlockingCall:
    """Stands in for the boto3 call: blocks its thread, counts its overlap."""

    def __init__(self, seconds: float) -> None:
        self._seconds = seconds
        self._lock = threading.Lock()
        self._running = 0
        self.peak_concurrent = 0

    def __call__(self) -> None:
        with self._lock:
            self._running += 1
            self.peak_concurrent = max(self.peak_concurrent, self._running)
        time.sleep(self._seconds)
        with self._lock:
            self._running -= 1


def _legacy_dispatch(coro) -> None:
    """The pre-#62 fallback: a daemon thread with a loop of its own, per event."""
    threading.Thread(target=asyncio.run, args=(coro,), daemon=True).start()


def _settle(baseline: int, timeout: float = 30.0) -> None:
    """Wait for the threads of the previous path to die before measuring."""
    deadline = time.time() + timeout
    while time.time() < deadline and threading.active_count() > baseline:
        time.sleep(0.05)


def measure(path: str, burst: int, work_seconds: float, quiet_threads: int) -> dict:
    """Run one burst through one dispatch path and return what it cost."""
    call = _BlockingCall(work_seconds)
    done = [threading.Event() for _ in range(burst)]
    latencies: list[float] = []
    peak_threads = quiet_threads

    async def notify(index: int) -> None:
        await asyncio.to_thread(call)
        done[index].set()

    work = None
    loop = None
    loop_thread = None
    if path == "bound":
        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
        loop_thread.start()
    if path in ("reserve", "bound"):
        work = BackgroundWork(max_in_flight=burst)

    started = time.perf_counter()
    for index in range(burst):
        at = time.perf_counter()
        if work is None:
            _legacy_dispatch(notify(index))
        else:
            work.submit(notify(index), "probing a burst", loop)
        latencies.append(time.perf_counter() - at)
        peak_threads = max(peak_threads, threading.active_count())

    deadline = time.time() + 120
    while time.time() < deadline and not all(event.is_set() for event in done):
        peak_threads = max(peak_threads, threading.active_count())
        time.sleep(0.002)
    drained_ms = (time.perf_counter() - started) * 1e3

    if work is not None:
        work.shutdown(timeout=10.0)
    if loop is not None and loop_thread is not None:
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        loop.close()
    _settle(quiet_threads)

    ordered = sorted(latencies)
    return {
        "path": path,
        "threads_added": peak_threads - quiet_threads,
        "peak_concurrent_calls": call.peak_concurrent,
        "dispatch_p50_us": statistics.median(latencies) * 1e6,
        "dispatch_p99_us": ordered[max(int(len(ordered) * _P99) - 1, 0)] * 1e6,
        "drained_ms": drained_ms,
        "delivered": sum(1 for event in done if event.is_set()),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--burst", type=int, default=DEFAULT_BURST)
    parser.add_argument("--work-ms", type=float, default=DEFAULT_WORK_MS)
    parser.add_argument(
        "--path",
        action="append",
        choices=["legacy", "reserve", "bound"],
        help="Repeatable. Defaults to all three, in that order.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    paths = args.path or ["legacy", "reserve", "bound"]
    work_seconds = args.work_ms / 1000.0
    quiet_threads = threading.active_count()

    print(
        f"burst={args.burst} work={args.work_ms:.0f}ms threads at rest={quiet_threads}"
    )
    for path in paths:
        result = measure(path, args.burst, work_seconds, quiet_threads)
        print(
            f"{result['path']:>8} | threads +{result['threads_added']:>4} "
            f"| calls at once {result['peak_concurrent_calls']:>4} "
            f"| dispatch p50 {result['dispatch_p50_us']:>8.1f} us "
            f"p99 {result['dispatch_p99_us']:>9.1f} us "
            f"| drained {result['drained_ms']:>8.1f} ms "
            f"| delivered {result['delivered']}/{args.burst}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
