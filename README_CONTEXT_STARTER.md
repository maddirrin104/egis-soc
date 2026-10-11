# EGIS-SOC Context Engineering — Starter Kit

**This package is a recommended operational setup, not a completed or deployed implementation.** It is built around EGIS-SOC research plan v1.0 dated 2026-10-09. It does not install the upstream skill repository automatically.

## Apply to your VS Code workspace (Windows PowerShell)

1. Back up or commit your existing EGIS-SOC files first. Inspect overlaps with `AGENTS.md`, `.github/`, `.agents/` and `docs/context/`; MERGE instead of indiscriminate overwrite.
2. Extract the contents of this ZIP to the root of your EGIS-SOC repository (not one directory above it). Preserve its folder structure.
3. Put/keep your research plan at `docs/EGIS_SOC_Ke_hoach_8_tuan.md`.
4. Review `AGENTS.md` and `docs/context/AGENT_POLICY.md`. Add `gitignore.additions.txt` contents to your existing `.gitignore`, with care not to hide allowed sanitized datasets unintentionally.
5. In PowerShell from repo root: `powershell -ExecutionPolicy Bypass -File .\scripts\install-context-skills.ps1` (only if you trust/review the script and the upstream repo). It clones the context engineering project, copies eight selected skill directory bundles and records upstream commit. The script does not execute upstream scripts, and preserves the upstream MIT LICENSE alongside the copied skills.
6. Validate: `python .\scripts\context_status.py --check`; examine `git status --short` and `git diff --check`.
7. In Codex, paste `prompts/start-session.md`; for fallbacks paste `prompts/takeover.md`; for closing a session paste `prompts/end-session.md`. Local LLM review: `prompts/local-review-only.md`.
8. In VS Code, verify each agent genuinely sees the custom instructions/skills; installation/discovery depends on active agent harness and extension versions.

## Why one root AGENTS.md?

Codex, Antigravity and supported VS Code Copilot harnesses recognize shared project instructions in `AGENTS.md`. A short `.github/copilot-instructions.md` supplements this for Copilot. We intentionally do NOT duplicate a full `GEMINI.md` because Antigravity may load both cumulatively, wasting tokens and risking conflicting instructions.

## Skills

From the third-party library: `filesystem-context`, `memory-systems`, `context-compression`, `context-optimization`, `multi-agent-patterns`, `harness-engineering`, `evaluation`, `project-development`. EGIS-specific skills shipped locally: `egis-handoff`, `egis-experiment-guard`. Install each skill as a FOLDER that retains its `SKILL.md` and references/scripts; do not flatten into single markdown files.

## Memory tiers

- Static instructions: root `AGENTS.md` (always-on, small).
- Durable semantic/decision memory: `PROJECT_BRIEF.md` and `DECISION_LOG.md`.
- Fast-changing operational state: `CURRENT_STATE.md`, `TASK_BOARD.md`, `HANDOFF.md`.
- Episodic archive: `docs/context/handoffs/` and Git commit history.
- Task-specific skill docs: `.agents/skills/<name>/SKILL.md` loaded when needed.
- Raw logs, model artifacts, large outputs: outside conversational context and outside public version control.

## Security and factual integrity

File instructions alone are NOT technical access controls. Configure local models in Ask/Chat read-only mode, disable terminal/edit tools, avoid auto-approvals, and consider isolated read-only checkouts for review. Human approval remains required for research protocol changes, merging, sensitive SIEM connectivity and publishing.

You may adapt directory names, but keep all linked paths consistent and verify instruction discovery in every agent provider.
