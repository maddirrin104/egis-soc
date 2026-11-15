# W8 synthetic adapter and pinned-model boundary card

## W8 offline draft adapter

- **Identity:** `deterministic-synthetic-draft` bound to the authored W8 fixture hash.
- **Use:** Feed a fixed, cited synthetic draft into W5 atomization/S1/S2/S3 for integration tests.
- **Execution:** Deterministic fixture lookup. No LLM call, token generation, training or model weight.
- **Evidence boundary:** W1-validated synthetic incident and incident-scoped W3 retrieval only. Draft text is not gold.
- **Limit:** A successful W8 test says nothing about actual generation accuracy or generalization.

## W8 offline NLI adapter

- **Identity:** fixed-logit synthetic backend; it returns `(0.0, 5.0, 0.0)` and `truncated=false` for each test pair.
- **Use:** Exercise unchanged W4 V3 rule/NLI fusion, negative routing and W5 repair re-verification.
- **Execution:** No pretrained checkpoint is loaded. The `model_id` and `model_revision` fields retained by the W5 V2 contract are **contract identifiers**, not evidence of execution. The W8 report separately records `FIXED_LOGITS_NOT_MODEL_INFERENCE`.
- **Limit:** The positive case is a source-exact rule/citation integration check. It is not an empirical NLI Supported Precision result.

## Pinned NLI checkpoint for separately authorized work

- **Configured adapter identity:** `cross-encoder/nli-distilroberta-base`, revision `b14d131f9d32668a5e6a982729b57ff6ed5dfcbd`, declared Apache-2.0 in the existing adapter source. The adapter verifies its label order on load.
- **Status in W8-01:** NOT RUN. No model download or replacement occurred.
- **Required before a real inference smoke:** confirm local exact revision availability, source/use rights, same evidence and checkpoint for V2/V3, pinned inputs and output manifest. Any real RQ claim still needs independent gold, D-032 and W7 locks.

## Local generation checkpoint for separately authorized work

- **Existing W5 binding:** the local Ollama generator records the exact model tag and full digest, prompt version, seed, decoding and evidence order. A historical W5 synthetic run used a pinned local Qwen tag; this W8 demo does not call it.
- **Status in W8-01:** NOT RUN. No automatic large-model download or new generation result.

These cards describe implemented interfaces and limits. They do not claim model performance, annotation quality, real SOC usefulness, CFR/UCR/CSA or RQ1–RQ3 outcomes.
