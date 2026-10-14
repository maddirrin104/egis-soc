# Current project state

## W1-03 accepted and complete — 2026-10-14 04:14 UTC

- The project owner explicitly approved W1-03 Data Schemas for completion on 2026-10-14 after reviewing the remediation and acceptance reports. W1-03 is `DONE`; other task statuses are unchanged. The approved four-file, path-limited schema commit is `07bc252f37320568ce68d52f79fab0264e81d6d8` on branch `main`. W1-03 context updates remain unstaged because the context files contain mixed prior task history; unrelated staged and unstaged changes were preserved. The latest [handoff](HANDOFF.md) records the verified commit tree and Git status.
- Scope-bearing `IncidentBundle.alert_ids`/`evidence_ids`, `ClaimEvidencePair.evidence_ids`, `GoldFact.evidence_ids`, and `EvaluationGoldRecord.evidence_ids`/`gold_facts` now validate list inputs into ordered immutable tuples. The scope-bearing models also reject ordinary field reassignment, and the common contract rejects unchecked `model_copy(update=...)`. Nested evaluation fact references can no longer be appended after validation through normal model APIs.
- **PASSED, freshly rerun:** `$env:PYTHONPATH='src'; $env:PYTHONDONTWRITEBYTECODE='1'; .\.venv\Scripts\python.exe -m unittest discover -s tests -v` — 10 tests, `OK`, exit 0 (0.006 s on the final run). Python 3.14.7, Pydantic 2.14.1, and `.venv` `pip check` with no broken requirements were verified. Exact commands and limits are in the latest [handoff](HANDOFF.md).
- The staged approved protocol still hashes to `B80A39F0E08CC8D22B1A65776355D1C34D81E7E0F2721A0C34A08CA9C34C1E0A`. Its pre-existing unstaged working-copy edits remain untouched and require separate owner disposition. W1-04 annotation guidelines and real independent human review, W2 ingestion/hash verification and raw-store lookup, and W1-07 lineage/split/freeze and evaluation access controls remain future work. Schema acceptance does not establish those controls or empirical results.

The records below are historical; this update supersedes their W1-03 current/next wording.

## W1-03 schema remediation awaiting human acceptance — 2026-10-14 03:23 UTC

- Verified branch `main`, HEAD `852d1fe0cbcfa69b8879bfa564f16c9bbd5b6cc4`. W1-03 remains `IN_PROGRESS`; W1-01/W1-02 and other task statuses were not changed.
- Inference-facing `IncidentBundle` no longer accepts or serializes evaluation `gold_facts`. Separate `EvaluationGoldRecord` retains human-reviewed facts and checks incident, tenant and evidence-snapshot identity. `EvaluationClaimEvidencePair` requires human-reviewed label provenance and an annotation record ID; general `ClaimEvidencePair` still supports generated/training candidates with a separate claim-source field. Evidence provenance now requires a source-store raw-message reference, defines SHA-256 over persisted raw snapshot bytes, and prevents ordinary post-validation reassignment of provenance fields.
- **PASSED:** project `.venv` unittest discovery: 7 schema tests, `OK`, exit 0. **PASSED:** Pydantic 2.14.1 import and project `.venv` `pip check` (no broken requirements). The latest [handoff](HANDOFF.md) records exact commands, changes and limits. No ingestion, annotation, model, final-test, or empirical run was performed.
- The approved staged protocol hash remains `B80A39F0E08CC8D22B1A65776355D1C34D81E7E0F2721A0C34A08CA9C34C1E0A`; the pre-existing unstaged working-copy protocol edits remain outside this task and need separate owner reconciliation. W1-03 implementation needs human acceptance before `DONE`.

The records below are historical; this update supersedes their W1-03 current/next wording.

## Latest W1-03 dependency restoration and verification — 2026-10-13 03:47 UTC

