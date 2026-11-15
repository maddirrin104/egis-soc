"""Development-only process-tree profiling with explicit measurement provenance."""

from __future__ import annotations

import os
import platform
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import psutil

VERSION = "w6-profile-1"


def _tree_rss() -> int:
    root = psutil.Process(os.getpid())
    total = 0
    for process in (root, *root.children(recursive=True)):
        try:
            total += process.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return total


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[int((len(ordered) - 1) * fraction + 0.999999)]


def profile_stages(stages: Sequence[tuple[str, Callable[[], Mapping[str, Any] | None]]], *,
                   workload_ref: str, repetitions: int = 1, concurrency: int = 1,
                   context_config: Mapping[str, Any] | None = None,
                   model: Mapping[str, Any] | None = None,
                   timeout_s: float | None = None,
                   input_cost_per_million: float | None = None,
                   output_cost_per_million: float | None = None) -> dict[str, Any]:
    """Measure completed synchronous calls; deadline overruns are failed attempts.

    A call is not forcibly interrupted. The timeout classification is made after
    it returns; use an external supervisor for hard process termination.
    """
    if (not stages or repetitions < 1 or concurrency < 1 or not workload_ref
            or len({name for name, _ in stages}) != len(stages)
            or any(not name or not callable(action) for name, action in stages)):
        raise ValueError("invalid_profile_plan")
    if timeout_s is not None and timeout_s <= 0:
        raise ValueError("invalid_timeout")
    if any(value is not None and value < 0 for value in
           (input_cost_per_million, output_cost_per_million)):
        raise ValueError("invalid_token_price")
    attempts = []
    whole_ns = []
    peak_rss = _tree_rss()
    for repetition in range(repetitions):
        run_elapsed_ns = 0
        for name, action in stages:
            stop = threading.Event()
            sample_peak = [0]

            def sample() -> None:
                while not stop.is_set():
                    sample_peak[0] = max(sample_peak[0], _tree_rss())
                    stop.wait(0.005)

            monitor = threading.Thread(target=sample, daemon=True)
            monitor.start()
            start = time.perf_counter_ns()
            try:
                result = action()
                if result is not None and not isinstance(result, Mapping):
                    raise ValueError("invalid_stage_measurement")
                result = dict(result or {})
                token_in = result.get("input_tokens")
                token_out = result.get("output_tokens")
                if any(value is not None and (type(value) is not int or value < 0)
                       for value in (token_in, token_out)):
                    raise ValueError("invalid_token_usage")
                error = None
            except Exception as exc:
                result, token_in, token_out = {}, None, None
                error = type(exc).__name__
            finally:
                elapsed = time.perf_counter_ns() - start
                stop.set()
                monitor.join()
                peak_rss = max(peak_rss, sample_peak[0], _tree_rss())
            status = ("FAILED" if error else "TIMEOUT" if timeout_s is not None
                      and elapsed > timeout_s * 1e9 else "SUCCESS")
            run_elapsed_ns += elapsed
            attempts.append({"stage": name, "repetition": repetition,
                             "start_kind": "cold" if repetition == 0 else "warm",
                             "status": status, "error_type": error,
                             "latency_ns": elapsed, "input_tokens": token_in,
                             "output_tokens": token_out})
        whole_ns.append(run_elapsed_ns)
    successes = [item for item in attempts if item["status"] == "SUCCESS"]
    input_tokens = sum(item["input_tokens"] for item in successes
                       if item["input_tokens"] is not None)
    output_tokens = sum(item["output_tokens"] for item in successes
                        if item["output_tokens"] is not None)
    priced = (input_cost_per_million is not None and output_cost_per_million is not None
              and all(item["input_tokens"] is not None and item["output_tokens"] is not None
                      for item in successes) and bool(successes))
    return {"version": VERSION, "scope": "SYNTHETIC_OR_DEVELOPMENT_ONLY",
            "workload_ref": workload_ref,
            "conditions": {"os": platform.platform(), "python": platform.python_version(),
                           "psutil": psutil.__version__,
                           "cpu": platform.processor(), "logical_cpus": os.cpu_count(),
                           "concurrency": concurrency,
                           "context_config": dict(context_config or {}),
                           "model": dict(model or {"status": "NOT_MEASURED"}),
                           "rss_sampling_interval_ms": 5,
                           "timeout_kind": "post_return_deadline_classification"},
            "attempts": attempts,
            "summary": {"success": len(successes),
                        "failed": sum(item["status"] == "FAILED" for item in attempts),
                        "timeout": sum(item["status"] == "TIMEOUT" for item in attempts),
                        "overall_latency_p50_ns": _percentile(whole_ns, .5),
                        "overall_latency_p95_ns": _percentile(whole_ns, .95),
                        "stage_latency_ns": {name: {
                            "p50": _percentile([a["latency_ns"] for a in successes if a["stage"] == name], .5),
                            "p95": _percentile([a["latency_ns"] for a in successes if a["stage"] == name], .95)}
                            for name, _ in stages},
                        "peak_process_tree_rss_bytes": peak_rss,
                        "input_tokens": input_tokens if all(a["input_tokens"] is not None for a in successes) and successes else None,
                        "output_tokens": output_tokens if all(a["output_tokens"] is not None for a in successes) and successes else None,
                        "throughput_successful_attempts_per_s": (format(len(successes) * 1e9 / sum(whole_ns), ".6f")) if successes else None,
                        "inference_cost": (format((input_tokens * input_cost_per_million + output_tokens * output_cost_per_million) / 1e6, ".12f"))
                        if priced else None,
                        "inference_cost_unit": "configured_currency" if priced else "NOT_MEASURED"}}
