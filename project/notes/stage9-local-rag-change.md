# Owner change request: Stage 9 local RAG, Stage 9B local vs API (2026-11-12)

Owner decisions in chat on 2026-11-12:
- Stage 9: self-built RAG over the 3GPP documentation, with an open-weight LLM run locally.
- Local model scope: RAG only. Stages 8 and 10 keep the Claude API.
- 9B: no longer Bedrock. It becomes a local vs API comparison of the same RAG pipeline.
- Hardware: the owner's Mac mini with Apple M4 Pro, on the LAN. Memory size, OS version and serving tool were not stated, and nothing is checked yet.

## Proposed `project/WORKFLOW.md` edits (owner applies; W0 file, outside agent scope)

Row 9, Build column:
> Self-built Telco-RAG over 3GPP TS 23.501, 23.502, 24.501, 38.413 (start set), chunked by clause; hybrid search, reranker, clause citations; embeddings and generation from an open-weight LLM served locally on the owner's Mac mini (M4 Pro) on the LAN; eval on GSMA Open-Telco subset + 50 owner questions

Row 9, Exit criteria: append
> ; model server reachable only from the lab (security review)

Row 9B, Build and Exit:
> Same RAG pipeline with the Claude API as answer model vs the local model on the Stage 9 eval set: quality, clause accuracy, latency, cost per 1,000 queries (run after Stage 10 closes) | Decision record: local vs API RAG

Line 20, replace "Product LLM calls use the Claude API or Bedrock, with the model ID in configuration." with:
> Product LLM calls use the Claude API, except Stage 9, which uses a local open-weight model on the owner's Mac; the model ID and endpoint are in configuration.

Line 71 (plugins): `aws-core (9B)` is no longer needed; remove it, or keep it disabled.

## Points the Stage 9 plan must resolve
- Mac resources (unified memory) decide the model size and quantization; check, don't guess.
- Serving tool (for example Ollama, llama.cpp or MLX) and an OpenAI-compatible endpoint.
- LAN exposure: L0 closed LAN exposure. The Mac endpoint must be bound or firewalled to the lab VM only, with no open port on the LAN. Security reviewer signs off.
- The Mac is outside Terraform and Ansible, like the control machine. Who installs and runs the server (the owner by hand, or an agent over SSH under an approved plan) must be decided.
- The model license must allow this use. Record the model name, version and license in the plan.
- `project/budget.yaml`: local inference costs $0 API. 9B uses the API, so keep its spend under the cap.
- Stage 12 still compares an open model on a rented GPU against the API for the agent. It overlaps 9B for RAG only; leave it as is or narrow it at the Stage 12 plan.
