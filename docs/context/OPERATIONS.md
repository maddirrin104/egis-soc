# Operating procedure for multi-session agents

## On first setup
1. Open the actual EGIS-SOC repository as the VS Code workspace root.
2. Merge the starter package into the root. Never overwrite pre-existing `AGENTS.md`, `.github` instructions, or `docs/context` without reviewing a diff.
3. Copy selected upstream skill folders to `.agents/skills/` (see `scripts/install-context-skills.ps1`). Record pinned upstream commit. Review third-party SKILL.md and scripts before activation.
4. Verify visible instructions/skills in each provider UI; not every VS Code chat integration uses the same harness.
5. Start Codex with `prompts/start-session.md`.

## On every new session
- Read the brief, state, handoff and current selected task; use selective searching for deeper project files.
- Run `python scripts/context_status.py --check` (if Python/Git are available), then inspect actual Git state.
- Lock one task/branch to one writing agent. Explain intended diff and command to validate before editing.

## Before fallback
- Do not assume exhaustion from error symptoms; inspect provider quota/auth/status where possible.
- Ask active agent to follow `prompts/end-session.md` and update state and handoff.
- Preserve commit/branch/working tree, create explicit checkpoint when safe; do not auto-push.
- Start next eligible provider with `prompts/takeover.md` and the on-disk files.
- Verify actual files and test outputs, not just outgoing agent narrative.

## Day-end
- Ensure task board corresponds to verified deliverables.
- Archive material changes in Git and/or dated handoff records; keep sensitive telemetry out of Git.
- Record unresolved decisions and negative experiment attempts, not only successful outcomes.

## Context hygiene
- The root `AGENTS.md` should remain relatively short. Store details in context files and skills.
- Keep tool outputs/logs in ignored scratch files and retrieve only relevant lines on demand.
- Avoid copying entire previous chat sessions into a new agent's prompt.
- Update state at meaningful transitions, not after every trivial conversational message.
