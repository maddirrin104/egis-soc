# EGIS-SOC project brief

**Source of authority**: `docs/EGIS_SOC_Ke_hoach_8_tuan.md` v1.0 dated 2026-10-09. This is an operational summary, not a replacement for the original.

- Project: Evidence-grounded Incident Summarization for SOC Analysts.
- Planned period: 2026-10-12 through 2026-12-06 (8 weeks).
- Input: already scoped incident bundle (alerts + relevant telemetry). Output: structured incident report with atomic claims, cited evidence, verification status, omission checks and analyst review.
- Pipeline: ingestion/provenance → scoped retrieval (structured + BM25) → LLM draft → rule+NLI verification AND independent critical-fact omission detection → controlled repair (max 2 rounds) → analyst approval.
- RQ1: hybrid verification versus pretrained NLI-only under matched evidence/checkpoints (V3 versus V2 primary).
- RQ2: omission-aware repair versus verification-only (S3 versus S2 primary), assess CFR, UCR, CSA; proposed non-inferiority margin on absolute UCR increase: 3 percentage points, lock before test.
- RQ3: independently sourced OOD environment; simple IP/hostname substitutions are perturbation robustness, not independently sufficient as OOD evidence.
- Dataset *targets, not observations*: 80 incidents aspirational; fallback 50–60 with held-out OOD; 10–15 pilots by W2.
- Main tech: Python, FastAPI/Pydantic, Pandas/SQLite/JSONL, BM25, scikit-learn TF-IDF+LR, pretrained NLI, deterministic rules, lightweight local generation, Streamlit and read-only Splunk integration.
- W1: research protocol, schemas, annotation policy, threat model, baselines and dataset/license selection.
- W2: normalization, evidence identity/provenance and annotated pilots.
- W3/W4: retrieval+NLI baselines then hybrid verifier.
- W5: structured generation, omission/repair and review UI.
- W6: independent OOD/perturbations and profiling.
- W7: ablation/statistics/frozen runs.
- W8: reproducible demo and paper/report.

No results have been established merely by including this brief. Mark empirical outcomes only after saving outputs and test logs.
