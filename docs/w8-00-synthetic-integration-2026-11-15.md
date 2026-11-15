# W8-00 synthetic/offline system integration — 2026-11-15

> Historical W8-00 record. The public synthetic package now uses [W8 v5](../experiments/w8_02_synthetic_demo_v5/) and optional authenticated review described in the [README](../README.md). The v3 archive below records the earlier W8-00 source state.

## Scope and data flow

This is an engineering demo, not a research evaluation or a real incident pilot. The fixed positive and negative synthetic fixtures enter the W1 `IncidentBundle`/`EvidenceEvent` contracts, W3 incident-scoped BM25 retrieval, a deterministic draft adapter, W5 atomization/S1, authored synthetic citation review, W4 V3 through W5 S2, W5 operational omission inventory, S3 controlled repair, and W5 final report projection. The W8 API and browser view expose only these two allowlisted fixtures. No sealed evaluation path is accepted. Original W4–W7 archives and controlled protocol surfaces are unchanged.

The NLI backend returns fixed entailment logits to exercise the existing V3 rule/fusion path. It does **not** run the pinned model. The `model_id` and `model_revision` fields inside W5 V3 traces identify the W5 adapter contract; they do **not** show that checkpoint was executed in W8. `w8_demo.nli_adapter` and `w8_demo.draft_adapter` mark this distinction. The draft and citation judgments are authored synthetic fixture content, not independent human gold. Operational source facts are not evaluation gold, and `candidate_unmentioned` is not a confirmed critical omission or CFR result.

## Reproduce locally on Windows

From the repository root, use the configured `.venv` and installed `requirements-w7.txt` dependencies. The W8 path adds no package dependency. Commands below are PowerShell:

```powershell
$env:PYTHONPATH='src;scripts'
& .\.venv\Scripts\python.exe scripts/w8_offline_demo.py --check
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_w8_*.py' -v
& .\.venv\Scripts\python.exe scripts/w8_demo_server.py --port 8768
```

Open `http://127.0.0.1:8768/`, select a case and run it. The server binds loopback only. It has no persisted analyst review action. A new create-only archive uses `scripts/w8_offline_demo.py --output <new-empty-path>`; the current archive is `experiments/w8_00_synthetic_demo_v3/`. The checker re-runs both fixed cases, compares stable report content, fixture and source hashes, exact report bytes and the file set. It normalizes only measured S3 latency for rerun comparison. A failed check raises a reason-coded exception and exits nonzero. Earlier in-session `v1` and `v2` archives remain untouched as intermediates before stylesheet and malformed-path hardening; their current-code checks are expected to fail.

## API and UI

The API is a local WSGI selection layer over the W5 report contract, matching the existing W5 local review stack without introducing a second review store or a new web dependency. The W5 report builder remains the source of report semantics. Routes:

| Route | Function |
| --- | --- |
| `GET /api/health` | Local synthetic status and disabled review mutations |
| `GET /api/incidents` | Two allowlisted synthetic incident IDs |
| `POST /api/run` with `{"case":"positive"}` or `negative` | Re-run scoped pipeline and return report |
| `GET /api/reports/{incident_id}` | Re-run and retrieve structured report |
| `GET /api/evidence/{incident_id}/{evidence_id}` | Retrieve only an in-scope evidence record |
| `GET /api/export/{incident_id}` | Download synthetic JSON report |
| `/api/reviews` | Disabled, HTTP 403; authenticated identity is not implemented |

The UI shows incident and synthetic status, timeline, final and draft claims, S/C/I verdicts, citations and evidence details, omission candidates, repair history, review queue, structured report and export link. It labels final claims as verified development output and analyst review as pending. The existing W5 `w5_review.html`/server is kept for historical fixed-packet review; the W8 view is a small case-selection extension over the same W5 report format. Streamlit would add a second UI/runtime for this two-case offline slice, so it is not used here.

## Two demo cases

| Case | Input | Observed output |
| --- | --- | --- |
| Positive `SYN-W8-POSITIVE` | Synthetic 4625, 4624 and Sysmon 1 events on WS01; three source-bound evidence IDs | One exact record R2 success claim is V3 Supported, reviewed citation E-P2 is in scope, and the final report retains it. No compromise claim is made. R1 is an unmentioned operational candidate; Sysmon process inventory is unresolved under the current logon-only W5 policy. |
| Negative `SYN-W8-NEGATIVE` | Synthetic failed logon E-N1, draft asserts success and compromise; raw text includes an inert prompt-injection string | The success claim is Contradicted/removed, compromise is Insufficient/abstained, the failed-logon fact is `candidate_unmentioned`, and an explicit authored one-round add proposal is reverified Supported with E-N1. The original claims and review warnings remain in the trace. |

Both outputs are `NOT_GOLD`; neither measures UCR, CFR, CSA, time saving, real model quality or RQ1–RQ3. The fixed-logit backend deliberately tests whether the rule path blocks unsupported claims even when the mocked NLI branch favors entailment.

## Splunk boundary and security

The offline fixture source is marked `synthetic:splunk-offline-export`; it does not claim to be a live Splunk response or the W2 `splunk_export_jsonl_v1` parser profile. The opt-in `SplunkReadOnlySearch` transport is separate from the demo. It requires HTTPS, an explicit enable flag and in-memory token, index/host allowlists, bounded time and event/response limits, and a fixed search shape with no caller-supplied SPL. It has fake-transport tests only. It does not persist returned bytes or admit them as W1 evidence; real use still needs source authorization, custody, exact provenance, W2 ingestion and approved incident/tenant boundaries. **REAL SPLUNK DEMO: NOT RUN.** No live credentials were supplied or used.

The W8 API rejects unknown cases, foreign evidence IDs and review writes. Review actions remain disabled because a session token/self-attested reviewer is not an authenticated analyst identity. The browser renders report content with `textContent`; raw log prompt-injection text stays data. The archive and API contain only authored synthetic bytes.

## Validation and remaining gates

Focused W8 tests cover positive/negative claims, citation relevance, scope, injected raw text, archive tamper/replay, API export and disabled mutations, plus bounded fake Splunk transport. Full offline regression and final hash/check results are recorded in `docs/context/HANDOFF.md` after execution. The first full regression invocation with `PYTHONPATH=src` alone produced two W3 script-import errors; the corrected invocation includes `src;scripts`.

W8-00 is **PARTIAL** against the requested full engineering criteria: the synthetic vertical slice, local API/UI and offline archive run, while authenticated analyst mutation, real Splunk-to-report ingestion, actual local LLM inference in this W8 slice, true source-specific real pilot, calibrated evaluation and held-out RQ1–RQ3 remain open. W2 human-reviewed gold is blocked, Environment B independence is unknown, D-032 is proposed, and official W7 calibration/frozen final evaluation have not run.
