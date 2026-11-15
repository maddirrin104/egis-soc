"""Create/check a code-pinned W7 statistical engineering smoke archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

import scipy

from egis_soc.w7.bootstrap import bootstrap_intervals, rq1_endpoints, rq2_endpoints, rq3_endpoints
from egis_soc.w7.calibration import (Scenario, population_truth, rq3_population_truth,
                                     run_smoke, synthetic_pair_generator,
                                     synthetic_rq3_generator, synthetic_summary_generator)
from egis_soc.w7.count_cache import (cache_pairs, cache_summaries, cached_rq1_endpoints,
                                      cached_rq2_endpoints, cached_rq3_endpoints)
from egis_soc.w7.metrics import rq3_drops, score_pairs, score_summaries
from egis_soc.w7.readiness import check_readiness
from egis_soc.w7.scenario_catalog import (
    PairCountDesign, SummaryCountDesign, generate_pair_counts, generate_rq3_counts,
    generate_summary_counts, pair_population_truth, rq3_population_truth as count_rq3_truth,
    summary_population_truth,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "w7_synthetic_smoke_v1.json"
ADVERSE = ROOT / "tests" / "fixtures" / "w7_adverse_count_candidates_v1.json"
OUTPUT = ROOT / "experiments" / "w7_00_synthetic_infra_v8"
CODE_FILES = (
    "scripts/w7_synthetic_infra.py", "requirements-w7.txt",
    "src/egis_soc/development/matched_evaluation.py",
    "src/egis_soc/w7/metrics.py", "src/egis_soc/w7/bootstrap.py",
    "src/egis_soc/w7/count_cache.py", "src/egis_soc/w7/calibration.py",
    "src/egis_soc/w7/agreement.py", "src/egis_soc/w7/ablation.py",
    "src/egis_soc/w7/readiness.py", "src/egis_soc/w7/scenario_catalog.py",
    "tests/test_w7_statistics.py", "tests/test_w7_ablation.py",
    "tests/test_w7_scenario_catalog.py",
)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _code_hashes() -> dict[str, str]:
    return {name: _sha((ROOT / name).read_bytes()) for name in CODE_FILES}


def _focused_tests() -> dict[str, object]:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(ROOT / "src"),
                                                         str(ROOT / "scripts"),
                                                         str(ROOT / "tests"))),
           "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests",
                             "-p", "test_w7_*.py", "-q"], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=60, check=False)
    output = result.stdout + result.stderr
    match = re.search(r"Ran (\d+) tests? in", output)
    if result.returncode != 0 or match is None or not re.search(r"(?m)^OK\s*$", output):
        raise ValueError("w7_focused_tests_failed")
    return {"command": "python -m unittest discover -s tests -p test_w7_*.py -q",
            "passed": int(match.group(1)), "failed": 0, "skipped": 0,
            "exit_code": result.returncode}


def _pair_design(record: dict) -> PairCountDesign:
    return PairCountDesign(record["environment"], tuple(record["cluster_sizes"]),
                           tuple(record["family_by_cluster"]),
                           {name: tuple(value) for name, value in record["prevalence_by_family"].items()},
                           {name: tuple(value) for name, value in record["errors_by_family"].items()},
                           record["cluster_dependence"])


def _summary_design(record: dict) -> SummaryCountDesign:
    return SummaryCountDesign(tuple(record["cluster_sizes"]),
                              tuple(record["family_by_cluster"]),
                              {name: tuple(value) for name, value in record["rates_by_family"].items()},
                              record["facts_per_incident"], record["claims_per_incident"],
                              record["cluster_dependence"])


def _adverse_smoke(seed: int) -> dict:
    raw = ADVERSE.read_bytes()
    config = json.loads(raw)
    if (config.get("version") != "w7-adverse-candidates-1"
            or config.get("scope") != "SYNTHETIC_CANDIDATES_NOT_LOCKED"):
        raise ValueError("invalid_adverse_fixture")
    outcomes = {}
    for index, item in enumerate(config["pair_scenarios"]):
        design = _pair_design(item)
        truth = pair_population_truth(design)
        scenario = Scenario(item["name"], "RQ1", truth,
                            {name: "two_sided" for name in truth},
                            item["hypothesis"], item)
        outcomes[item["name"]] = run_smoke(
            scenario, generator=lambda value, d=design: generate_pair_counts(d, value),
            evaluator=cached_rq1_endpoints, outer=1, inner=10, seed=seed + index)
    item = config["summary_scenario"]
    design = _summary_design(item)
    truth = summary_population_truth(design)
    scenario = Scenario(item["name"], "RQ2", truth,
                        {"delta_cfr": "lower", "delta_ucr": "upper"},
                        item["hypothesis"], item)
    outcomes[item["name"]] = run_smoke(
        scenario, generator=lambda value: generate_summary_counts(design, value),
        evaluator=cached_rq2_endpoints, outer=1, inner=10, seed=seed + 20)
    item = config["rq3_scenario"]
    a, b = _pair_design(item["a"]), _pair_design(item["b"])
    truth = count_rq3_truth(a, b)
    scenario = Scenario(item["name"], "RQ3", truth,
                        {name: "two_sided" for name in truth}, item["hypothesis"], item)
    outcomes[item["name"]] = run_smoke(
        scenario, generator=lambda value: generate_rq3_counts(a, b, value),
        evaluator=cached_rq3_endpoints, outer=1, inner=10, seed=seed + 30,
        stratum_of=lambda unit: unit.environment)
    return {"status": "CANDIDATE_SMOKE_NOT_LOCKED", "fixture_sha256": _sha(raw),
            "scenario_count": len(outcomes), "outcomes": outcomes,
            "missing_component_boundary_designs": "PENDING_PRETEST_SCENARIO_LOCK"}


def _report() -> dict:
    raw = FIXTURE.read_bytes()
    config = json.loads(raw)
    if config.get("version") != "w7-synthetic-smoke-1" or config.get("scope") != "AUTHORED_SYNTHETIC_NO_GOLD":
        raise ValueError("invalid_w7_smoke_fixture")
    seed = config["seed"]
    args1 = {**config["rq1"], "prevalence": tuple(config["rq1"]["prevalence"])}
    args2 = config["rq2"]
    args3 = {**config["rq3"],
             "prevalence_a": tuple(config["rq3"]["prevalence_a"]),
             "prevalence_b": tuple(config["rq3"]["prevalence_b"]),
             "errors_a": tuple(config["rq3"]["errors_a"]),
             "errors_b": tuple(config["rq3"]["errors_b"])}
    gen1 = synthetic_pair_generator(**args1)
    gen2 = synthetic_summary_generator(**args2)
    gen3 = synthetic_rq3_generator(**args3)
    units1, units2, units3 = gen1(seed), gen2(seed + 1), gen3(seed + 2)
    cache1, cache2, cache3 = cache_pairs(units1), cache_summaries(units2), cache_pairs(units3)
    rep = config["bootstrap_repetitions"]
    methods1 = {name: "two_sided" for name in rq1_endpoints(units1)}
    methods2 = {"delta_cfr": "lower", "delta_ucr": "upper"}
    methods3 = {name: "two_sided" for name in rq3_endpoints(units3)}
    truth1 = population_truth(prevalence=args1["prevalence"],
                              v2_error=args1["v2_error"], v3_error=args1["v3_error"])
    truth2 = {"delta_cfr": args2["cfr_s3"] - args2["cfr_s2"],
              "delta_ucr": args2["ucr_s3"] - args2["ucr_s2"]}
    truth3 = rq3_population_truth(prevalence_a=args3["prevalence_a"],
                                  prevalence_b=args3["prevalence_b"],
                                  errors_a=args3["errors_a"], errors_b=args3["errors_b"])
    scenarios = (
        (Scenario("rq1_toy", "RQ1", truth1, methods1, "TRUE_H1", config["rq1"]),
         lambda value: cache_pairs(gen1(value)), cached_rq1_endpoints, None),
        (Scenario("rq2_toy", "RQ2", truth2, methods2, "TRUE_H1", config["rq2"]),
         lambda value: cache_summaries(gen2(value)), cached_rq2_endpoints, None),
        (Scenario("rq3_toy", "RQ3", truth3, methods3, "TRUE_H1", config["rq3"]),
         lambda value: cache_pairs(gen3(value)), cached_rq3_endpoints,
         lambda unit: unit.environment),
    )
    return {"status": "SYNTHETIC_ENGINEERING_ONLY", "fixture_sha256": _sha(raw),
            "runtime": {"os": platform.platform(), "python": platform.python_version(),
                        "scipy": scipy.__version__, "logical_cpus": os.cpu_count()},
            "config": config, "tests": _focused_tests(),
            "metric_engine": {"rq1": score_pairs(units1),
                              "rq2": score_summaries(units2),
                              "rq3": rq3_drops(tuple(unit for unit in units3 if unit.environment == "SYN_A"),
                                               tuple(unit for unit in units3 if unit.environment == "SYN_B"))},
            "bootstrap": {
                "rq1": bootstrap_intervals(cache1, evaluator=cached_rq1_endpoints,
                                           methods=methods1, repetitions=rep, seed=seed),
                "rq2": bootstrap_intervals(cache2, evaluator=cached_rq2_endpoints,
                                           methods=methods2, repetitions=rep, seed=seed + 1),
                "rq3": bootstrap_intervals(cache3, evaluator=cached_rq3_endpoints,
                                           methods=methods3, repetitions=rep, seed=seed + 2,
                                           stratum_of=lambda unit: unit.environment)},
            "calibration_smoke": {scenario.rq.lower(): run_smoke(
                scenario, generator=generator, evaluator=evaluator,
                outer=config["calibration_outer_smoke"],
                inner=config["calibration_inner_smoke"], seed=seed + index + 10,
                stratum_of=stratum_of)
                for index, (scenario, generator, evaluator, stratum_of) in enumerate(scenarios)},
            "adverse_candidate_smoke": _adverse_smoke(seed + 100),
            "readiness": check_readiness(),
            "heldout_evaluation": "NOT_RUN", "human_gold": "NOT_AVAILABLE",
            "official_calibration": "NOT_RUN_NO_SCENARIO_LOCK"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = args.output
    if args.check:
        if not output.is_dir() or output.is_symlink() or {p.name for p in output.iterdir()} != {"report.json", "manifest.json"}:
            raise ValueError("invalid_w7_archive")
        report_raw = (output / "report.json").read_bytes()
        manifest_raw = (output / "manifest.json").read_bytes()
        manifest = json.loads(manifest_raw)
        if (report_raw != _canonical(json.loads(report_raw))
                or manifest_raw != _canonical(manifest)
                or manifest.get("fixture_sha256") != _sha(FIXTURE.read_bytes())
                or manifest.get("adverse_fixture_sha256") != _sha(ADVERSE.read_bytes())
                or manifest.get("report_sha256") != _sha(report_raw)
                or manifest.get("code_sha256") != _code_hashes()):
            raise ValueError("w7_archive_integrity_failure")
        print(json.dumps({"status": "PASS_ARCHIVE_INTEGRITY",
                          "report_sha256": _sha(report_raw)}))
        return 0
    report = _report()
    report_raw = _canonical(report)
    manifest_raw = _canonical({"version": "w7-synthetic-archive-1",
                               "fixture_sha256": report["fixture_sha256"],
                               "adverse_fixture_sha256": report["adverse_candidate_smoke"]["fixture_sha256"],
                               "code_sha256": _code_hashes(),
                               "report_sha256": _sha(report_raw)})
    output.mkdir(parents=True, exist_ok=False)
    with (output / "report.json").open("xb") as stream:
        stream.write(report_raw)
    with (output / "manifest.json").open("xb") as stream:
        stream.write(manifest_raw)
    print(json.dumps({"status": "SYNTHETIC_INFRA_CREATED",
                      "report_sha256": _sha(report_raw),
                      "focused_passed": report["tests"]["passed"],
                      "readiness": report["readiness"]["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
