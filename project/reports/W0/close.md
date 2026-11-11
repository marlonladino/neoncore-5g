# W0 close report: agent workflow, approval gate, plugins

Branch `stage/W0`, build commit `636afc7` (not pushed). Plan `project/plans/W0.md`, approved by the owner 2026-11-09T22:34:29Z, SHA-256 `dcb8c6f1f8bd08d3c45c86b878aadc1bfb2dd9a586c88b07c18ae338e15f010f` (matches the file at close).

## Exit criteria and evidence

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Write to `phase7/x.py` blocked without approval | Pass | `test_01` (fixture); **live hook**: lead Write → `GATE BLOCKED [lead] phase7/x.py is outside lead's write scope`; `echo x > phase7/y.py` also blocked; `phase7/` does not exist afterwards |
| 2 | …passes after a valid approval, blocked again after the plan is edited | Pass (fixture only) | `test_02`: developer, STAGE 7 fixture with a simulated approval file. Not exercised live, since no real stage-7 approval exists |
| 3 | Approval script refuses without a TTY | Owner-reported, not observed by the lead | Owner ran it with `</dev/null` in their own terminal and reported "both ran". The terminal panel had no shell, so the lead could not read the refusal text. The real W0 plan approval file exists and its hash matches |
| 4 | evaluator cannot edit `phase7/` | Pass (fixture) | `test_03` |
| 5 | developer cannot edit `evals/` or read `datasets/holdout/` | Pass (fixture) | `test_04`, `test_05` (Read, Grep, Glob and `cat` all blocked) |
| 6 | Only lab-ops (with an approved plan) runs `terraform apply` | Pass (fixture) | `test_06`: blocked for lead, developer and unapproved lab-ops; allowed for approved lab-ops |
| 7 | Secrets file unreadable | Pass (live) | `cat` blocked by the hook; Read tool blocked by the `Read(/.env.lab)` deny rule |
| 8 | Gate files self-protected | Pass (live) | Edit of `.claude/hooks/gate.py` refused by the permission deny rule; file unchanged |
| 9 | Every agent appears in `/agents` | **Not tested** | That dialog doesn't run in the desktop app. Frontmatter for all 8 agents is linted by `test_agents_frontmatter`. Owner to confirm in a terminal `claude` |
| 10 | Every plugin shows its expected state | Pass, with 2 missing | `plugin_list.txt`: 7 enabled and 5 disabled, as planned |

Unit tests: `python3 -m unittest scripts.tests.test_gate -v` ran 19 tests and all passed (2.041 s). Full output is in `project/reports/W0/test_gate.txt`. The tests cover Bash write targets, heredocs, `..`/symlink escapes, fail-closed cases (missing STAGE, bad JSON), unknown agents being read-only, kubectl rules, destructive commands being left to the owner, the lead having no product scope after W0, and skills being non-model-invocable.

## Plugins (`anthropic-plugin-directory`, project scope)
- **Enabled:** commit-commands, security-guidance, pyright-lsp, context7, claude-md-management, session-report, terraform.
- **Disabled:** frontend-design, playwright, grafana-mcp, huggingface-skills, aws-core.
- **Not in the directory, not substituted:** `code-review` (the directory offered `code-review-anthropics` and `code-review-16urls`, neither installed; the built-in `/code-review` covers it) and `mlflow`.
- **Known not working yet:**
  - pyright-lsp needs `pyright-langserver`.
  - terraform's MCP server needs Docker.
  - grafana-mcp has 2 unset required options (it's disabled).
- **Data flow:**
  - context7 sends lookups to the hosted `mcp.context7.com`.
  - security-guidance runs an LLM diff review on Stop.
- MCP server health (`/mcp`): **not tested**, because the dialog isn't available in the app.

## Spend
API $0, GPU $0, cloud $0. No product LLM calls were made. The session's own Claude Code usage is outside `budget.yaml`.

## Lab changes
None. Proxmox was only queried with a single unauthenticated HTTPS GET to read the certificate, at planning time.

## Known limits
- The hook parses Bash text. It catches mistakes, not a determined adversary. Aliases, `eval`, encoded commands and subprocesses (for example the TUI's own `kubectl`) are invisible to it (`docs/agent-gate.md`).
- Any command that mentions the approvals folder, the approval script or the secrets file is blocked outright, even in commit messages or greps. The lead therefore can't commit the approval files: **the owner commits `project/approvals/` themself**. That folder is uncommitted right now.
- After W0, gate changes need the owner to edit `.claude/settings.json` and `.claude/hooks/` by hand. The deny rules stop agents from doing it.
- `project/plans/W0.md` contains the Proxmox LAN address `192.168.1.250` from the brief. It is a private address, but the security-reviewer scrub before any push should decide whether to keep it.
- Unpinned tracer image `nicolaka/netshoot:latest`: carried to L0.
- Hard-coded `REPO_ROOT=~/neoncore-5g` in `phase5/neoncore_cli/k8s.py:15` and `phase6/kubectl_util.py:14`: carried to L0.

## Questions for the owner
1. Do all 8 agents appear in `/agents` in a terminal `claude` session?
2. Will you commit `project/approvals/` (the W0 plan hash now, the close hash after approval) on `stage/W0` before the merge?
3. Merge strategy: is a local `git merge --no-ff stage/W0` into `main`, with no push, still what you want?
4. Will you install the prerequisites (`gh`, `nodejs`/`npm`, `pyright`, Docker, `tshark`, `ansible`, Terraform from HashiCorp's apt repo) before the L0 build? Terraform and Ansible are needed in L0.
5. Should the Proxmox LAN address stay in the committed W0 plan, or be redacted at the pre-push scrub? Redacting it would void that plan's approval hash; it's a closed stage, so the approval record remains in git history.
6. For the L0 plan, have ready (no secrets in chat): the VMID range, pool name, storage target, the K3s VM's static IP/CIDR, gateway and DNS, and VM sizing limits you accept.
7. Does `mlflow` (missing from the directory) get dropped, or reconsidered at the Stage 10 plan with another source you approve?
