# Decision register

This is a proposal-and-approval register, not a record of automatic agent authority. When a proposal is approved, include an approver and date; otherwise keep status `PROPOSED`.

| ID | Date | Decision / reference | Status | Approver | Impact |
|---|---|---|---|---|---|
| D-001 | 2026-10-11 | Adopt file-based shared context, per-task skills, checked handoffs | PROPOSED | pending | Agent development harness only |
| D-002 | 2026-10-11 | Codex → Antigravity → Copilot; local LLM review-only | USER-DIRECTED | User request | Fallback permissions |
| D-003 | 2026-10-11 | Preserve source plan v1.0 as research baseline, amendments gated | PROPOSED | pending | Research reproducibility |
| D-004 | 2026-10-12 | W1-02 draft 0.2 Phase C.2: propose RQ3 F1/SP-only relative-robustness inference with B FSR diagnostics; primary RQ1 pairs from arm-independent frozen drafts; clarify `delta=0.03` as pooled-UCR-rate margin. See protocol Sections 2, 3, 6, 8, 10. No frozen artifact is changed. | SUPERSEDED 2026-10-13 | Project owner; see D-007 | Historical proposal; adopted scope is in A-01/A-02/A-04 under D-007. Later locks remain pending. |
| D-005 | 2026-10-12 | W1-02 Phase C.3 A-02/A-03 amendment proposal: retain `delta=0.03` only as an unvalidated pooled-UCR research tolerance with absolute-count qualification; add pre-test CI calibration, W1-07/W7 ownership, proposed coverage/type-I acceptance criteria and exploratory fallback. See protocol Sections 6, 8, 10. A-01/A-04 unchanged; no calibration run or frozen artifact changed. | SUPERSEDED 2026-10-13 | Project owner; see D-007 | Historical proposal; adopted A-02/A-03 scope and conditions are in D-007. No calibration is claimed. |
| D-006 | 2026-10-12 | W1-02 final A-03 correction proposal: replace nominal-95%-lower-bound coverage demand with a proposed 93% usable-coverage and 7% full-claim Type I Monte Carlo-bound screen, using at least 1,000 outer datasets per scenario, optional 3,000-run top-up, and the proposed 10,000 inner bootstrap resamples. Define composite-null false full-H1 confirmation, separate power, non-test boundary/stress scenarios and W7 compute gate. See protocol Section 8 and A-03. No calibration run or frozen artifact changed. | SUPERSEDED 2026-10-13 | Project owner; see D-007 | Historical proposal; 93%/7% screening adopted, but optional 3,000-run top-up rejected in favor of fixed 1,000 and separate approval for any valid sequential extension. |
| D-007 | 2026-10-13 | W1-02 protocol v0.2; SHA-256 `B80A39F0E08CC8D22B1A65776355D1C34D81E7E0F2721A0C34A08CA9C34C1E0A`. A-01: RQ1 three gates, RQ3 two relative-robustness gates and mandatory descriptive B FSR. A-02: `delta=0.03` pooled-UCR research tolerance and absolute-count diagnostics. A-03: paired lineage-cluster bootstrap; nominal 95% endpoint intervals and 5% full-claim Type I target; 93% usable-coverage lower-bound and 7% full-claim Type I upper-bound **screening** tolerances; fixed initial 1,000 independent simulated datasets per scenario; no automatic top-up, with any sequential extension needing a separately approved statistically valid pre-test procedure. Failed/inconclusive calibration bars the affected confirmatory RQ. A-04: arm-independent draft-derived primary pairs, strict lineage isolation, independent B and identical archived S2/S3 state. | APPROVED | Project owner (user), explicit methodological approval on 2026-10-13 | Approval is for methodological specification only; W1-04/W1-05/W1-07/W5/W7 artifacts, CI calibration, final-test locks and empirical claims remain pending. Passing screening is not proof of strict nominal coverage/alpha or SOC safety. |

## New decision template

### D-XXX — Title
- Date / author / approving human:
- Status: PROPOSED | APPROVED | REJECTED | SUPERSEDED
- Source / motivating evidence:
- Alternatives and trade-offs:
- Affected paths, baselines, evaluation protocol:
- Decision and rationale:
- Verification:
