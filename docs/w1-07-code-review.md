# W1-07 code phase — review notes

**Status: SYNTHETIC IN-MEMORY IMPLEMENTATION ACCEPTED FOR W1 under [D-012](context/DECISION_LOG.md); operational choices PENDING OWNER REVIEW.** The code operates on synthetic sidecar records. A public direct manifest-freeze call is rejected; the split gate may create an in-memory `frozen` record only after recomputing the configured audit and checking submitted references. Those strings are not authenticated approvals. No real split, sealed store, gold record, access grant, or evaluation is created by this phase. [W1-07](context/TASK_BOARD.md) is `DONE` for the scoped W1 deliverable; D-011 remains `PROPOSED` for its pending operational choices.

## Design-to-code map

| Policy area | Implementation | Boundary |
| --- | --- | --- |
| Immutable lineage, typed original/run/concrete-template/collection/source-event keys, parents, missing metadata, connected components | [`lineage.py`](../src/egis_soc/lineage.py) | The sidecar is separate from approved [W1-03 schemas](../src/egis_soc/schemas.py); a `GroupKey` or review reference is a recorded assertion, not evidence of its truth. |
| Seeded whole-component A assignment, B reservation/quarantine, train-only mutation, insufficient groups, duplicate/near-match review, structural heterogeneity | [`split_freeze.py`](../src/egis_soc/split_freeze.py) | The full plan and audit-policy digests bind the manifest. Every active cross-partition material overlap, including train/validation, is gated; excluded findings stay separate. The deterministic greedy assignment reports shortfalls and does not establish source independence. |
| Canonical JSON bytes, SHA-256, stable content ID, proposed/frozen lifecycle and tamper checks | [`integrity.py`](../src/egis_soc/integrity.py) | Direct public `Manifest.freeze` is disabled. Hashes detect changed bytes; they do not prevent writes, attest identity, certify approval or seal storage. Actual signed manifests and ACLs are deferred. |
| Development denial for held-out/gold workflow reads, separate operational facts, W5 pair population, V2/V3 shared inputs, S2/S3 archive identity | [`evaluation_boundary.py`](../src/egis_soc/evaluation_boundary.py) | Gold reads require a verified manifest-linked tenant/incident/partition and incident-scoped grant; operational facts cite supplied evidence. In-process role strings and `AccessGrant` references are workflow guards, not authentication or OS isolation. |
| Original ten synthetic positive/adversarial cases and F-01–F-09 regressions | [`test_split_freeze.py`](../tests/test_split_freeze.py), [`test_w1_07_preacceptance.py`](../tests/test_w1_07_preacceptance.py) | No acquired data, held-out examples, model scores or real gold labels are used. |

## Role, capability and storage assumptions

| Role | In-process capability | Required external control before real use |
| --- | --- | --- |
| Development | Build inference input from train/validation evidence and operational facts; held-out and gold reads are rejected. | Development process and credentials cannot read restricted A/B or gold storage. |
| Custodian | Prepare private graph, audits, manifests and B dispositions; inspect permitted evidence under the project protocol. | Separate restricted storage, attributable reviewers, immutable-source preservation, access logs and authorized acquisition. |
| Annotator | Scoped annotation grant may allow fixed permitted evidence; evaluation gold construction remains independently blinded. | Separate accounts, documented blinding, initial judgments and adjudication audit. |
| Evaluator | Scoped evaluation grant may read gold only for the manifest-bound tenant, incident and partition named by the grant. | W7 locks, calibration, eligibility checks, signed unseal, restricted runner and logged outputs. |

The adapter is not a security boundary against a Python caller that can inspect process memory, forge role strings, or open the backing files directly. The host must enforce process/storage isolation and credential separation. Exact B component counts and lineage, held-out IDs and text, and all gold belong in restricted storage; only the [policy](split-freeze-policy.md) §4/§11 dispositions may reach development. The structural audit function returns restricted detail to its caller and must not be invoked in a development workflow with sealed graph records.

