# W8-01 local analyst review and packaging — 2026-11-15

> Historical W8-01 development record. In the public synthetic branch, the current create-only archive is [W8 v5](../experiments/w8_02_synthetic_demo_v5/) and the available offline suite passed 182/182. The v4 archive and 527/527 run below refer to the larger local development worktree.

## Scope

W8-01 extends the synthetic W8-00 report view. It uses W5's report-bound `ReviewStore` hash-chain reader through `AuthenticatedReviewStore`, with immutable numbered report snapshots. No W5 S1/S2/S3 report logic, evaluation metric, gold record, split or historical archive was edited. The review store is for **synthetic operational review**, not research annotation or a production multi-tenant service.

## Source preservation before edits

Preflight on the local development `main` HEAD `0228669522df4eb2197a1bd982f9fa5e519d7986` found 37 tracked modified, 314 untracked, zero staged and 36,341 ignored paths. An owner-restricted external snapshot was created under the owner's private `%LOCALAPPDATA%/EGIS-SOC/backups/` directory before code changes. Its manifest SHA-256 is `1fc20db50fddef6e5f6ebb0d6006b492f907d0f4ef4ed230cc37c8c4d8c3facf`. Independent verification checked 266 copied files, relative paths, sizes, SHA-256 values and file ACL allowlists. Exclusions: 59 generated/historical archive paths, 23 source-rights/custody documents, two controlled proposals and one editor configuration file. All ignored files stayed out. This is a recoverable **selected-file** snapshot, not a full-project backup or Git commit. The private backup payload and manifest are not included in this public demo package.

A second owner-restricted snapshot was made after implementation under the same private backup root. Its manifest SHA-256 is `ec7dd02ef755bf04361264a00b5cd75f3500175e65842cfe03ad52bcf3acbee3`; independent count/path/size/hash/file-ACL verification passed for 278 copied files. It excludes 88 changed paths under the same rules. It was taken before the final context/handoff wording; those final bookkeeping edits are not in that snapshot. The first snapshot retains the exact pre-edit bytes.

## Local authentication

- The server starts read-only when review credentials are absent. Both `EGIS_REVIEWER_ID` and `EGIS_REVIEW_PASSWORD_HASH` must be present to enable review; partial configuration fails at startup.
- Generate a scrypt verifier interactively with `scripts/w8_review_password.py`. The password is not passed on the command line or written to source. The ID comes only from server configuration; a request cannot choose or override it.
- The server issues a random bearer token in RAM after login. It expires after 60–3600 seconds (default 900) and is revoked at logout. The browser keeps it only in page memory. Cookies are not used, so no ambient browser credential is sent with cross-site requests.
- The server binds `127.0.0.1`. An authenticated start requires an existing external directory whose Windows ACL check permits only the owner, SYSTEM and Administrators. `scripts/w8_review_dir.ps1 -Create` creates such a directory without overwriting an existing one; the server runs its `-Check` form before serving.
- This is a single-owner local mechanism. It is not an IAM system, a production network security assessment or authorization for real evidence.

## Versioned review workflow

The initial synthetic report becomes version 1 with status `DRAFT`. `start_review` creates version 2 and `REVIEW_PENDING`. Claim actions (`accept_claim`, `reject_claim`, `request_claim_changes`) and notes each create another immutable version. Only a source-verifier-supported **final** claim can be accepted. `approve_report` requires every final claim accepted and no outstanding report-change request; `reject_report` records a final rejection. Finalized versions reject further actions. `start_revision` creates a new `DRAFT` child linked to the approved/rejected parent. Requests for claim or report changes remain review overlays; they do not alter factual claims, raw evidence or citations. A factual rewrite requires a future verified pipeline output before it could be promoted.

Each action records authenticated reviewer ID, UTC timestamp, incident/tenant ID, stable report ID, previous/new version and status, optional claim ID, reason, source snapshot hash and audit record ID. The W5-derived JSONL audit chain is stored separately from immutable `version-######.json` snapshots in the external directory. Reads replay the chain against every version and fail closed on missing, altered or orphaned records. A partial write after a crash remains a blocker requiring owner recovery; no automatic overwrite occurs. File ACLs and external backup are necessary because a hash chain alone cannot prevent a privileged actor from rewriting an entire local store.

Review exports preserve the original report's citations, verification trace, repair history, omissions and uncertainty. They add review decisions and keep `gold_status: NOT_GOLD`; an analyst-approved synthetic report is **not** a human-reviewed evaluation annotation.

## Local API

| Endpoint | Purpose |
| --- | --- |
| `POST /api/login`, `POST /api/logout`, `GET /api/session` | Local bearer session lifecycle |
| `GET /api/reviews/{incident}` | Latest immutable version, authenticated |
| `GET /api/reviews/{incident}/versions/{n}` | Historical immutable version, authenticated |
| `GET /api/reviews/{incident}/audit` | Verified audit records, authenticated |
| `POST /api/reviews/{incident}/actions` | Exact action schema, authenticated ID and optimistic `expected_version` |
| `GET /api/reviews/{incident}/export` | Reviewed synthetic JSON export, authenticated |

The existing W8 synthetic report and evidence routes remain read-only. Unknown incident IDs, cross-incident evidence IDs, malformed claims, stale version writes and unauthenticated mutations fail closed. Only two allowlisted synthetic incidents are available; the sole local owner can inspect both. There is no real multi-tenant authorization claim.

## UI and setup

The existing W8 HTML/JS view now has login/logout, incident selection, timeline, S/C/I traces, citations/evidence, omission and repair views, version/status, claim and report actions, audit records and reviewed JSON export. Report content is rendered with `textContent`. The UI remains a local static page over WSGI rather than a second Streamlit implementation; this differs from the original planned Streamlit deliverable.

See the root `README.md` for Windows setup, dependency files, interactive password-verifier generation, ACL-protected review-directory creation, API/UI start, offline archive checks and troubleshooting. `.env.example` contains blank credentials and is not automatically loaded. Review storage, the backup and any future credential configuration stay outside the public package.

## Model and research boundaries

The offline positive/negative fixtures and fixed-logit adapter are unchanged; no actual LLM or pinned NLI inference was run in W8-01. The opt-in Splunk transport was not connected to a real server. The [adapter card](model-cards/w8-01-adapters.md), [paper skeleton](w8-01-paper-skeleton-2026-11-15.md) and [public-safe checklist](w8-01-public-safe-checklist.md) mark planned experiments separately from synthetic engineering. W2/M1, W4-05, W5-09, D-032, independent Environment B, official W7 calibration and held-out RQ1–RQ3 remain open.

## Validation record

Focused W8 **15/15 PASS**; full offline **527/527 PASS**. W5-08 v2, W6 v3, W7 v8 and create-only W8 v4 archive checks passed. W8 v4 manifest SHA-256 is `c6567e1a196d08a38fe479e75ef486ca08d820d28de18c1a22d21d2515f7b390`. JavaScript and PowerShell syntax checks passed; editor diagnostics on new Python files were empty. Browser review smoke used only a disposable synthetic reviewer and left the report at `REVIEW_PENDING`; no real analyst approval was claimed. The first W5 archive-check invocation omitted mandatory model/digest arguments and exited 2; rerun with the pinned values passed. Final context status and Git whitespace results are recorded in the latest `docs/context/HANDOFF.md`.
