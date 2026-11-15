# W8-01 public-safe package review checklist

This checklist is a scope record for the owner's requested public-remote push. It does not approve research data, a merge to `main`, or production use. Verify the exact staged diff and remote ref before treating a branch as published.

| Check | Current W8-01 finding |
| --- | --- |
| Public source scope | The package branch starts from public `origin/main`. The 126 W5-CP synthetic paths were re-hashed with zero drift; W4 dependencies and W6–W8 synthetic paths were selected explicitly. Unpublished local W2–W4 history is not an ancestor of this branch. |
| Private raw data | Exclude ignored `data/raw/`, `data/private/`, private normalized/export roots, real telemetry and private Splunk credentials. No such content is intentionally included in W8 synthetic artifacts. |
| Review storage | Keep authenticated report snapshots and audit logs outside Git in a user-restricted directory. They are operational review records, not evaluation gold. |
| Sealed evaluation | Exclude split IDs, held-out A/B/OOD labels, final evaluation fixtures, protected metric inputs and any unsealed test material. W8 does not need them. |
| Credentials | Never stage `.env`, bearer tokens, password hashes from a live setup, `.pem` or `.key`. `.env.example` contains blank values only. |
| Source rights | W2 source/rights and custody decisions remain separate; synthetic fixtures do not grant redistribution rights for real datasets. |
| Archives | W5-08 v2, W6 v3, W7 v8 and current W8 v5 checks passed in the isolated worktree. Historical W8 v3/v4 remain saved; do not replace them. |
| Research claims | Mark W8 demo as synthetic engineering; no Macro-F1, CFR, UCR, CSA, confidence interval, annotation agreement or OOD result is available. |
| Release action | The owner requested commit and push. Exact staged-content review, a fresh commit checkout and remote-ref verification are release gates for this synthetic branch. A dependency reinstall and merge to remote `main` are outside this package. |

The package should use an exact allowlist, checked file bytes and staged-content screening for secrets/PII/raw records. The offline demo must be reproduced from the committed tree. Do not bulk-stage the original dirty research worktree.
