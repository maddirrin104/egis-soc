# EGIS-SOC / GitHub Copilot

Follow the repository root `AGENTS.md` as the canonical project contract. At each new session, inspect `docs/context/INDEX.md`, `CURRENT_STATE.md` and `HANDOFF.md`. Validate Git state before editing. Follow `docs/context/AGENT_POLICY.md` for the fallback hierarchy; Copilot may implement scoped tasks when Codex and Antigravity are unavailable. Keep research protocol, test/OOD datasets and frozen metrics protected. End each task with tests, explicit NOT RUN status where needed, and a verified handoff. Do not infer that a previous agent's chat history is accessible.