- Verified branch `main`, HEAD `852d1fe0cbcfa69b8879bfa564f16c9bbd5b6cc4` (`Initial commit`). Existing staged, unstaged and untracked work was preserved.
- Restored the declared `pydantic>=2.0,<3.0` from [requirements.txt](../../requirements.txt) into the ignored project `.venv` using Python 3.14.7; installed Pydantic 2.14.1. The base Python installation was not modified. Use `.venv/Scripts/python.exe` explicitly for subsequent tests.
- **PASSED:** `$env:PYTHONPATH='src'; $env:PYTHONDONTWRITEBYTECODE='1'; .\.venv\Scripts\python.exe -m unittest discover -s tests -v` — 4 tests, `OK`, exit 0. **PASSED:** `.\.venv\Scripts\python.exe -m pip check` — no broken requirements, exit 0. Exact output is recorded in the latest [handoff](HANDOFF.md).
- The missing-dependency blocker is resolved for this environment. W1-03 remains `IN_PROGRESS` pending human acceptance; W1-01/W1-02 remain `DONE`. No schema, test, dependency declaration, protocol, dataset or frozen evaluation artifact changed. No empirical evaluation was run.

The records below are historical; this update supersedes their current blocker and next-action wording.

**As-of**: 2026-10-12 17:45 UTC. **Status**: W1-01 context verification and W1-02 methodological protocol v0.2 remain `DONE` on recorded owner approvals. W1-03 schemas remain `IN_PROGRESS` pending human acceptance; the current focused test attempt exited 1 before assertions because this Python environment lacks `pydantic`. W1-02 completion does not certify an experiment or final-test readiness.

## Latest verified end-session state

- Branch `main`, HEAD `852d1fe0cbcfa69b8879bfa564f16c9bbd5b6cc4` (`Initial commit`). The [approved protocol](../research-protocol.md) remains staged as an added file; an unrelated staged deletion and pre-existing dirty/untracked paths remain. The exact status is in the latest [handoff](HANDOFF.md). No code, dataset, frozen evaluation artifact, decision or approval was changed in this end-session check.
- Current test command: `PYTHONPATH=src`, `PYTHONDONTWRITEBYTECODE=1`, `python -m unittest discover -s tests -v`; exit 1, one import error (`ModuleNotFoundError: No module named 'pydantic'`), zero test assertions reached. The earlier W1-03 [handoff](HANDOFF.md) reports four tests passing with Pydantic 2.14.1 in a temporary environment; that result was not rerun in that environment today. The test-discovery tool found no tests and did not execute them. This is an environment blocker for current W1-03 verification, not evidence of a schema assertion failure.
- The current session is documentation-only: [TASK_BOARD.md](TASK_BOARD.md) keeps W1-02 `DONE`, W1-03 `IN_PROGRESS`, and all later task statuses unchanged. No CI calibration, application, training, inference or empirical evaluation was run. The next action is to restore the declared Pydantic dependency in the test environment and rerun the focused W1-03 schema tests before requesting human acceptance.

The sections below are prior history; this update supersedes their current/next wording.

## Latest W1-02 Phase D methodological acceptance

