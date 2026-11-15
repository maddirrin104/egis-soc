# EGIS-SOC

**Evidence-grounded incident summaries for SOC analysts.** EGIS-SOC starts with an already triaged incident bundle, retrieves evidence within its incident and tenant, checks atomic claims and citations, screens for omitted source facts, and prepares a report for analyst review. It does not detect incidents from an unbounded stream or remediate systems.

> **Current release scope:** a reproducible **synthetic, offline engineering demo**. Its draft is authored and its NLI logits are fixed test values. The W8 demo does not run an LLM, the pinned NLI checkpoint or a real Splunk search. Analyst approval of a demo report is separate from research gold annotation.

## What you can run

| Capability | Current state |
| --- | --- |
| Incident-scoped W1/W3 retrieval → W4/W5 verification, omission check, controlled repair and report | Two allowlisted synthetic cases; positive and negative paths tested |
| Browser report view and JSON export | Local WSGI server on `127.0.0.1:8768` |
| Analyst review | Optional single-owner login, expiring bearer session, immutable report versions and audit records in an external private directory |
| Actual local LLM/NLI inference and real Splunk | **Not run in W8**; separate model, source-use and custody gates apply |
| Confirmatory RQ1–RQ3 | **Not run**; independent gold, Environment B, D-032 and W7 calibration remain open |

The positive fixture produces one source-exact Supported final claim citing E-P2. The negative fixture removes a Contradicted claim, abstains on an Insufficient causal claim, flags an unmentioned source fact and re-verifies a controlled synthetic addition. These are integration observations, not accuracy or safety measurements.

## Offline quick start (Windows)

Tested locally with Python 3.14.7 and Pydantic 2.14.1. Run from the repository root in PowerShell:

```powershell
py -3.14 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-w8-offline.txt
$env:PYTHONPATH = 'src;scripts'
& .\.venv\Scripts\python.exe scripts/w8_offline_demo.py --check
& .\.venv\Scripts\python.exe scripts/w8_demo_server.py --port 8768
```

Open <http://127.0.0.1:8768/>, choose **Positive evidence case** or **Unsupported claim and omission case**, then select **Run pipeline**. The offline mode needs no Splunk account, network service, model weights or reviewer credentials. Review mutations stay disabled until configured. If your Python launcher does not provide `py -3.14`, create the virtual environment with a local Python 3.14 interpreter.

The current create-only archive is [`experiments/w8_02_synthetic_demo_v5/`](experiments/w8_02_synthetic_demo_v5/). The archive checker verifies its report bytes, fixed fixtures, source files and dependencies, then replays both cases with only nondeterministic repair timing normalized. Create another archive only at a new output path; do not replace historical versions.

## Optional authenticated local review

This is a single-owner **synthetic review** workflow. It uses no built-in username, password or secret. Generate a password verifier interactively and create a user-restricted directory outside Git:

```powershell
$env:PYTHONPATH = 'src;scripts'
$env:EGIS_REVIEWER_ID = 'local-owner'
$env:EGIS_REVIEW_PASSWORD_HASH = (& .\.venv\Scripts\python.exe scripts/w8_review_password.py)
$env:EGIS_REVIEW_SESSION_SECONDS = '900'
$env:EGIS_REVIEW_DIR = (& powershell -NoProfile -File scripts/w8_review_dir.ps1 -Create)
& .\.venv\Scripts\python.exe scripts/w8_demo_server.py --review-dir $env:EGIS_REVIEW_DIR --port 8768
```

Keep the resulting directory path for later starts: the create helper refuses to overwrite it, and the server checks its Windows ACL before enabling review. The ACL permits only the owner, SYSTEM and Administrators. Keep the password verifier and review records out of the repository. [`.env.example`](.env.example) lists configuration keys with blank secrets; the application does not load it automatically.

The browser holds its random bearer token only in memory. Sessions expire after 60–3600 seconds (default 900) and logout revokes them. No cookies are used. Review actions create numbered immutable snapshots linked to the previous version and a report-bound audit record. The original evidence, citations and verification trace remain unchanged. A hash chain detects many accidental or partial changes; local storage is not tamper-proof against a privileged actor. Claim-change requests are review notes until separately re-verified. Approval never creates evaluation gold.

## Tests and reproducibility

The minimal offline dependency is in [`requirements-w8-offline.txt`](requirements-w8-offline.txt). The optional [full development requirements](requirements-w8.txt) include the existing pinned scikit-learn, PyTorch and Transformers versions plus tested SciPy and psutil versions. Installing packages does **not** download model weights through this demo. A clean dependency reinstall on another machine remains unverified.

```powershell
$env:PYTHONPATH = 'src;scripts'
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_w8_*.py' -v
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -q
& .\.venv\Scripts\python.exe scripts/w8_offline_demo.py --check
& .\.venv\Scripts\python.exe scripts/w6_synthetic_profile.py --check
& .\.venv\Scripts\python.exe scripts/w7_synthetic_infra.py --check
```

The W8-01 development worktree passed 15 focused and 527 full offline tests; a clean public checkout must be tested separately because it contains a reviewed synthetic subset of the local source tree. See the [integration record](docs/w8-00-synthetic-integration-2026-11-15.md), [review and packaging record](docs/w8-01-local-review-2026-11-15.md), and [model/adapter card](docs/model-cards/w8-01-adapters.md) for exact boundaries.

## Actual models, Splunk and research use

The existing NLI adapter identifies `cross-encoder/nli-distilroberta-base` revision `b14d131f9d32668a5e6a982729b57ff6ed5dfcbd`; the W5 local generator records an exact Ollama model tag and digest. W8 fixed logits are **not** execution of that NLI revision, even though W5 trace fields retain its contract identifier. Do not download, replace or interpret a model checkpoint as tested here.

The W8 Splunk transport is opt-in, read-only and tested with a fake transport. It has no route into the offline report demo. A live read-only demonstration needs explicit owner authorization, restricted Splunk role/indexes, secure credentials, source-specific rights and custody, approved W2 ingestion, and reviewed incident/tenant boundaries. **Real Splunk demo: not run.**

The [research protocol](docs/research-protocol.md) and [annotation guidelines](docs/annotation-guidelines.md) govern any later evaluation. W2/M1 human-reviewed pilots, W4-05, W5-09, D-032, independent Environment B and official W7 calibration remain open. No Macro-F1, CFR, UCR, CSA, confidence interval, analyst-time gain or OOD effectiveness is established by the synthetic demo. The [paper skeleton](docs/w8-01-paper-skeleton-2026-11-15.md) leaves those results blank.

## Data and release boundaries

Keep raw telemetry, private source/custody records, credentials, review logs, model caches, sealed gold and test/OOD material outside a public package. The ignore rules are only a convenience, not access control. Review an exact file allowlist and staged diff before publication; the [public-safe checklist](docs/w8-01-public-safe-checklist.md) records remaining checks. The public demo is a synthetic subset, while the local working tree has additional uncommitted/private W2–W7 work.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `ModuleNotFoundError` during tests | Set `PYTHONPATH=src;scripts` in the same PowerShell session. |
| Review returns 403 | Configure both reviewer environment variables and a private external review directory. The offline report remains available. |
| Review returns 401 | Sign in again after expiry or logout. |
| Review storage fails validation | Check its ACL and audit/version files; do not overwrite a partial or tampered store automatically. |
| Archive reports drift | Keep the old archive intact, inspect changed source/fixtures, and create a new version at a new path. |
| No model or Splunk service | Use the offline demo; neither service is required. |
