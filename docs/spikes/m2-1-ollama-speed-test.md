# M2-1 spike: Ollama speed test (15 Oct 2026)

Script: `spikes/ollama_speed_test.py` (stdlib only; `--models ... --runs N [--slim]`).
Machine: Intel i7-8565U (4 cores), 15.9 GB RAM, NVIDIA GTX 1650 Max-Q (4 GB VRAM, shared with the Windows display), Ollama 0.40.4 running natively.
Test input: one synthetic tender section (about 830 prompt tokens, 8 known requirements, no real data), requirement extraction with a JSON schema, `temperature 0`, `num_ctx 4096`, `think: false` for Qwen3. 2 runs per model.

## Results

| Model | Size / GPU share | Generation | Prompt processing | Latency per section | Valid JSON | Recall (8 known) | Quotes found verbatim | 100-page pack (37 sections) |
|---|---|---|---|---|---|---|---|---|
| qwen3:4b | 3.5 GB / 66% GPU | 15-17 tok/s | ~150 tok/s | 90-155 s | 2/2 | **88%** | 97% (35/36) | **~70-75 min** |
| llama3.2:3b | 2.9 GB / 80% GPU | 30 tok/s | ~205 tok/s | 40-43 s | 2/2 | 38% | 100% | ~26 min |
| qwen2.5:1.5b | 1.2 GB / 100% GPU | 74 tok/s | ~400 tok/s | 30-32 s | 2/2 | 50% | 87% (40/46) | ~19 min |

Slimmer schema (no free-text `description`): qwen3:4b 105-124 s per section, recall 88%, about 70 min per pack, so only a small gain. qwen2.5:1.5b ran to the output cap and produced invalid JSON in both runs, so it is not reliable with that schema.

## Findings

1. **Generation speed, not prompt size, drives time.** A section produces 1,000-1,900 output tokens (one JSON object per requirement). At 15 tok/s that is 80-120 s. Prompt processing is a few seconds.
2. **The 45-minute target (PRD section 6) is not met by Qwen3-4B on this laptop** if every ~830-token section goes through the LLM: roughly 70-75 minutes per 100-page pack. Caveat: this synthetic section is unusually dense (almost every sentence is a requirement). Real packs contain more boilerplate, so real output will be shorter and faster, but this is unmeasured.
3. **Only Qwen3-4B has usable quality.** Recall 88% and 97% verified quotes. Llama 3.2 3B and Qwen2.5 1.5B miss most compulsory documents and the compulsory site meeting, so they would silently drop mandatory requirements (the worst failure for this product).
4. **Only 66% of Qwen3-4B fits on the GPU** (about 3.2 GB of the 4 GB is free after the display). Closing other GPU apps may raise this; not tested.
5. **Output is non-deterministic at temperature 0** for Qwen3 (21 vs 15 requirements between runs), so the evaluation script must average several runs.
6. **Structured output works.** Ollama's `format` (JSON schema) produced valid JSON in all runs where output was not truncated. The first llama3.2 attempt failed only because verbose output hit the 1,024-token cap; the cap is now 2,048. `think: false` worked for Qwen3.
7. **Model load times:** 4-23 s when cached, but a cold first load of llama3.2 took 75 s. Preload before demos.

## Container to host Ollama: works

With Docker Desktop on Windows, the `api` container reached the native Ollama through `LLM_BASE_URL=http://host.docker.internal:11434` (returned version 0.40.4) **without** setting `OLLAMA_HOST=0.0.0.0`. The full stack (db, api, worker, web, caddy) started, `/api/v1/health` and `/api/v1/health/db` returned ok through Caddy on port 8080, and the pgvector extension (0.8.7) can be created in the database. Other members on Mac/Linux may still need `OLLAMA_HOST=0.0.0.0` (see README).

## Not tested

- Real-world section density, scanned/low-quality text, BoQ refinement, quotation extraction, larger models, `qwen3:1.7b`, a smaller `num_ctx` to improve GPU fit.
- Only 1 section and 2 runs per model: indicative, not statistical.

## Recommendation (decisions for the group)

1. **Default model for extraction: `qwen3:4b`.** Keep `LLM_MODEL` configurable. Re-run on the larger synthetic set (M1-7) before locking it.
2. **Do not run the LLM on every section.** Add a deterministic pre-filter (sentences or windows containing "must", "shall", "required", "no later than", "compulsory", "disqualif", dates, grading/registration terms) and send only those windows. This cuts both calls and output. Measure recall against the full-section run.
3. **Revise the processing-time target**, either to "100-page pack in under 90 minutes in the background, with requirements appearing section by section", or keep 45 minutes and rely on the pre-filter. Decide after step 2 is measured.
4. **Process demo documents in advance** and use the live demo to show review, not extraction.
5. Keep the small models only for cheap classification tasks, and only after measuring them on that task.
6. Record `qwen3:4b` licence (Apache-2.0, verify at download) in the stack table.
