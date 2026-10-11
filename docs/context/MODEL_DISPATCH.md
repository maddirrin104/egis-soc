# Local model dispatch (qualitative suggestions, not measured rankings)

All Ollama models listed here run only as read-only assistants, consistent with the owner's policy. Capability depends on quantization, prompt format, tools, and local benchmarks. No claimed measured performance.

| Ollama model (user-provided identifier) | Suggested read-only task |
|---|---|
| `qwen2.5-coder:14b` | Review small Python diffs, detect possible test gaps; suggest snippets in chat |
| `gpt-oss:20b` | Explain architecture and critique clearly scoped decisions |
| `deepseek-r1:14b` | Review reasoning assumptions, discuss research risks or error analysis |
| `gemma4:12b` | Explain docs and summarize a narrow technical section |
| `qwen3.5:9b` | Summarize a handoff, classify small non-sensitive tasks, produce checklists |

Never paste private SOC logs or credentials into model chats without verifying storage/network/retention settings. When local inference is unavailable, continue with manual review; do not bypass read-only policy.
