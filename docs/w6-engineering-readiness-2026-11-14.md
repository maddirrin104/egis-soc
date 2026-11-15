# W6 engineering readiness — 2026-11-14

## Scope and execution

This is synthetic/development engineering evidence, not an Environment B qualification or RQ3 evaluation. Approved protocol §5 and D-008 put held-out A/B scoring after W7 method lock, calibration and access/independence audits. D-026 removes the presumption that the Splunk Attack Range channel is independent B after A allocation; D-028 unknown-lineage PDS-01 remains train-designated only. D-032 is still PROPOSED. No held-out IDs, events, labels, predictions or scores were read.

Baseline: `main` at `0228669 docs(context): record W4 checkpoint verification`; `git status --short` had 199 listed entries at preflight (295 expanded paths reported in the prior W5-CP audit). The local `w5-cp-verified-20261114` branch covers a synthetic subset, not a full development baseline. No Git history or existing W5 archive was changed.

## Tools and use

| Area | Implementation | Status / boundary |
| --- | --- | --- |
| Environment B | [`w6_environment_b.py`](../src/egis_soc/w6_environment_b.py) | Blinded custodian metadata screen for collection/provenance, operator/dates, pipeline/sensors/schema/source mix, incident/tenant and original-run lineage, template/source-family overlap, duplicate and near-duplicate findings, rights, cluster sufficiency and independent reviewer decision. Each check returns `PASS`, `FAIL`, `PENDING` or `UNKNOWN` with reason and audit reference. `PASS` remains `NOT_APPROVED_FOR_EVALUATION`; it cannot replace custodian evidence, human approval or W7 gates. The current source-absent screen is `UNKNOWN`. Structural duplicate detection must run in restricted custody and release only disposition references; no sealed fingerprints enter this checker. |
| R1–R6 | [`w6_robustness.py`](../src/egis_soc/w6_robustness.py) | Deterministic synthetic train variants retain parent incident, tenant, partition, lineage group, source evidence ID/provenance, transformation hash and seed. R1 substitutes whole entity literals; R2 maps field names with collision rejection; R3 adds timezone display while preserving UTC; R4 adds labeled synthetic benign noise; R5 removes selected telemetry; R6 removes a log-source category. R5/R6 always route to `HUMAN_REVIEW_REQUIRED`; no gold label is copied. Variants are separate from B and never alter raw source. The framework does not claim semantic label preservation without human review. |
| Profiling | [`w6_profiling.py`](../src/egis_soc/w6_profiling.py), [`w6_synthetic_profile.py`](../scripts/w6_synthetic_profile.py) | Measures per-stage and overall p50/p95 in nanoseconds, sampled peak process-tree RSS in bytes, success/failure/deadline-overrun attempts, cold/warm repetition, model/context/hardware/OS, token counts if supplied, and throughput. Cost is `NOT_MEASURED` without token counts and configured prices. Timeout classification happens after synchronous return; it is not a hard process kill. The 5 ms RSS sampler can miss shorter peaks. |

Install the small profiling dependency with `pip install -r requirements-w6.txt` in the configured Python environment. Run with `PYTHONPATH=src`:

```text
python scripts/w6_synthetic_profile.py
python scripts/w6_synthetic_profile.py --check
python -m unittest discover -s tests -p test_w6_engineering.py -v
python -m unittest discover -s tests -p test_*.py -q
```

The create command is exclusive; a new run needs a new output directory using `--output`. It reads only [`w6_synthetic_workload_v1.json`](../tests/fixtures/w6_synthetic_workload_v1.json). The current create-only [`w6_synthetic_engineering_v3/`](../experiments/w6_synthetic_engineering_v3/) archive contains [`report.json`](../experiments/w6_synthetic_engineering_v3/report.json) and [`manifest.json`](../experiments/w6_synthetic_engineering_v3/manifest.json). `--check` verifies canonical bytes, fixture SHA-256, report hash and five source code hashes without rerunning profiling. The earlier session-created v2 archive remains as an unpinned intermediate; the failed v1 attempt was removed. No historical W5 archive changed.

## Measured synthetic run

Fixture SHA-256 `7a0be66ac4aa689187dbc9a925b992fa7e6ba4386e1f4dea7c42806db711ceb3`; report SHA-256 `5e8ccc0363af3a31076ccf9818d38db1e84426476d3dcc4e40ac8f1c6fd79bc8`. Three sequential repetitions (first tagged `cold`, two tagged `warm`) of W3 retrieval and R1–R6 transformation stage: **6 success, 0 failed, 0 timeout**. These tags mean first and later calls within one already started Python process; actual process/model cold start was `NOT MEASURED`. Overall stage-sum p50 **1,158,200 ns**, p95 **1,963,500 ns**; sampled peak process-tree RSS **40,742,912 bytes**; successful stage throughput **1,475.760632 attempts/s**. Conditions: Windows 11 build 26200, Python 3.14.7, psutil 7.2.2, AMD64 16 logical CPUs, concurrency 1, two authored events, query `logon`, 5 ms RSS sampling. These are tiny synthetic engineering measurements and exclude model inference; they are not SOC throughput or a real incident benchmark. Model checkpoint/revision are recorded as intended context only; quantization, model execution, input/output tokens and inference cost are `NOT_MEASURED`. The W5-08 v2 archive check now passes with the pinned cache present; no model substitution was attempted.

The existing [`test_w5_s2.py`](../tests/test_w5_s2.py) and [`test_w5_final_report.py`](../tests/test_w5_final_report.py) already exercise a separate evidence-supported positive path with a synthetic fake backend and a final claim. This does not alter the historical W5-08 v2 archive, whose actual run retained zero claims. Its offline `--check` now PASS for all 9 stages with unchanged fork SHA-256 `d19105d2faff4a9022ba4867b693749569003a95d9746367b249e11e1ada2758` and manifest SHA-256 `71fb57e0249665dc99fe525e7cb708a1f82b428aaa603ed98dba860d2011db68`. That check read the currently present pinned cache files and saved archive; it did not run inference.

Validation on this dirty worktree: focused W6 **6 PASS / 0 FAIL / 0 SKIP**; full offline unittest **494 PASS / 0 FAIL / 0 SKIP**; W6 archive `--check` PASS; W5-08 v2 archive `--check` PASS; editor Problems on the five W6 Python files zero; `git diff --check` PASS. The full run includes the six new W6 tests and is not a clean-checkout release claim.

## Remaining gates

- A rights-cleared, separately operated Environment B collection; custodian evidence for operator, run, collection and concrete template/source-family independence, duplicate/near-duplicate comparisons across all A partitions, meaningful shift, independent cluster adequacy and independent review. Current B readiness is `UNKNOWN`, RQ3 `NOT RUN`.
- Human-reviewed R5/R6 variant labels before any robustness metric; eligible matched incident/pair set before calculating perturbation deltas. Current robustness metrics `NA`.
- W2 source-specific approvals, accepted scope/lineage and human gold; W4-05 and W5-09 remain blocked. D-032 remains proposed. W7 needs pre-test locks, blinded gold, calibration and audit/access gates before held-out A/B evaluation.
- Full model/pipeline profiling needs the exact pinned model cache verified, an authorized workload, token accounting and pricing if cost is reported. Current model latency/cost `NOT MEASURED`.
