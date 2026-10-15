# ADR-0003: LLM and embeddings behind swappable ports, configured by environment

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** IntelTPS team

## Context and Problem Statement
The default model is not chosen yet (PRD §13 evaluation), the runtime is native Ollama on Windows today and possibly a VM or a hosted API (synthetic data only) later. Extraction code must not care which.

## Decision Drivers
- FR-57: model, endpoint and provider are configuration
- Testability: CI cannot run a real LLM
- Portability rules (PRD §21): a single `LLM_BASE_URL`
- Privacy: hosted provider must be a deliberate, visible switch

## Considered Options
1. **Thin ports in `kernel` (`LLMPort`, `EmbeddingPort`) with small adapters; config by env**
2. LangChain / LlamaIndex abstractions throughout
3. Call the Ollama client directly from extraction code

## Decision Outcome
Chosen option: **Option 1**.
- `LLMPort.generate_structured(system, user, json_schema, options) -> StructuredResult(raw_json, prompt_tokens, completion_tokens, done_reason, latency_ms, model)` and (stretch) `stream_text(...)`.
- Adapters: `OllamaAdapter` (native `/api/chat` with `format=<JSON schema>`, explicit `num_ctx`, `temperature`, `num_predict`, timeout) and `OpenAICompatibleAdapter` (for a hosted API or vLLM). `FakeLLM` for tests replays recorded fixtures.
- Config: `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_NUM_CTX` (>= 4096), `LLM_TIMEOUT_S`, `LLM_ALLOW_HOSTED` (default `false`; the hosted adapter refuses to start unless it is `true`).
- `EmbeddingPort.embed_documents(texts)` / `embed_query(text)` (the query adds the bge instruction prefix). Default adapter: FastEmbed (ONNX, CPU, `BAAI/bge-small-en-v1.5`, 384-d), so no PyTorch in the image.
- Every extraction result stores `model`, `prompt_version` and `schema_version` for evaluation and audit.

### Consequences
- Positive: model comparison (PRD §13) is a config change; CI is deterministic with `FakeLLM`; moving to a VM changes one URL.
- Negative / Tradeoff: we write ~150 lines of adapter code that frameworks would give us, and we only get the lowest common denominator of features (no provider-specific tools). Prompts are tuned per model anyway, so "swappable" does not mean "same accuracy".
- Follow-ups: day 1, verify a container can reach host Ollama (`host.docker.internal`). Ollama may need `OLLAMA_HOST=0.0.0.0`; if so, block port 11434 from the LAN with Windows Firewall.

## Pros and Cons of the Options

### Option 1
- Good: small, explicit, testable, honours the Dependency Rule.
- Bad: we own the adapter code.

### Option 2
- Good: many integrations.
- Bad: large dependency surface and version churn in 32 days; hides prompts and retries, which hurts the evaluation story.

### Option 3
- Good: fastest first demo.
- Bad: violates FR-57; untestable without a model.

## Links / References
- PRD FR-56, FR-57, §21 portability; Cockburn, Hexagonal Architecture; Ollama structured outputs docs
