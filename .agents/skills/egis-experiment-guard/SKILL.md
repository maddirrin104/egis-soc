---
name: egis-experiment-guard
description: Check EGIS-SOC machine-learning experiment proposals and implementation changes for claim-label consistency, leakage, frozen tests, baseline comparability, and research integrity.
---
# EGIS-SOC research integrity audit

1. Read `docs/context/RESEARCH_GUARDRAILS.md` and the relevant RQ sections of `docs/EGIS_SOC_Ke_hoach_8_tuan.md`.
2. Identify whether modification touches V0–V3, S0–S3, split manifests, gold annotations, primary metric definitions or OOD protocol.
3. Confirm test IDs do not leak via synthetic variants, incidents, collection, environment, evaluation prompts or model tuning.
4. Confirm **Supported** requires full factual support and **Insufficient** is distinct from direct contradiction.
5. Confirm claims and critical facts have independent evidence/provenance; no self-evaluation using generator-created gold.
6. Never change frozen evaluation surfaces without a written protocol amendment and human approval.
7. Record pass/fail/unknown findings with file paths, proposed minimal fixes and exact validation required.