- The project owner approved A-01 through A-04 on 2026-10-13: RQ1 three gates and RQ3 two relative-robustness gates with descriptive B FSR; `delta=0.03` as a pooled-UCR research tolerance with mandatory absolute-count diagnostics; paired lineage-cluster inference with pre-test Monte Carlo screening; and frozen arm-independent draft pairs, lineage isolation, independent B, and identical S2/S3 starting states. A-03 approval requires nominal 95% intervals and a nominal 5% full-claim Type I target to be distinguished from the 93% usable-coverage and 7% Type I screening tolerances; exactly 1,000 outer datasets per predeclared scenario initially, with no automatic top-up. Any sequential extension needs a separately approved statistically valid pre-test procedure. Failed or inconclusive calibration prevents the affected confirmatory conclusion. These screens do not prove strict nominal coverage, alpha control or SOC safety.
- [Protocol v0.2](../research-protocol.md) is approved as a **methodological specification**, SHA-256 `B80A39F0E08CC8D22B1A65776355D1C34D81E7E0F2721A0C34A08CA9C34C1E0A`, and staged alone for addition to Git; it is not committed. [D-007](DECISION_LOG.md) records the owner/date/hash/conditions and supersedes D-004/D-005/D-006 while preserving their proposal history. N-B1/N-M1/N-m1 remain resolved in the written method. [W1-02](TASK_BOARD.md) is `DONE` after the document, context, whitespace, acceptance and unrelated-change checks recorded in the latest [handoff](HANDOFF.md).
- Deferred: W1-04 annotation rubric and independent gold; W1-05 licensed source/independent-B dossier; W1-07 lineage, split, draft-pair, sealed-class and freeze audits; W5 draft and paired-fork archives; W7 non-test scenario lock, compute benchmark, Monte Carlo calibration, manifest validation and final evaluation. W3/W4 source-derived pilots remain diagnostic. No later gate, empirical metric, final-test parameter, CI validity or operational safety has been verified. W1-03 and unrelated dirty paths were preserved.

The sections below are prior history; this update supersedes their current/next wording.

## Latest W1-02 final A-03 statistical correction

- The [untracked protocol draft](../research-protocol.md) replaces the impractically strict Monte Carlo coverage criterion with a **PROPOSED** 95% nominal coverage target, a proposed two-percentage-point usable-coverage shortfall tolerance, a proposed two-percentage-point full-claim Type I excess tolerance, at least 1,000 independent simulated datasets per scenario, and an optional predeclared 3,000-run top-up. It defines false full-H1 confirmation under the composite null as Type I error and failure to confirm a true H1 as Type II error; power is reported, not used to pass calibration. The seven single-component boundary nulls include both RQ2 CFR and UCR boundaries. W7 must freeze non-test scenarios, include sparse/heterogeneous/dependent clusters, use the proposed 10,000 inner bootstrap replicates, and benchmark compute before final-test access. The tolerances do not prove exact nominal coverage/alpha or generalize to unmodeled shifts. No simulation was run.
- [D-006](DECISION_LOG.md) is `PROPOSED` and all A-01–A-04 approvals remain pending. A-01, A-02 `delta=0.03`, A-04, prior Phase C.2 resolutions, W1-03 and unrelated dirty paths were preserved. W1-07/W7 artifacts, calibration, final evaluation and Phase D are not complete. W1-02 remains `IN_PROGRESS`; see the latest [handoff](HANDOFF.md) for observed checks and Git state.

The sections below are prior history; this update supersedes their current/next wording.

## Latest W1-02 final methodological approval amendment

- Phase C.3 found N-B1, N-M1 and N-m1 resolved in the written method, no new BLOCKER, and a MAJOR A-03 concern that the proposed 10-cluster/5%-invalid rule does not itself validate percentile-bootstrap coverage. The [untracked protocol draft](../research-protocol.md) now states a normative, unvalidated rationale for the proposed `delta=0.03` pooled-UCR tolerance, requires qualified reporting if absolute unsupported counts rise, and makes a failed/undefined UCR bound fatal to the full RQ2 claim. It also proposes a pre-test CI calibration gate with W1-07 design audits, W7 non-test simulation, an explicitly proposed coverage/type-I acceptance criterion, and exploratory fallback. No calibration or evaluation was run.
- [D-005](DECISION_LOG.md) is `PROPOSED`, not approved. A-01 and A-04 were left unchanged; A-02 and A-03 still require explicit human decisions. W1-04, W1-05, W1-07, W5, W7 and Phase D remain deferred. W1-02 is not `DONE`. The latest [handoff](HANDOFF.md) records validation and Git state; W1-03 and unrelated dirty paths were preserved.

The sections below are prior history; this update supersedes their current/next wording.

## Latest W1-02 Phase C.2 targeted correction

