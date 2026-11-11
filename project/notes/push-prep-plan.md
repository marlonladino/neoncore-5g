# Push preparation plan (draft, lead, 2026-11-11, main at dbc42e8)

Not a stage. Nothing here is approved. Pushing needs the owner's approval each time. Findings are the security reviewer's returned text (read-only inventory, condensed; GitHub-side state, untracked/ignored files and the approvals folder not scanned).

## Findings
- **At HEAD, owner first name:** DEVLOG.md:41 (Windows path), DEVLOG.md:123 (old WSL hostname), wireshark-hosts:33 (hostname + old WSL IP), project/plans/W0.md:22 (login). Quoted copies of DEVLOG:41 in 5 `allowlist-hits.txt` files under project/reports/L0/eval/ (31 lines; the 862 KB `close/wsl-final` one is the largest).
- **Control-machine hostname:** project/plans/W0.md:9 (also Proxmox LAN IP:port). LAN IP also in project/reports/W0/close.md:45. D18 allows the IP; it does not cover hostname or name.
- **Not found:** webmail, surname, employer names, real tokens/keys, env/tfstate/tfvars/kubeconfig in history. IMSIs are all test 99970. Only pcap: traces/rogue-ue-reject.pcap (test PLMN, pod IPs).
- **Already public (origin 2dca43c):** first name (README:306 then, DEVLOG, wireshark-hosts), old WSL IP, webmail author on 3 commits. Grafana admin password is hardcoded in phase3/manifests/06-grafana.yaml:18 with anonymous access on, documented in README:270-275 (public since 2dca43c).
- **Identities in unpushed 135:** 123 local machine identity, 2 "Your Name" (02b264d, 0f24789), 10 owner noreply.
- **Other:** no LICENSE; .gitignore lacks *.tfstate*, .terraform/, terraform.tfvars, *.tfplan; tui-demo.gif tracked twice (~6 MB); site footer "Local preview only"; D11 open (topics list rag/mcp/llm/ai-agents/nwdaf, not built); STATUS says "no git user set" (stale); approvals folder is tracked in git, owner's check.
- git-filter-repo not installed; git-filter-branch is. Not installed by anyone.

## Options for history (owner decides)
- **(a)** Rewrite unpushed range only (mailmap + text replace). Fast-forward push; 3 published commits unchanged; all cited SHAs in STATUS/close/reports go stale; needs tool install + approval.
- **(b)** Scrub tree, then one fresh commit (or one per stage) on top of origin/main, noreply identity. Cheapest, safest; keep local repo as the audit archive; history on origin untouched.
- **(c)** Rewrite and force-push origin/main. Only way to remove webmail/name from the 3 published commits; GitHub caches/forks may still serve them. Needs approval for rewrite and force-push.
- Reviewer's view: (b), or (a) if the audit trail matters; (c) only if the owner wants the webmail/name gone from the public commits.

## Proposed steps (after owner picks)
1. Owner decisions: history option; Grafana password (change + rewrite README, or accept as lab default); LICENSE choice; topics for D11; webmail/first name on origin (accept as public or (c)); employer outside-work policy (owner only).
2. Plan approval for a W0-style amendment is NOT needed for tree edits outside the gate, but the lead has no product write scope: developer/docs-writer/lab-ops do the edits on a branch `push-prep`, small commits.
3. Tree scrub: W0.md:9,22; DEVLOG:41,123; wireshark-hosts:33; regenerate or mask the 5 allowlist-hits files (E6(a) evidence stays valid only if the PASS counts are re-checked, not claimed from the masked copies); dedupe GIF; .gitignore additions; LICENSE; footer/site decision; STATUS stale line.
4. Security-reviewer re-scan of the final tree and of the exact push payload (`git diff origin/main..<candidate>`), including the approvals folder via the owner.
5. Owner reviews the diff and runs the push themself (or approves it explicitly). Then D11 metadata.
6. S-I3 fix (signed approvals, separate OS user) remains a gate before any Stage 7 plan approval, independent of the push.

## Owner decision (2026-11-11)
History option **(b)**: scrub the tree, then one fresh commit (or one per stage) on top of origin/main with the noreply identity; local repo stays as the audit archive; the 3 published commits are not rewritten. Open owner calls: Grafana password, LICENSE, D11 topics, one commit vs one per stage, employer outside-work policy. No tree edits started; they wait for the owner's go on this plan.

## Status 2026-11-11 (push-prep at 49feec7 plus this commit)
- Owner ran the scrub script; 4 commits (395e443, ea74126, 2b998e2, 49feec7). The script itself held the WSL IP and control hostname as literals (reviewer finding), so it is removed from the tree in the next commit; it stays in local history only, which is not published under option (b).
- Reviewer re-scan: tree otherwise clean for first name, Windows user, WSL hostname, login, webmail, FQDN. Employer not tested (reviewer does not know it).
- W0.md edit: its hash now differs from the W0 plan approval (dcb8c6f1…). Nothing enforces W0's hash after W0 closed; audit trail only. The published W0.md will not match the recorded approval hash.
- Open before push: approvals files (3 tracked contain the login; owner), Grafana password (accepted as lab default), commit shape (single commit vs W0'+L0 with a hand-scrubbed W0 tree), employer policy (owner).

## Owner decision 2026-11-11: approval files
The owner accepts that the first name in line 1 of the three tracked approval files becomes public (already public via the 3 origin/main commit authors). Reviewer verdict on `publish` 5afdd4b: clean except this item, so push-ready on that basis. Still the owner's: employer outside-work policy, running the push. Not part of the payload: this note, STATUS edits after 9574a5c.