The current near-match candidate detector uses Unicode NFC, case folding, whitespace normalization and `SequenceMatcher`; its threshold is caller supplied. Cross-state comparison count is checked against an explicit policy limit before scanning; the provisional legacy cap is not methodological approval. The synthetic scaling test checks a bounded comparison count and a generous runtime ceiling, not real-dataset throughput. It does not implement entity/timestamp placeholder normalization or a scalable search index. A proposed next design is exact-key inverted indexes plus reviewed token-shingle blocking for near candidates, checked against exhaustive non-test data before adoption. Candidate indexing, similarity thresholds and production-size profiling remain **PENDING OWNER REVIEW**.

## F-01–F-09 pre-acceptance regressions

The [new synthetic regression suite](../tests/test_w1_07_preacceptance.py) was run **before** implementation changes: 9 tests, 7 failed assertions and 2 missing-API errors, exit 1. The direct public-freeze bypass was separately reproduced as one failing test before its fix. Each is retained as a passing regression after the corresponding change.

| Finding | Retained regression and fixed boundary |
| --- | --- |
| F-01 | Development exposure on any descendant quarantines its B component. |
| F-02 | Material unresolved train/validation overlap blocks; excluded/quarantined findings are reported separately. |
| F-03 | Freeze recomputes the complete audit and rejects forged flags/findings; direct public manifest freezing is disabled. |
| F-04 | Manifest digest changes with seed, targets, minimum groups, collection holdouts, policy/config revision or audit-policy digest even when assignments match; the implemented algorithm revision is bound and an unsupported revision is rejected. |
| F-05 | Gold reads reject caller partition, tenant/incident or grant-scope mismatches against a verified frozen manifest record. |
| F-06 | Operational facts may cite only evidence supplied to the current inference call. |
| F-07 | V2/V3 compare exact ordered claim text/payload and verified evidence/threshold bytes, plus checkpoint. |
| F-08 | Oversized comparisons fail before near matching; a bounded synthetic cost test reports comparison count. |
| F-09 | Threshold, normalization/method revision, review state, comparison budget and exact dispositions are bound and replayed at freeze. |

## N-01–N-04 targeted repair — owner review pending

The fresh pre-change baseline passed 40/40 synthetic/unit tests, exit 0. Four new minimal cases in [`test_w1_07_n01_n04.py`](../tests/test_w1_07_n01_n04.py) then ran **before source edits** and exited 1: N-01/N-03 assertion failures and N-02/N-04 missing-API errors. The extended ten-case suite adds adversarial rights, duplicate-resolution, stale-review and grant tests. Final counts and commands are recorded in the newest [handoff](context/HANDOFF.md). No acquired or sealed example was read.

| Finding | Implemented guard and synthetic checks | Pending decision / limitation |
| --- | --- | --- |
| N-01 | [`lineage.py`](../src/egis_soc/lineage.py) evaluates every artifact's blocked, independent-clearance or verified-parent-inheritance state; unresolved status quarantines the component. Tests cover blocked B child, default/unverified inheritance, documented synthetic inheritance and blocked parent. | Owner must approve rights evidence format, inheritance scope and reviewer. Fixture references assert invented synthetic permission only; code cannot verify a real license. |
| N-02 | [`split_freeze.py`](../src/egis_soc/split_freeze.py) indexes strong exact same-partition signals across distinct components under a separate cap, reports independence findings separately, and blocks freeze until review. Tests cover equal hashes, parent dataset, explicit distinct resolution, missing second review, `same_component` requiring a rebuilt graph, changed cluster count and budget. Generic text remains only a cross-state candidate signal. | Owner must approve exact signals, cap and disposition standard. A reviewed shared ancestor requires a new accepted graph link and complete reassignment/audit; the code does not infer ancestry from a hash alone. |
| N-03 | [`lineage.py`](../src/egis_soc/lineage.py) canonically hashes accepted links, registry version, predecessor and retained history; [`split_freeze.py`](../src/egis_soc/split_freeze.py) binds graph/registry digests to audit and manifest. Tests change evidence, reviewer, relation and version/history without changing membership, then reject stale audit/manifest. | Append-only private storage, authenticated review and amendment sign-off remain external. A reviewer string is not a signature. |
| N-04 | [`evaluation_boundary.py`](../src/egis_soc/evaluation_boundary.py) checks every inference incident against a supplied verified split manifest, and checks restricted grant purpose, manifest, partition and tenant/incident. Synthetic tests reject wrong/missing scope, missing manifest, generic manifest and pre-freeze evaluator access while allowing proposed-manifest annotation and frozen-manifest evaluation. | The host must deliver an authenticated trusted manifest and enforce separate credentials, ACLs, access logs, blinding and W7 unseal; self-consistent bytes and role strings alone cannot grant access. |

