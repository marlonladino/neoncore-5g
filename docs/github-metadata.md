# GitHub repository metadata (checklist)

The owner applies everything below by hand. Agents apply nothing to GitHub.

## 1. Description (max 350 characters)

```
5G SA testbed: Open5GS core + UERANSIM gNB/UE on single-node K3s, with Prometheus/Grafana and packet tracing. Planned, not built: fault injection, LLM troubleshooter, RAG over 3GPP specs, MCP agent, NWDAF-lite. Built with AI agents under the owner's direction.
```

Character count is checked with `wc -m` before commit (see the commit message).

## 2. Topics (16 of max 20, lowercase, hyphenated)

5g, 5g-core, open5gs, ueransim, kubernetes, k3s, proxmox, prometheus, grafana, telecom, fault-injection, rag, mcp, llm, ai-agents, nwdaf

Note: rag, mcp, llm, ai-agents, nwdaf and fault-injection describe planned work; the description says so.

## 3. Website

Leave empty.

## 4. Commands (owner runs these)

Run `gh auth login` first.

```
gh repo edit --description "5G SA testbed: Open5GS core + UERANSIM gNB/UE on single-node K3s, with Prometheus/Grafana and packet tracing. Planned, not built: fault injection, LLM troubleshooter, RAG over 3GPP specs, MCP agent, NWDAF-lite. Built with AI agents under the owner's direction."
```

```
gh repo edit \
  --add-topic 5g --add-topic 5g-core --add-topic open5gs --add-topic ueransim \
  --add-topic kubernetes --add-topic k3s --add-topic proxmox \
  --add-topic prometheus --add-topic grafana --add-topic telecom \
  --add-topic fault-injection --add-topic rag --add-topic mcp \
  --add-topic llm --add-topic ai-agents --add-topic nwdaf
```

## 5. Check by hand in the GitHub UI

- Default branch is `main`.
- Issues: on or off, owner's choice (suggest on). Discussions: suggest off for now.
- License: after the push, the repo page should detect MIT.
- Social preview image: optional.
- No secrets in the repo, Actions secrets or variables that are not needed.