- The independent Phase C.2 review returned NO-GO on N-B1 (RQ3 zero-margin FSR gate), N-M1 (RQ1 target population), and N-m1 (UCR margin wording). The [untracked protocol draft](../research-protocol.md) now proposes a two-endpoint RQ3 relative-drop claim (Macro-F1 and Supported Precision) with absolute B FSR/counts/denominators/uncertainty reported as mandatory diagnostics, not a safety non-inferiority claim. It defines primary RQ1/RQ3 pairs from frozen arm-independent LLM drafts, with source-derived and verifier-blind repair claims separately diagnostic. `delta=0.03` is explicitly a proposed pooled-UCR-rate margin, not an absolute count allowance.
- [D-004](DECISION_LOG.md) records these changes as `PROPOSED`, with human approval pending. W1-04 annotation, W1-05 B sourcing, W1-07 manifests, W5 draft generation, W7 evaluation, and Phase D remain unperformed by this correction. W1-02 status is unchanged. See the latest [handoff](HANDOFF.md) for fresh validation and Git state. W1-03 implementation and unrelated dirty paths were preserved.

The sections below are prior history; the update above supersedes their current/next wording.

## Latest W1-02 Phase C revision

- The independent Phase C review found 3 BLOCKER, 7 MAJOR, and 1 MINOR issues. [Protocol draft 0.2](../research-protocol.md) now contains proposed RQ1/RQ3 conjunctive decision hierarchies, a proposed RQ2 non-inferiority rule with `delta=0.03` still unapproved, lineage-group leakage quarantine, fixed pair sampling, identical S2/S3 archived forks, review mapping, UCR dilution diagnostics, B-independence gates, a lineage-cluster bootstrap rule, a secondary metric dictionary, and a finding-resolution/source-plan acceptance crosswalk.
- W1-02 is still `IN_PROGRESS`. The written corrections are proposals, not human approvals or evidence that W1-04 annotation, W1-05 B sourcing, W1-07 splits, model runs, or empirical evaluation exist. Sections 10–12 of the draft identify approval choices and later gates. `DECISION_LOG.md` has no new accepted decision.
- Only the protocol and W1-02 context/handoff records were edited in this revision. W1-03 code/tests and unrelated dirty paths were preserved. Validation and fresh Git state are recorded in the latest section of [HANDOFF.md](HANDOFF.md).

## Latest W1-03 verified update

- Branch `main` and HEAD `852d1fe0cbcfa69b8879bfa564f16c9bbd5b6cc4` remain unchanged. W1-03 preserved all pre-existing dirty paths and added only `requirements.txt`, `src/egis_soc/__init__.py`, `src/egis_soc/schemas.py`, and `tests/test_schemas.py`.
- Five Pydantic contracts now cover incident bundle, evidence event, evidence provenance, human-reviewed gold fact, and claim-evidence pair. They validate the three distinct labels, UTC provenance timestamps, unique and in-bundle evidence references, and tenant/incident scope. Schema validation does not establish factual support or independent annotation provenance.
- PASSED: focused `python -m unittest discover -s tests -v` with `PYTHONPATH` set to the temporary Pydantic 2.14.1 install and `src`; 4 tests, `OK`, exit 0. The temporary dependency install is outside the repository.
- W1-03 remains `IN_PROGRESS` pending human acceptance before `DONE`. W1-02 remains separately pending methodological review. No ingestion/retrieval caller, dataset, model run, or empirical result is claimed. See the latest section of `HANDOFF.md` for fresh Git and validation output.

The sections below record the prior W1-02 state and validation history; the update above supersedes their "current" and "next" wording.

## Verified

