# Model routing and permissions

## Sequential fallback (NOT automatic orchestration)

1. **Codex** — primary owner for implementation, architecture, experiments and integrating tests.
2. **Antigravity** — use only when Codex is unavailable/exhausted and an up-to-date handoff exists; may implement the current narrowly scoped task.
3. **GitHub Copilot** — use when Codex and Antigravity are unavailable; may implement scoped changes with checks and handoff.
4. **Local Ollama models** — review-only, explanation, summarizing non-sensitive documentation, and small code suggestions in chat; no direct repository writes, terminal execution, autonomous test changes, or human-free approvals.

At a fallback boundary: write handoff → snapshot Git status → save task branch/checkpoint if safe and authorized → start the next agent → validate working tree and handoff → continue ONLY the selected task. A new agent does not inherit the old chat or quotas. Restart with a new conversation/session if needed, explicitly attaching handoff/context files.

**Important**: `AGENTS.md` can steer agent behavior but cannot enforce permissions. For local LLM sessions use chat/ask mode without edit/terminal tools, or genuinely read-only mounts/ACLs where feasible. Never grant broad autonomous tool approval just to make fallback convenient.

## Ownership
- One writer per branch/task; if multiple IDE sessions are open, only one receives edit access.
- Read-only reviews may run concurrently on a specific commit or diff.
- The human operator authorizes protocol modifications, merges, remote pushes/publication, connecting to production/live SIEM and any destructive command.
- Agent output is a proposal until supported by repository diff and validation.

## No silent escalation
- If local model identifies a bug, produce a file:line finding with proposed patch text only. A coding agent/human decides whether to apply.
- If an agent cannot execute a test, mark NOT RUN and explain exactly why.
