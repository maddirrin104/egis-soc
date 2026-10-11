---
name: egis-handoff
description: Produce a verified EGIS-SOC agent handoff on task completion, quota exhaustion, session switch, context compression, or transfer among Codex, Antigravity and Copilot.
---
# EGIS-SOC verified handoff

1. Read `AGENTS.md`, `docs/context/HANDOFF.md`, `docs/context/CURRENT_STATE.md`, `docs/context/TASK_BOARD.md`.
2. Capture actual `git status --short`, `git rev-parse HEAD`, branch name and diff paths. Do not force commits, stash, reset, or checkout.
3. Enumerate changes with exact paths and distinguish complete/partial/not begun.
4. Record validation command, observed exit code and output path, or `NOT RUN` with reason.
5. Document decisions and pending approval separately. Preserve uncertainties and failures.
6. Update `docs/context/HANDOFF.md` and `CURRENT_STATE.md`. If creating a persistent dated archive, use `scripts/context_status.py --snapshot` after saving HANDOFF.
7. Incoming agent verifies Git state and resumes one specified next action, not the entire project.

Never include credentials or private raw log payloads in the handoff.
