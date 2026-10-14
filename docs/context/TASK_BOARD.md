# Task board (statuses require human/verified evidence)

| Task | Priority | Status | Acceptance |
| --- | --- | --- | --- |
| W1-01 Context verification | P0 | DONE | Context files and Git status checked; active VS Code Codex instructions and `egis-handoff` discovery, no conflicts, and validation/handoff evidence confirmed and approved by user on 2026-10-12 |
| W1-02 Research protocol | P0 | DONE | Project owner approved [protocol v0.2](../research-protocol.md) A-01–A-04 as a methodological specification on 2026-10-13, A-03 with fixed 1,000-dataset/no-automatic-extension conditions; exact SHA-256 and preserved D-004/D-005/D-006 proposal history are in [D-007](DECISION_LOG.md). Protocol is staged for Git tracking; the [latest handoff](HANDOFF.md) records source/guardrail review, structural/context/whitespace/acceptance and unrelated-change checks. W1-04/W1-05/W1-07/W5/W7 artifacts, calibration, final-test locks and empirical claims remain pending. |
| W1-03 Data schemas | P0 | DONE | Project owner explicitly approved completion on 2026-10-14 after reviewing the remediation and acceptance reports. Inference bundles exclude evaluation gold; gold-label provenance and raw snapshot references are explicit; scope and nested gold references are immutable through normal model APIs. The full schema suite passed again (10 tests, exit 0); evidence and limits are in the [latest handoff](HANDOFF.md). W1-04 annotation, W2 ingestion and W1-07 split/access controls remain future work; no empirical result is claimed. |
| W1-04 Annotation guideline | P0 | TODO | S/C/I rubric, gold facts, disagreements, examples |
| W1-05 Dataset assessment | P0 | TODO | Source/license matrix, W2 pilot candidates, independent ENV-B plan |
| W1-06 Threat model | P1 | TODO | Threat boundaries, abuse cases, proposed security tests |
| W1-07 Split/freeze policy | P0 | TODO | Group leakage control, ID/OOD distinction, freeze procedure |
| W1-08 Literature matrix | P1 | TODO | Related works, comparison matrix, proposed research gaps |
| W1-09 Architecture v1 | P0 | TODO | Pipeline diagram, stage contracts, deployment boundaries |

Status values: TODO / IN_PROGRESS / BLOCKED / DONE. DONE requires an evidence path, test output or reviewed document, not merely agent assertion. Only one task may have a principal writer at a time.