The approved [protocol](research-protocol.md) and [annotation guideline](annotation-guidelines.md) were not edited. W1-03 schemas, RQ contrasts, labels, metric denominators, near threshold, primary split algorithm and W6/W7 execution order are unchanged. The [policy](split-freeze-policy.md) marks N-01–N-04 operational semantics **PENDING OWNER REVIEW**; [D-011](context/DECISION_LOG.md) remains the `PROPOSED` record, while scoped [D-012](context/DECISION_LOG.md) accepts the W1 framework and synthetic controls. W1-07 is `DONE` for that limited scope only.

## Ten synthetic test cases

The reviewed policy has 13 sections but no numbered ten-case checklist. The test module therefore maps the requested ten cases to its requirements:

1. Parent, run, concrete-template, collection and event lineage form components; malformed parent/scope/original relations fail.
2. Broad source family alone does not group; missing run, operator or parent-dataset provenance quarantines; reviewed links can connect concrete lineage.
3. A fixed seed and input reordering yield the same whole-component assignment; non-label cluster and heterogeneity fields are counted.
4. Reserved, unknown, exposed or same-pipeline B is never reassigned to A.
5. Mutations/counterfactuals force train, while a held-out collection conflict or B mutation quarantines.
6. Event hashes, normalized evidence, near claims, prompts and source-family overlap produce review findings; unresolved held-out risk blocks.
7. A cross-partition exact incident identity cannot be waived by an unrelated manual rationale.
8. Manifest bytes and IDs are deterministic; altered or noncanonical bytes are detected.
9. A frozen record requires feasible assignment, matching audit/manifest and explicit approval references; a failed gate rejects it.
10. Development cannot read held-out/gold through the adapter; operational facts stay separate; primary pair, V2/V3 input and S2/S3 archive contracts reject mismatches.

## Deferred responsibilities and owner acceptance

- **W2:** obtain separate rights/acquisition authority; verify raw persisted-byte hashes, source-event and incident boundaries, actual operator/run/template/collection lineage, privacy, and independent annotation storage. Do not infer these from sidecar flags.
- **W5:** fix and archive arm-independent draft generation and pair sampling, including candidate/exclusion lists and independent human annotation. Keep diagnostics separate from the primary draft-derived population.
- **W7:** lock exact split/pair/gold/config/metric artifacts, verify S2 forks, run non-test CI calibration and restricted eligibility/access audits, then conditionally unseal and score. This code implements no final scoring or CI simulation.
- **SCOPED W1 ACCEPTANCE / PENDING OPERATIONAL REVIEW:** [D-012](context/DECISION_LOG.md) accepts the Week 1 framework and synthetic controls linked to the historical [D-011](context/DECISION_LOG.md) proposal. The [policy §13](split-freeze-policy.md) operational choices remain pending: sidecar key/equivalence rules, assignment targets/seed, B eligibility and custodian, near-match method/threshold, manifest/approval format, storage and role enforcement. Synthetic passing tests do not establish readiness for real data or a final-evaluation freeze.
