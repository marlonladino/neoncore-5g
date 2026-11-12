"""Owner-run: apply the Stage 9 / 9B edits to project/WORKFLOW.md (2026-11-12 decision).

Usage from the repo root:  python3 project/notes/workflow-stage9-edit.py
Optional second argument writes to another path instead (used for a dry run).
"""
import sys

src = "project/WORKFLOW.md"
dst = sys.argv[1] if len(sys.argv) > 1 else src
s = open(src).read()
rep = [
    ("| 9 | `phase9/` | Telco-RAG over TS 23.501, 23.502, 24.501, 38.413, chunked by clause; hybrid search, reranker, clause citations; eval on GSMA Open-Telco subset + 50 owner questions (wk 13-16) | Right clause returned; scores in README |",
     "| 9 | `phase9/` | Self-built Telco-RAG over 3GPP TS 23.501, 23.502, 24.501, 38.413 (start set), chunked by clause; hybrid search, reranker, clause citations; embeddings and generation from an open-weight LLM served locally on the owner's Mac mini (M4 Pro) on the LAN; eval on GSMA Open-Telco subset + 50 owner questions (wk 13-16) | Right clause returned; scores in README; model server reachable only from the lab (security review) |"),
    ("| 9B | `phase9/` | Port Telco-RAG to Bedrock Knowledge Bases and compare (roadmap wk 23-24, run after Stage 10 closes) | Decision record: managed vs self-built RAG |",
     "| 9B | `phase9/` | Same RAG pipeline with the Claude API as answer model vs the local model on the Stage 9 eval set: quality, clause accuracy, latency, cost per 1,000 queries (roadmap wk 23-24, run after Stage 10 closes) | Decision record: local vs API RAG |"),
    ("Product LLM calls use the Claude API or Bedrock, with the model ID in configuration.",
     "Product LLM calls use the Claude API, except Stage 9, which uses a local open-weight model on the owner's Mac; the model ID and endpoint are in configuration."),
    (", aws-core (9B).", "."),
]
for a, b in rep:
    if s.count(a) != 1:
        sys.exit("stopped, text not found exactly once: " + a[:70])
    s = s.replace(a, b)
open(dst, "w").write(s)
print(f"4 edits written to {dst}")
