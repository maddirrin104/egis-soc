# Research guardrails (do not treat as optional coding preferences)

| Artifact | Policy | Rationale |
|---|---|---|
| Gold test and OOD labels | Read-only for agents during evaluation; changes require documented human adjudication | Prevent target leakage |
| Incident family / environment split manifests | Freeze before final test; keep a SHA/checksum | Avoid overlapping original incidents and mutated variants |
| Evaluation metrics and denominators | Version before test; never change to improve scores | Prevent metric gaming |
| RQ1 primary: V3 vs V2 | Same NLI checkpoint, same evidence, same thresholds | Causal comparison |
| RQ2 primary: S3 vs S2 | Same incident set, model and access; measure CFR, UCR, CSA | Isolate omission contribution |
| RQ3 OOD | Independent telemetry collection/environment | Measure meaningful shift |
| Gold critical facts | Human-review and independence from draft generator | Avoid circularity |
| Data egress | Splunk read-only, privacy and incident/tenant scope required | Avoid leakage |

When an agent wants to change an item listed here: write a PROPOSAL to `DECISION_LOG.md` explaining motivation, impact on published protocol, changed files, and required human signoff; do not silently mutate a frozen artifact.
