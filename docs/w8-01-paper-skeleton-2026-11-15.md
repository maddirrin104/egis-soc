# EGIS-SOC paper/report skeleton — W8-01, 2026-11-15

**Status:** Draft structure only. Methods below are planned or implemented as explicitly marked. Confirmatory results, real pilot acceptance and final dataset descriptions are unavailable. No numbers in this draft are scientific findings.

## 1. Abstract

EGIS-SOC is a proposed evidence-grounded summarization workflow for already triaged security incidents. It combines incident-scoped retrieval, atomic cited claims, hybrid verification, source-grounded omission screening, controlled repair and analyst review. **Results placeholder:** RQ1–RQ3 outcomes are NOT RUN; no effectiveness claim can yet be made.

## 2. Introduction

Describe the analyst need for traceable incident summaries and the risks of unsupported claims and missed critical facts. Define the scope as a provided incident bundle, not incident detection or autonomous remediation. Frame C1–C3 as research hypotheses requiring empirical comparison.

## 3. Related Work

Use the verified [literature matrix](literature-matrix.md) and [dated search log](literature-search-log.md) for source attribution. Resolve any remaining full-text and novelty questions before publication. **No new academic references are asserted here.**

## 4. Problem Definition

Input: provenance-backed incident/tenant-scoped evidence and an already triaged bundle. Output: structured report with atomic factual claims, cited evidence, S/C/I prediction, review routing, omission candidates and analyst decision. Missing evidence is Insufficient; a valid citation ID alone does not prove factual support.

## 5. EGIS-SOC Architecture

Use the approved [architecture v1](architecture-v1.md) as design context. Distinguish inference, operational review and isolated evaluation gold. The current W8 [synthetic integration](w8-00-synthetic-integration-2026-11-15.md) implements an offline vertical slice and local review service; real-source admission and production deployment are pending.

## 6. Dataset and Annotation Methodology

Describe candidate source rights, immutable provenance, incident and tenant boundaries, connected lineage, split isolation and independent S/C/I plus critical-fact annotation using the approved [annotation guidelines](annotation-guidelines.md). **Observed status:** W2 has no qualifying accepted real pilot cohort or independently reviewed gold for final evaluation. Do not treat W8 authored fixtures or operational fact inventory as gold.

## 7. Evidence Retrieval

Describe structured filtering followed by incident-scoped BM25 and an exact evidence snapshot/ID set. Explain retrieval failure and cross-scope rejection. **Implemented engineering:** synthetic W3/W8 path; real eligible retrieval evaluation is pending.

## 8. Hybrid Evidence Verification

Describe V0 rule checks, V2 pinned NLI baseline and V3 fusion with Supported, Contradicted and Insufficient plus a separate review flag. RQ1 compares V3 versus V2 on identical evidence/checkpoint under [approved protocol](research-protocol.md). D-032 thresholds and real-data use gates remain open. W8 fixed logits are a mock, not NLI performance.

## 9. Omission-Aware Controlled Repair

Describe S2 verified fork, source-only operational candidates, S3 source-exact proposals, maximum two repair rounds, re-verification and retained negative trace. RQ2 requires independent critical-fact gold and matched S3/S2 CFR/UCR/CSA. W8 demonstrates mechanics only.

## 10. Experimental Design — RQ1/RQ2/RQ3

- **RQ1 planned:** matched V3 versus V2, same NLI checkpoint, evidence, pair population and approved metrics.
- **RQ2 planned:** matched S3 versus S2 from one frozen fork, independently annotated critical facts, CFR/UCR/CSA and repair diagnostics.
- **RQ3 planned:** independently operated OOD Environment B, lineage/overlap audit and absolute plus relative performance reporting.

The [approved research protocol](research-protocol.md) controls hypotheses, denominators, intervals, calibration and ordering. W7 method lock and official calibration precede held-out access.

## 11. Results — NOT RUN placeholders

| Result | Status | Required evidence before writing |
| --- | --- | --- |
| RQ1 Macro-F1, Supported Precision, False Support Rate | NOT RUN | Eligible independent gold, locked matched pairs, D-032 and W7 gate |
| RQ2 CFR, UCR, CSA and repair-induced errors | NOT RUN | Fixed S2/S3 population and independent critical facts |
| RQ3 OOD performance | NOT RUN | Independent B qualification, locks and authorized held-out run |
| Analyst time/efficiency | NOT MEASURED | Actual human study or explicitly labeled proxy |

Synthetic W8 test passes belong in an engineering validation appendix, not in these results cells.

## 12. Discussion

After real results exist, discuss supportive, negative and inconclusive outcomes separately. Examine citation relevance, source-family differences, repair-induced errors and review burden without assuming improvement.

## 13. Threats to Validity

Small incident/lineage counts, correlated claims, source-selection bias, annotation subjectivity, log-format-specific rules, missing telemetry, draft dependence, extra S3 claims and OOD independence uncertainty. Explain how audits and sensitivity analyses address each when actually run.

## 14. Limitations

Current W8 is synthetic/offline, local and single-owner. Authentication protects only configured local analyst mutations; file-system ACLs and human custody remain operational requirements. Real Splunk and W8 actual-model inference are NOT RUN. W2/M1, W4-05, W5-09, D-032, independent B and W7 calibration block confirmatory acceptance.

## 15. Conclusion

**Draft placeholder:** State only the implemented architecture and testable research questions until actual evidence supports a scientific conclusion. Do not claim reduced analyst time, improved accuracy, safety or SOC readiness from synthetic tests.

## 16. Reproducibility Statement

Record exact code commit, source hashes, eligible dataset rights and lineage manifests, model revisions/digests, prompt/decoding settings, environment versions, seeds, frozen test population, evaluation scripts, per-incident outputs, missing-data handling and independent annotation audit. The current W8 synthetic archive is reproducible within the dirty development environment; a clean complete checkout and real-data reproduction are unverified.