- Repository branch: `main`; HEAD: `852d1fe0cbcfa69b8879bfa564f16c9bbd5b6cc4` (`Initial commit`).
- `python scripts/context_status.py --check` exited 0 on 2026-10-12: all expected context files exist. It reported the branch, HEAD and dirty paths listed below.
- Root `AGENTS.md` is the shared project contract, and `.github/copilot-instructions.md` points to it. Selected local skills are tracked under `.agents/skills/`; `docs/context/SKILL_PROVENANCE.md` records their upstream source. The user confirmed on 2026-10-12 that the active VS Code Codex harness recognizes `AGENTS.md`, discovers `egis-handoff`, and has no conflicting applicable instructions. This is human-reported UI evidence, not an agent-run UI test.
- The user explicitly approved W1-01 validation and handoff evidence on 2026-10-12. W1-01 is `DONE` in `TASK_BOARD.md`; the approval does not extend to W1-02 implementation.
- The source plan's W1 row calls for a literature matrix, research gap, RQs/hypotheses, schemas, annotation guideline, threat model, dataset/license selection, research protocol, architecture v1, split policy and baseline list. These are planned deliverables, not completed work.
- A W1-02 [research protocol review draft](../research-protocol.md) now exists with RQ1–RQ3, V0–V3/S0–S3, metric formulas, dataset/evaluation policy, statistics, reproducibility fields, and a CONFIRMED/PROPOSED/OPEN register. It contains no measured findings and has not been accepted or frozen.

## Working tree before W1-01 (historical)

Before the W1-01 edits, `git status --short` reported:

```text
 M .gitignore
D  README_CONTEXT_STARTER.md
 M docs/EGIS_SOC_Ke_hoach_8_tuan.md
 M docs/context/TASK_BOARD.md
?? README.md
?? plan.pdf
```

These paths predated W1-01. That task preserved them except for a narrow status/acceptance update to the W1-01 row in `TASK_BOARD.md`. The current W1-02 Git state is recorded under Validation below.

## Not verified / do not assume

- Other-provider instruction/skill visibility was not checked and is outside W1-01 acceptance. The working tree is known to be dirty; a clean tree is not a project-policy completion condition.
- Dataset collection, Splunk connection, trained models, benchmarks, experiment/test runs, or any M1–M4 milestone.
- Approval of proposed research or architectural decisions in `DECISION_LOG.md`.
- Human approval of the W1-02 protocol, the proposed 3-percentage-point UCR margin, exact dataset/split/model choices, metric edge-case policies, or final-test configuration.

## Current milestone and task

W1 (2026-10-12 to 2026-10-18). `W1-01` remains `DONE` on the recorded checks and explicit human approval. `W1-02` is `IN_PROGRESS`: its protocol draft is ready for human methodological review, with decisions explicitly pending. No research experiment, training, or inference has been performed.

## Validation

- At the latest end-session check, `git status --short` listed unstaged modifications to `.gitignore`, `docs/EGIS_SOC_Ke_hoach_8_tuan.md`, `docs/context/CURRENT_STATE.md`, `docs/context/HANDOFF.md`, and `docs/context/TASK_BOARD.md`; staged deletion of `README_CONTEXT_STARTER.md`; and untracked `README.md`, `docs/research-protocol.md`, and `plan.pdf`. Branch `main` and HEAD above were verified. See [latest handoff](HANDOFF.md) for the exact status output and provenance of these changes.
- PASSED: `python scripts/context_status.py --check` (exit 0; `Context: OK`, branch/HEAD and dirty paths reported). It checks required file presence, not methodological correctness.
- PASSED: `git diff --check` (exit 0, LF-to-CRLF warnings only) and `git diff --cached --check` (exit 0, no output). The untracked protocol is outside Git's diff checks.
- NOT RUN this end-session check: application, unit, model, and empirical tests; no application/test tree exists and this update changes only documentation. A prior structural/link/whitespace scan of the protocol draft passed, as recorded in the [earlier handoff](HANDOFF.md).

## Next action

Human reviewer: review the W1-02 [protocol draft](../research-protocol.md), especially the PROPOSED and OPEN choices, and approve or request revisions. Preserve and document the existing working-tree changes.
