# L0 security review

## Plan review

Reviewer: security-reviewer. Input: draft `project/plans/L0.md` (unapproved, 392 lines), `project/WORKFLOW.md`, `CLAUDE.md`, `docs/agent-gate.md`, `.claude/hooks/gate.py`, `.claude/settings.json`, `scripts/labenv`, `.gitignore`, and the phase1–4 manifests. `.env.lab` not read. Lab not contacted. Nothing built yet, so every point below is about the design.

**What I ran:** I fed synthetic hook JSON to `.claude/hooks/gate.py`, the same way `scripts/tests/test_gate.py` does. That only classifies the command text and runs nothing. I also ran count-only greps over tracked files and git history for private IPv4 addresses. No values were printed. Everything else is reading.

**Gate results** (rc=0 means allowed). Stage L0, plan **not approved**:

| Actor | Command | rc |
|---|---|---|
| evaluator, docs-writer, lead | `scripts/labenv infra/lab.sh up` | 0 |
| evaluator | `NEONCORE_ALLOW_REPLACE=1 scripts/labenv infra/lab.sh up` | 0 |
| evaluator | `scripts/labenv infra/lab.sh snapshot golden-l0` | 0 |
| blog-writer | `./start.sh` | 0 |
| evaluator | `scripts/labenv printenv` (would print the token) | 0 |
| evaluator | `scripts/labenv sh -c "curl -s -X POST \"$PVE_ENDPOINT/...\""` (a Proxmox write: the `:8006` regex never sees the port) | 0 |

The gate also blocked my own test command because its text contained `terraform` followed later by `destroy`. That is the intended behavior.

---

### BLOCKING

**S-B1. Gate blind spot: nothing restricts `lab.sh`, `labenv`, `start.sh` or `stop.sh` by actor or by approval.**
Section 9 says "Only lab-ops runs `lab.sh`, and only with this plan approved." The gate doesn't enforce either half (results above). No LAB pattern matches `infra/lab.sh`, `scripts/labenv` or `start.sh`/`stop.sh`. In L0, start.sh and stop.sh become VM power operations through the API. The `ask` rule `Bash(terraform apply *)` never fires either, because the planned call is `scripts/labenv … terraform -chdir=… apply` inside `lab.sh`.
*Fix to put in the plan:*
1. `lab.sh` checks approval itself. Before any mutating subcommand (`up`, `deploy`, `start`, `stop`, `snapshot`), and inside `start.sh`/`stop.sh`, it computes `sha256(project/plans/$(cat project/STAGE).md)` and compares it with the recorded approval hash. On a mismatch or a missing file it refuses with a non-zero exit. `status` and `verify` stay read-only and need no approval. Add `infra/tests` cases for both outcomes.
2. Add an owner task to T0: extend the gate's `LAB` list so these are lab-ops-only and need approval:
   - `infra/lab.sh (up|deploy|start|stop|snapshot)`
   - `(^|[\s;&|(/])(start|stop)\.sh\b`
   - `scripts/labenv` followed by anything other than `infra/lib/pve_get.sh` or `infra/lab.sh (status|verify)`.

   Changing the gate is owner-only. If the owner declines, section 9 must say plainly that any agent can run `lab.sh` and that check 1 is the only control.
3. Delete the claim that `docs/agent-gate.md` "already states this limit" for `lab.sh`, or have docs-writer add a `lab.sh`/`labenv` line to the Limits section in T11.

**S-B2. The replace override `NEONCORE_ALLOW_REPLACE=1` can be set by any agent.**
An agent can prefix it to the command (gate result above), or it can sit in `.env.lab`, which `labenv` loads for every run. So it is not "owner-only". There is a second gap: the plan doesn't say that the applied plan is the one that was guarded.
*Fix to put in the plan:*
- Remove the environment variable. A replace or delete goes ahead only after an interactive confirmation: `lab.sh` lists the affected resource addresses and reads the typed resource address from `/dev/tty`.
- `lab.sh` refuses when there is no TTY or when `CLAUDECODE` is set (the same checks as `approve.sh`). It also refuses if `NEONCORE_ALLOW_REPLACE` is present at all.
- `lab.sh` runs `terraform apply <planfile>` on exactly the saved plan file that passed the guard, never a fresh `apply`. The plan file lives in the state directory (mode 600) and is deleted afterwards.
- The guard fails closed on a JSON parse error, an empty `resource_changes`, an unknown action, or `"delete"` anywhere in `change.actions` (`["delete"]`, `["delete","create"]` and `["create","delete"]`).
- `infra/tests` cover each of those, plus a malformed JSON case and a missing plan file.

**S-B3. TLS pinning falls back to the system CA store, and has a check-then-use gap.**
- **Fallback.** Go's `crypto/x509` on Linux loads `SSL_CERT_FILE` *and then still loads the default `SSL_CERT_DIR` directories* (`/etc/ssl/certs`, `/etc/pki/tls/certs`) unless `SSL_CERT_DIR` is set too. So with only `SSL_CERT_FILE` set, any certificate from a system-trusted CA with a matching SAN is accepted. That includes a locally installed corporate or MITM CA.
- **Missing file.** If `pve-ca.pem` is missing or unreadable, Go silently uses the directories alone.
- **The T2 wrong-cert test doesn't catch either case,** because a self-signed wrong cert is not in the system store.
- **Check-then-use gap.** The check compares the *network* cert. Terraform then trusts whatever the *file* holds at exec time. The file sits in a persistent, user-writable path that is reused across runs.

*Fix to put in the plan:*
1. Every run gets a fresh `mktemp -d` (mode 700) under `~/.local/state/neoncore/`.
2. Write **only the leaf** there, re-hash *that file* against `PVE_TLS_FINGERPRINT` right before each terraform/curl exec, then export `SSL_CERT_FILE=<file>` and `SSL_CERT_DIR=<empty mode-700 dir>`.
3. `insecure = false` is a literal in the provider block. `lab.sh` aborts if `PROXMOX_VE_INSECURE` or any `PROXMOX_VE_SSH_*` variable is set. If the provider asks for SSH to the host, lab-ops stops and reports.
4. Add a T2 negative test: `SSL_CERT_FILE` pointing at a nonexistent file must make Terraform fail to connect. That proves there is no silent fallback.
5. A pin mismatch never offers to re-pin. Abort messages never print the expected or actual fingerprint.
6. The E10 negative path uses a flag that can only cause failure (for example `lab.sh status --selftest-bad-pin`, which flips one hex digit of the expected value). Never use an environment variable that *replaces* the pin, because that would be a pin bypass. Note that `labenv` re-sources `.env.lab` with `set -a`, so a caller's `PVE_TLS_FINGERPRINT=` is overwritten anyway.

**S-B4. The token must stay out of argv, logs and the E10 trace.**
The plan says the token is "never in logs". It doesn't say how curl gets it. `curl -H "Authorization: PVEAPIToken=…"` puts it in argv. There, `ps` and `/proc/*/cmdline` show it to any local process, and any agent can run `ps`. It is also written into the E10 `strace` file.
*Fix to put in the plan:*
- `pve_get.sh` passes the header through stdin (`curl --config -` or `-H @-`), never on the command line.
- `lab.sh` never uses `set -x`. It refuses to run if `TF_LOG` or `TF_LOG_PROVIDER` is set, and it never prints environment variables.
- Ansible runs without `-v` and `--diff`. Every task that touches the kubeconfig or keys has `no_log: true`.
- E10 strace runs with `-o <session scratchpad file>` (never stdout/stderr, never the repo) and without `-v`.
- Before the raw trace is deleted, `tls_negative.sh` counts occurrences of `PVEAPIToken` in it and records only the count, which must be 0. Then E10 proves the argv claim instead of assuming it.
- Do the unauthenticated cert fetch with `openssl s_client`, not curl. Then any `curl` or `terraform` execve after the check is a FAIL. A basename-only trace can't tell authenticated curl from unauthenticated curl.

**S-B5. "Redacted" is not defined, and raw output reaches repo paths.**
`lab-up.log (redacted)`, the `nft list ruleset` output, the Terraform plan output, `pods.json` and `prom-targets.json` all reach repo paths. `pods.json` holds `spec.nodeName` and `status.hostIP`. `prom-targets.json` holds `instance`, which includes the node IP. The WSL2 baseline B has the **WSL2 hostname as the node name, which defaults to the Windows computer name** and may be an employer asset tag. B (D14a) runs inside WSL2, where the `.env.lab` value list doesn't apply.
*Fix to put in the plan:* one redaction filter used by lab-ops and the evaluator for every write under `project/notes/L0.md` and `project/reports/L0/**`:
1. Replace the value of every site variable taken from the environment in-process: the endpoint host, every `TF_VAR_*`, `LAB_ADMIN_CIDR`, the fingerprint, and the VM hostname.
2. Redact by structure: `nodeName`, `hostIP`, `hostname`, the kube context and cluster names, the node's `InternalIP`, and the `instance` labels that carry the node address.
3. Replace any IPv4 address outside the documented lab ranges (pod/service CIDRs, the UE pool, and the addresses already in the phase manifests) with `<ip>`.
4. **Fail closed:** after writing, re-scan the file for each sensitive value and for any non-allowlisted RFC1918 address. On a hit, delete the file and exit non-zero.

Raw output goes only to the state directory or the scratchpad, never into the repo first. `capture_baseline.sh` applies steps 2–4 inside WSL2.

**S-B6. No SSH host key pinning on first contact.**
The plan doesn't say how Ansible trusts a freshly built VM. A from-zero rebuild creates new host keys, and the usual "fix" is `host_key_checking=False`. A LAN impersonator would then hand the control machine its own kubeconfig.
*Fix to put in the plan:*
- `ansible.cfg` sets `host_key_checking = True`, `StrictHostKeyChecking=yes`, and `UserKnownHostsFile=~/.local/state/neoncore/known_hosts` (mode 600).
- Never `StrictHostKeyChecking=no`.
- After cloud-init, `lab.sh` reads `/etc/ssh/ssh_host_ed25519_key.pub` through the pinned, authenticated API (guest agent `file-read`: `VM.GuestAgent.FileRead` on PVE 9, `VM.Monitor` on PVE 8) and writes the known_hosts entry. On a VM rebuild, the entry is replaced only through that path.
- If the guest-agent path doesn't work, it becomes an owner decision: trust on first use with `accept-new` into the dedicated file, with the risk recorded in section 9.

**S-B7. The nftables persistence and auto-revert mechanism is not specified.**
E7 R3 depends on the rules persisting across a reboot. The standard Ubuntu `/etc/nftables.conf` starts with `flush ruleset`. Any `systemctl restart|reload nftables`, for example from an Ansible handler on an idempotent re-run, would wipe the Docker, kube-proxy and flannel tables on a running node. The plan also doesn't say what happens to the persistent config when the 120 s revert fires.
*Fix to put in the plan:*
- The guard lives in its own file holding only `table inet neoncore_guard`, re-created with `destroy table` + define. nft 1.0.9 on 24.04 supports it.
- It is loaded by a dedicated oneshot unit with `Before=network-pre.target docker.service k3s.service`.
- Never `flush ruleset`, and never restart `nftables.service` on a live node.
- The final drop is family-agnostic, so it covers IPv6. Add `ct state invalid drop` and a `counter` on the drop rule.
- **Revert:** arm `systemd-run --on-active=120 nft delete table inet neoncore_guard` before applying. Cancel it only after a *new* SSH connection succeeds. Enable the persistent unit only after that confirmation.
- If the revert fires, the Ansible run fails (non-zero), and `lab.sh verify` fails while the table is absent.
- E7 in R3 records that the table and unit are present after the reboot.

**S-B8. Pushing `main` publishes the Proxmox LAN address that is already in git history.**
Count-only scan: `project/plans/W0.md` (1 hit) and `project/reports/W0/close.md` (1 hit) contain the Proxmox LAN address. Both are committed (`636afc7`, `727c20c`) and merged into `main`. Section 9 and T15c treat this as a working-tree scrub. Editing the files doesn't remove the address from history.
*Fix to put in the plan:* T15c precondition. The pre-push scrub runs over **all history** (`git log -p --all`, checking the redaction value list plus non-allowlisted RFC1918 addresses), not just `HEAD`. Any hit in history goes to the owner as a decision before the first push: accept that this private address becomes public, or rewrite history first (owner-only, destructive, per-action approval). The security-reviewer lists the hits by commit, file and line in this report at close.

**S-B9. The GIF frame check is manual and not reproducible. A GIF stays public permanently once pushed.**
The `p` and `l` keys and the `s` scenario can show the node name, which is the VM hostname. They may also show the node `InternalIP` (the VM's LAN IP) and the control machine's `user@host` prompt.
*Fix to put in the plan:*
- The Terraform VM name and hostname get a neutral, publishable value (for example `neoncore-lab`).
- The VHS tape sets a neutral `PS1` and also writes a `.txt` output.
- Before the commit, the S-B5 filter's scan step runs over that text output and must return 0 hits.
- Then a human looks at the frames.
- No `-o wide` views.

---

### ADVISORY

- **S-A1. Token role.**
  - Use a dedicated `neoncore@pve` user with no password, a privilege-separated token, and a token expiry date.
  - Never grant `Sys.Modify` on `/`. The `download-url` endpoint (D5a) needs `Sys.Modify` on `/` or, on newer 8.x, `Sys.AccessNetwork` on the node. `Sys.Modify` is out of the question. `Sys.AccessNetwork` lets the host fetch arbitrary URLs (SSRF from the host), so it should be an explicit owner decision, otherwise D5(b).
  - `VM.Allocate` on the pool also grants destroy, so "no destroy subcommand" is a convention, not an ACL limit. Section 7's "hard limit" is true only for objects outside the pool; reword it.
  - A2: require **zero** foreign VMs in `/cluster/resources`. Drop "or they must be read-only". Storage content listing through `Datastore.Audit` is accepted and noted.
  - `Datastore.AllocateTemplate` on a shared image storage lets the token delete other ISOs and templates there. Use a dedicated storage or record the risk.
  - On PVE 9, grant only `VM.GuestAgent.Audit` and `FileRead`, not `Unrestricted` or `FileWrite`. On PVE 8, `VM.Monitor` includes guest-exec, which is root in the VM. Say so in section 9.
- **S-A2.** Every `labenv` child gets the write-capable token. That includes the evaluator during E5 and E10. `scripts/labenv printenv` dumps all values into the transcript. Suggested owner gate rule: block `labenv` followed by `env`, `printenv`, `set`, `declare`, `export -p`, `sh -c` or `bash -c`. Optionally, a second read-only token for `pve_get.sh`. Real separation would need an owner change to `labenv`, since it loads the whole file.
- **S-A3. Terraform state.**
  - It holds VM config (IPs, node, VMID, MAC, SSH public key, user name), not the token. The provider reads the token from the environment.
  - Terraform rewrites the state with its default mode, so "mode 600" on the file won't hold. Make the directory 0700 and use `umask 077` in `lab.sh`. That also covers `.tfstate.backup`.
  - Add `*.tfplan`, `*.tfstate*`, `crash.log` and `.terraform.tfstate.lock.info` to `infra/.gitignore`.
- **S-A4. kubeconfig.** Never use `insecure-skip-tls-verify`. Verify that the K3s cert SAN covers the VM IP. Use `fetch` with `no_log`. Back up the WSL-era file (plan already says so).
- **S-A5. sshd.** Ubuntu 24.04 includes `sshd_config.d/*.conf` *before* the main settings, and sshd keeps the first value it sees. A cloud-init `50-cloud-init.conf` setting `PasswordAuthentication yes` beats an edit to `sshd_config`. Use a drop-in `00-neoncore.conf` that also sets `KbdInteractiveAuthentication no`. Record `sshd -T` output as evidence. Use a dedicated lab key, not the owner's personal key, mode 600, outside the repo.
- **S-A6. LAN.**
  - `lab.sh` refuses a `LAB_ADMIN_CIDR` wider than /32 unless the owner confirms.
  - The control machine needs a static IP or DHCP reservation. A lease change locks you out, or hands access to another host.
  - Grafana's anonymous **Admin** on 30030 is an unauthenticated admin API for any process on the control machine, agents included. It can create datasources (SSRF from the cluster) and API keys. Accepted for L0. It must be closed before Stage 10/11 (grafana-mcp).
  - On WSL2, the NodePorts weren't reachable from the LAN. The move raises exposure, and the guard is what brings it back down; say so.
  - The first firewall run happens before `l0-base` exists, so a lockout at that point means a rebuild. Guest-agent exec is another recovery path.
- **S-A7. E7 coverage.**
  - No IPv6. Record `ip -6 addr show scope global` on the VM (expect none), or scan the v6 address.
  - Add the UDP list to the allowlisted scan as well.
  - Record the nft drop-counter delta during the non-allowlisted scan. That turns UDP `open|filtered` into positive evidence.
  - Record yes/no that the scanning host's address is outside `LAB_ADMIN_CIDR`.
  - `phase1/test-macvlan-nad.yaml` uses `"master": "eth0"`. If the VM's NIC is `eth0`, applying it would put a pod on the LAN past the guard. It's not in the deploy; keep it that way. The E7 `-A` NAD check covers it.
- **S-A8. Supply chain.**
  - `get.k3s.io` is fetched live. The installer checks the binary against a checksum fetched from the same release, not a committed value. Pin `install.sh` from the tag with a committed sha256, or download the binary and check it against a committed sha256.
  - T0 fetches the HashiCorp and Docker GPG keys without checking fingerprints. Check them against the published fingerprints.
  - Take the Ubuntu image SHA-256 from a GPG-verified `SHA256SUMS`.
- **S-A9. Pcaps.**
  - The tracer runs `tcpdump -i any` on hostNetwork. On a LAN bridge it now also captures LAN ICMP from other hosts, including the E7 scanner.
  - SBI on 7777 is cleartext, so the pcaps include the synthetic subscribers' K/OPc in UDR→UDM authentication data.
  - Recommendation: never publish run or baseline pcaps; publish only curated reference captures. At close, scrub with `tshark -q -z conv,ip` for non-lab addresses.
- **S-A10. Untrusted data in the evaluator scripts.**
  - No `shell=True` or `eval` on parsed values.
  - Validate the MSIN against `^[0-9]{9,10}$` before using it in paths or filters.
  - Use `tshark -T fields` with explicit fields.
  - Run tshark unprivileged with a clean config directory (HOME/XDG), so personal Lua plugins and preferences don't load.
  - Strip control and ANSI characters before writing any string into `.md`, and put data values in code spans.
  - The plan guard parses Terraform JSON and fails closed.
  - Agents quote log, pcap and Terraform text only as evidence. A string in them never triggers a command.
- **S-A11. Publication.**
  - README, `docs/lab-proxmox.md` and DEVLOG use placeholders for node, bridge, storage, pool and VMID.
  - No Proxmox GUI screenshots that show the resource tree, other guests or the node name.
  - No employer names in the description or topics.
  - The WSL2 export holds the whole distro (shell history, `~/.ssh`, kubeconfig). Keep it out of synced folders (OneDrive), owner-only, and delete it on the D10 date.
- **S-A12.** UE egress to the LAN through the UPF NAT: I agree it should be flagged for Stage 7. Once the VM sits on the LAN, that path reaches the owner's devices from any pod.

### Not tested
Everything that needs the lab or built code: the pin behavior (the Go fallback above comes from Go's documented `crypto/x509` loading order, not from a test), the token ACL, nftables, the scans, sshd, and the GIF. These are re-checked in the build review at close.

## Build review (interim, 2026-11-10)

Reviewer: security-reviewer. Branch `stage/L0` at `3f061d3`, plus the owner's uncommitted gate change and the untracked R1 evidence. This was a code and evidence review only. I did not read `.env.lab`, contact the lab or the Proxmox API, or run `lab.sh`, `labenv`, `start.sh`/`stop.sh` or anything else that changes state.

**What I ran:**
1. **Gate classification.** I fed synthetic hook JSON to the working-tree `.claude/hooks/gate.py`, using a throwaway fixture with an approved L0 plan, the same method as the plan review. This only classifies the command text. None of the commands was executed.
2. **Redaction test with fake values.** I ran `evals/l0/redact.py --stdout` under `env -i` with fake site values, on synthetic input in the session scratchpad. No lab environment was loaded.
3. **Count-only scans.** I scanned the added lines of `main..stage/L0` (47 commits) for:
   - `redact.scan()` categories, with no site values
   - Proxmox default names
   - token and fingerprint shapes
   - UUIDs
   - SSH keys
   - this machine's hostname and login name

   I also ran `redact.py --scan` over `project/notes/L0.md` and all 31 files under `project/reports/L0/` (tracked and untracked). No values were printed.
4. **Permission check.** I ran `stat` on the state directory and `~/.kube` (permissions only, no contents).

### Status of the plan-review blocking points

| Point | Code status | Notes |
|---|---|---|
| S-B1 approval check, D16 gate patterns | Implemented: `approval_check.sh` runs before every mutating path (`lab.sh` up/deploy/start/stop/snapshot, `start.sh`/`stop.sh`, `tf.sh apply`, `ansible.sh`, `hostkey.sh`, `pve_power.sh` start/shutdown, `pve_snapshot.sh`). D16 patterns are present (uncommitted) | **Bypassable**, see S-I1 and S-I3 |
| S-B2 plan guard | Implemented: saved plan file, guard on `terraform show -json`, fails closed, no override variable, `NEONCORE_ALLOW_REPLACE` presence refused, TTY confirm | One fail-open shape case and the TTY spoof, see points 1 and S-I3 |
| S-B3 TLS pin | Pass (code): per-run `mktemp -d` (700), leaf only, re-hash in `pin_verify` before every exec, `SSL_CERT_DIR` set to an empty dir, curl `--pinnedpubkey`, `insecure = false` literal, aborts on `PROXMOX_VE_INSECURE`, `PROXMOX_VE_SSH_*`, `TF_LOG*`, fail-only selftest, no re-pin path, no fingerprint printed. E10 R1 evidence: negative exit 1 with 0 curl/terraform execve; positive exit 0 | Nonexistent-cert-file negative not re-run by me |
| S-B4 token out of argv | Pass: `curl --config -` on stdin everywhere (`pve_get.sh`, `pve_api.sh`, `pve_snapshot.sh`); no `set -x`; E10 `PVEAPIToken` count 0 in trace, stdout and stderr (both runs) | — |
| S-B5 redaction | Implemented, fails closed without site values (`11aafc0`). The `var.`/`local.` exemption is narrow (fullmatch, unquoted, text mode only) and I accept it | **Boundary bug leaks the token secret**, see S-I2 |
| S-B6 host key | Agent path implemented; D17 TOFU used (owner decision) | Point 2 |
| S-B7 nftables guard | Implemented as specified: own file and table, add+delete+define in one transaction, prerouting −150, invalid drop, established accept, admin /32 to {22, 6443, 30030, 30090}, family-agnostic `counter drop`, auto-revert armed before apply and cancelled only after a new SSH connection, unit enabled afterwards, no `flush ruleset`. R1 evidence matches | Reboot persistence not tested; advisories S-I-A4 and S-I-A5 |
| S-B8 history | Pre-push scrub is still due at close | Point 5 |
| S-B9 GIF | Not built yet (T12). VM name `neoncore-lab` is in `main.tf` | Not tested |

### BLOCKING

**S-I1. The D16 gate patterns miss trivial path variants. Any agent can still run `labenv` with arbitrary commands (owner fix in `gate.py`).**
- **Evidence.** These forms are classified as allowed (rc=0) for the evaluator, and for other agents in the same way:
  - `scripts/./labenv printenv`
  - `./scripts//labenv printenv`
  - `cd scripts && ./labenv printenv`
  - `infra/./lab.sh up`
  - `env -u CLAUDECODE script -qec 'scripts/./labenv infra/./lab.sh up' /dev/null`
- **Impact.** The first three print the token. That is exactly what the new test `assertBlocked("scripts/labenv printenv")` is meant to stop. The `cd scripts && ./labenv` form is a plausible accident, not only an adversarial one.
- *Fix (owner, `check_bash`):*
  1. Match LAB patterns against a path-normalized copy, `flat_n = re.sub(r"/(?:\.?/)+", "/", flat)`. This collapses `//` and `/./`.
  2. Anchor on the basename instead of the `scripts/` prefix:
     - `r"(^|[\s;&|(/])lab\.sh\s+(up|deploy|start|stop|snapshot)\b"`
     - `r"(^|[\s;&|(/])labenv\b(?!\s+(infra/lib/pve_get\.sh|infra/lab\.sh\s+(status|verify)|python3\s+-I\s+(-m\s+evals\.l0\.(?!redact\b)[a-z_]+|evals/l0/(?!redact\.py)[a-z_]+\.py)|evals/l0/[a-z_]+\.sh)\b)"`
  3. Add `test_gate.py` cases for the five forms above, plus `../infra/lab.sh up`.

**S-I2. `redact.py` misses a site value that is directly followed by a word character. Through the gate's `evals/l0` allowance, any agent can print the Proxmox token secret.**
- **Evidence.** I used a fake token in `env -i`. `redact.py --stdout --format text` on a NUL-separated environment sample returned rc=0. The output had the token id replaced, but **the secret part was intact**. The post-redaction scan reported 0 hits.
- **Cause.** `strip_control` deletes `\x00`, so each value runs straight into the next variable name. The plain-mode lookahead `(?![\w-])` then fails, and `scan()` uses the same regex. A token value followed by a letter in an ordinary log line (`...uuidxyz`) slips through the same way.
- **Path.** `/proc/self/environ` of a `labenv` child holds the real token. The gate allows `scripts/labenv python3 -I -m evals.l0.redact --stdout <file>` for **every** agent (classified rc=0 for the evaluator and for the docs-writer). I did not run this with the real environment.
- **Point 4, other scripts.** I checked every other `evals/l0` script. None prints the environment or echoes raw input: they use list argv, `-I`, tshark with a clean environment, and every write goes through `redact`. But each of them writes through `redact`, so the same miss applies to any input that contains the token.
- *Fix:*
  1. **evaluator, `redact.py`:**
     - In `strip_control`, map `\x00` (and the other C0 controls) to `\n` instead of deleting them.
     - For the secret class (`PVE_API_TOKEN` and each part, `PROXMOX_VE_API_TOKEN`, every `PVE_TLS_FINGERPRINT` form), substitute and scan as plain substrings with no lookaround.
     - Refuse any input path whose `realpath` starts with `/proc/`, `/sys/` or `/dev/`, and any input that is not a regular file (stdin `-` stays allowed).
     - Add tests: a token followed by a letter, a NUL-joined environ sample, and `/proc/self/environ` refused with exit 2.
  2. **owner, `gate.py`:**
     - Exclude `redact` from the `labenv` allowance (pattern in S-I1).
     - Make the `evals/l0` allowance actor-bound: when `labenv` is followed by an `evals/l0` form, block unless `ctx.actor in ("evaluator", "lab-ops")`, then `ctx.require_approval(...)`. Today the docs-writer and blog-writer pass.
     - Note that this allowance also lets any agent run `capture_baseline.sh capture`, which runs the phase6 suite (subscriber provisioning) out of the gate's sight.

**S-I3. An agent can satisfy every "human at a TTY" check, including the one that protects plan approval itself (owner fix; predates L0).**
- **Evidence.** These checks all rely on `[ -t 0 ] && [ -t 1 ]` with `CLAUDECODE`/`CLAUDE_CODE_ENTRYPOINT` unset, or on reading `/dev/tty`:
  - `approval_check.sh`'s owner exemption
  - `plan_guard.py`'s typed replace/delete confirmation
  - `scripts/approve.sh`

  `env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT script -qec '<cmd>' /dev/null` gives the child a pty and feeds it piped stdin. The repo's own test `test_approval_check.sh` ("owner at a real terminal is exempt") does exactly this from a non-interactive shell and passes.
- **Gate text checks.** The gate's text block on `approve.sh` and the approvals path is evaded by a glob: `scripts/appr*.sh L0` and `ls project/approv*` are both classified rc=0. The `script` wrapper itself is classified rc=0 for lab-ops around `tf.sh apply`.
- **Impact.** An agent could forge an approval, or confirm a VM replace. I did not try either.
- *Fix (owner):*
  1. **Bind approvals to a secret the agent can't use.**
     - `approve.sh` signs `"<stage> <kind> <sha256>"` with `ssh-keygen -Y sign -n neoncore-approval`. The key must be one an agent can't use unattended: a passphrase-protected key that is **not** loaded in the agent's `ssh-agent`, or a FIDO `-sk` key that needs a touch.
     - `gate.py` and `approval_check.sh` verify the signature with `ssh-keygen -Y verify` against a committed `allowed_signers`.
     - The TTY exemption in `approval_check.sh` goes away. The owner signs a short-lived `power` approval instead.
     - `plan_guard.py --confirm` requires the same signature over the plan file's sha256.
  2. **Until then, add gate rules that catch the obvious forms:**
     - `\bscript\b[^\n;&|]*\s-\w*c`, `\bunbuffer\b`, `\bexpect\b`, `pty\.spawn`, `\bsocat\b[^\n;&|]*\bpty\b`
     - `\benv\b[^\n;&|]*-u\s*CLAUDE`, `\bunset\s+CLAUDE`, `CLAUDECODE=`
     - The glob-tolerant `appr[a-z]*[*?\[]` and `approv[a-z]*\b` on the flattened text
  3. **Document it.** Add a line to `docs/agent-gate.md` Limits: the TTY checks stop mistakes, not an agent wrapping in `script(1)`.

### Points the lead asked about

1. **`plan_guard.py` skips the pool check on updates (`919abab`): ADVISORY.**
   - **Why I accept it.** With `ignore_changes = [pool_id]`, Terraform never plans a pool move. The token's ACL is pool-scoped (A2: exactly the pool role, no foreign VMs visible), so an update to a VM outside the pool fails server-side. A replace or create is still pool-checked and needs confirmation.
   - **Fail-open case.** `if "create" in actions and isinstance(after, dict) and ...` passes a create whose `after` is not a dict.
   - *Fix:*
     - Change the create check to `if "create" in actions and (not isinstance(after, dict) or after.get("pool_id") != pool): raise Refused(...)`.
     - On `update`, refuse unless `before.vm_id == after.vm_id == int(TF_VAR_vm_id)` and `before.node_name == after.node_name == TF_VAR_node_name`.
     - Add `CLAUDE_CODE_ENTRYPOINT` to `confirm_on_tty`.
     - Add tests for all three.
2. **D17 TOFU for the host key: ADVISORY (owner decision).**
   - **Current state.** The guest agent now runs (notes: "the guest agent now answers") and the token has `VM.GuestAgent.FileRead`, so the TOFU pin can be checked after the fact at no cost. But `hostkey.sh` path (1) **replaces** an existing entry instead of comparing.
   - *Fix:*
     - When an entry exists, path (1) compares the agent-read key with the pinned one and aborts on a mismatch, without replacing it. Run it once (lab-ops, approved) and record "match" in the notes.
     - For rebuilds, the owner installs `qemu-guest-agent` in the template so that A12 works on first boot and TOFU isn't needed again.
   - **Separate exposure.** With the agent running, `scripts/labenv infra/lib/pve_get.sh /nodes/…/agent/file-read?file=…` (allowed for every agent, rc=0) reads any VM file as root: `/etc/shadow`, the K3s server token. *Fix:* `pve_get.sh` accepts only an allowlist of path prefixes (`/version`, `/cluster/resources`, `/pools/`, `/access/permissions`, `/storage`, `/nodes/<n>/status`, `/nodes/<n>/qemu/<id>/status/current`, `…/snapshot`, `…/tasks/`). `agent/*` stays inside `hostkey.sh`.
3. **Gate-avoidance code in `approval_check.sh`: none found, PASS.**
   - `git log --all -- infra/lib/approval_check.sh` has exactly one commit (`d976a91`), and its content is identical to HEAD. The approvals path appears as a plain literal.
   - A scan of all added lines in `git log -p main..stage/L0` for split-string, escaped, base64, `eval` or `$(printf …)` forms of gate words found nothing evasive. The only hits were the test fixture writing a fake approval inside its own `mktemp -d` tree, and ordinary `printf | jq @uri` / `openssl base64` uses.
   - The uncommitted draft itself can't be checked; it was never committed.
4. **`evals/l0` under `labenv` for any agent: BLOCKING.** See S-I2. ADVISORY on top of that: `redact.py -o`, `capture_baseline.sh --out-dir`, `prom_check.py --out-dir` and `ping_check.sh --out-dir` write to any path, outside the caller's gate scope. *Fix:* refuse an output `realpath` outside `project/reports/L0/`, `project/notes/L0.md` and the session scratchpad.
5. **Site values in history (`main..stage/L0`, count-only, 110 hits): ADVISORY now, D18 at push.** Site values themselves couldn't be checked (that needs `labenv`). By category:
   - **Notes and reports.** `project/notes/L0.md` has 0 hits in history and 0 in the working tree. The 31 files under `project/reports/L0/` have 0 hits.
   - **Test fixtures.** `evals/l0/test_redact.py` (34 RFC1918, 1 ULA IPv6, 3 instance-label, structural keys, 3 UUIDs), `evals/l0/redact.py` (allowlist and comments) and `evals/l0/test_pods_check.py` (2 structural). These look synthetic, with **one exception**: `5c75743 evals/l0/test_redact.py:205` holds an address in **the same /24 as the Proxmox LAN address already in W0 history** (not equal to it). The owner should decide whether that /24 is a ubiquitous home default or the real LAN, and change the fixture to `192.0.2.0/24` if it is the real LAN.
   - **Proxmox default names** (node `pve*`, storage `local-lvm`/`local-zfs`, bridge `vmbrN`):
     - `d2a785a infra/terraform/terraform.tfvars.example:3` (node), `:6` (storage) and `:8` (bridge). Replaced by `example-*` in `7aaab7f`. History keeps them. That only matters if they equal the real values. Generic defaults are low risk, but D18 should list them.
   - **Realm form `@pve!`** (generic realm, not a site value):
     - `d2a785a infra/tests/test_tf_apply.sh:56`
     - `2a555d2 infra/tests/test_pin.sh:35`
     - `3ee1a0f infra/tests/test_pve_get.sh:25,37`
     - `edde373 project/plans/L0.md:89,171,412,468`
     - `edde373 project/reports/L0/security.md:62,118`
   - **Not found:** home path or login name, this machine's hostname, SSH public keys, private keys, colon fingerprints.
   - **Still open for D18:** the W0 hits (`636afc7`, `727c20c`) and the `wireshark-hosts` line 33 hit (`2dca43c`) listed in STATUS.
   - *For close:* lab-ops runs `scripts/labenv python3 -I -m evals.l0.redact --scan` on a `git log -p --all` dump written to the state dir. That is the only way to check the step-1 values.
6. **Multus HelmChart installed, NAD CRD absent: not a concern for E7 (ADVISORY).**
   - Without the CRD, no NetworkAttachmentDefinition can exist, so no pod can get a macvlan, ipvlan or host-device leg past the host's prerouting hook. This is the safest state. `nad.json` records it explicitly (0 NADs, 0 `networks` annotations, all 16 pods on `cbr0` only).
   - **Two caveats:**
     1. The HelmChart has no `spec.version`, so a reinstall pulls whatever `rke2-multus` is latest, and that may add the CRD. *Fix:* pin `spec.version` (owner/telco to choose).
     2. R1 shows the VM's LAN NIC is `eth0`, the same `master` as `phase1/test-macvlan-nad.yaml`. Applying that file once the CRD exists would put a pod on the LAN past the guard. `lab.sh` never applies it and `test_lab.sh` checks that. Keep it that way, and keep the E7 NAD check on every E7 run.
7. **Anything else bypassing the guard: none found (ADVISORY items only).**
   - **What the guard covers.** The chain hooks prerouting at −150 for `inet`, before the kube-proxy/Docker DNAT at −100 (`dstnat`) and before local delivery. It therefore covers:
     - NodePorts 30030 and 30090, and every other `KUBE-NODEPORTS` entry
     - Docker-published ports
     - the hostNetwork, privileged tracer pod
     - kubelet 10250, the K3s API, flannel 8472
     - IPv6 (family-agnostic drop)
   - **The manifests.** Only Grafana and Prometheus are NodePorts, the only hostNetwork pod is the tracer, and there is no hostPort, LoadBalancer or externalIPs.
   - **Not covered by design:**
     1. A secondary CNI attachment on `eth0` (impossible today, item 6).
     2. AF_PACKET sockets. The tracer's `tcpdump -i any` still receives LAN frames before netfilter, so the pcaps contain LAN broadcast and multicast from the owner's devices (S-A9: never publish run pcaps).
   - **The allowlisted scan** shows exactly {22, 6443, 30030, 30090} open over 65535 TCP ports. The non-allowlisted scans are not run yet.

### ADVISORY (new)

- **S-I-A1 (S-A6):** the firewall role's assert accepts any prefix length, including `/0`. R1 shows a single admin address, so the current value is /32. *Fix:* assert a prefix of `/32`, or of at least `/24` with an owner override typed at the terminal.
- **S-I-A2 (S-A8):**
  - K3s `install.sh` is pinned to the tag with a committed sha256 (good). The binary is still checked against a sha256 file from the same release origin.
  - The Docker apt key is fetched without a fingerprint check.
  - The Multus chart is unpinned.
  - The UPF builder uses `archive.debian.org` with `Check-Valid-Until "false"`. Signatures are still checked, but replay or freeze of old metadata becomes possible and the builder stage gets no security updates. The tracer is digest-pinned (good).
- **S-I-A3:** `ansible.sh` forwards extra arguments. `-e ansible_ssh_common_args=…`, `--ssh-common-args`/`--ssh-extra-args` and combined flags like `-vD` are not refused. *Fix:* reject `-e`/`--extra-vars`, `--ssh-*`, and any short-flag cluster containing `v` or `D`.
- **S-I-A4 (S-B7):** Ubuntu's `nftables.service` is also ordered `Before=network-pre.target`, and `/etc/nftables.conf` starts with `flush ruleset`. Whether it is enabled on the VM was not checked. *Fix:* add `After=nftables.service` to `neoncore-guard.service`, and either mask `nftables.service` or assert it is not enabled. Check that in the R3 evidence.
- **S-I-A5:** the unit's `ExecStop` deletes the guard table. Any stop of the unit (or `isolate`) opens the LAN while sshd and K3s are still up. *Fix:* drop `ExecStop`; the table needs no teardown.
- **S-I-A6:** three never-applied `.tfplan` files remain in the state dir (mode 600 in a 700 dir). Plan files hold variable values. *Fix:* a `trap` in `tf.sh` deletes the plan file on every exit except a successful `plan`, and `apply` refuses plan files older than 30 min.
- **S-I-A7:** `infra/.gitignore` lacks `terraform.tfvars` and `*.auto.tfvars*`, although the example file tells people not to create one.
- **S-I-A8 (not security; for the evaluator's E5):** the firewall tasks use `changed_when: true` for arm, apply and cancel. The Ansible `changed=0` idempotency criterion can therefore never pass as written.
- **S-I-A9:** the D16 `start.sh` pattern also blocks read-only text such as `cat start.sh` or `git ls-files … start.sh stop.sh` for non-lab-ops agents. That's a harmless false positive; the Read tool still works.

### Could not verify (not tested)
- Step-1 site values in history and evidence: `.env.lab` is off-limits to me.
- Whether the `d2a785a` default names and the `test_redact.py:205` /24 are the owner's real values.
- Guard reboot persistence, `nftables.service` state on the VM, IPv6 on the VM, the non-allowlisted E7 scans (R2, R3), and the allowlisted UDP/SCTP scans.
- The `hostkey.sh` agent path, and whether the TOFU key matches the agent-read key.
- The replace/delete confirmation path live, and the `tf_pin_negative.sh` result (nonexistent cert file).
- Whether the WSL-era `~/.kube/config` was backed up (current file is mode 600 in a 700 dir).
- The sshd `-T` evidence file itself (it is in the state dir; the notes report the assert passed).
- S-B9 (GIF), not built.

## Gate patch re-check (2026-11-10)

Reviewer: security-reviewer. Input:
- the owner's uncommitted patch to `.claude/hooks/gate.py` and `scripts/tests/test_gate.py`, described in `project/notes/L0-gate-proposal.md`
- the evaluator's `redact.py` fix `fce5968` (and `3b89588`)

Nothing real was executed.

**What I ran:**
1. **Gate unit tests.** `python3 -I scripts/tests/test_gate.py` (fixture-based): **19/19 OK**.
2. **Gate classification.** 66 command strings, as synthetic hook JSON, against the working-tree gate, in a throwaway fixture with an approved L0 plan. This classifies text only. I report forms and counts here, not working commands.
3. **Redaction test.** `redact.py` at HEAD, under `env -i` with **fake** token, fingerprint and pool values, on synthetic input in the scratchpad.

lab-ops' advisory fixes (`6c9d655`, `0fecab1`, `2c22100`) were not reviewed in this pass and are not applied live.

### Results by item

| Item | Re-check | Status |
|---|---|---|
| **S-I1** path variants | 9/9 as expected. Blocked: `scripts/./labenv`, `./scripts//labenv`, `cd scripts && ./labenv`, bare `labenv` after `cd scripts`, `infra/./lab.sh up`, `../infra/lab.sh up`, `cd infra; ./lab.sh up`. Still allowed: `labenv infra/lab.sh status` and `labenv infra/lib/pve_get.sh /version`. `sh -c '…'`, `find -exec` and `xargs` forms are also blocked | **Closed** for path variants. Indirection remains, see R1 |
| **S-I2** gate side | 8/8 as expected. The `redact` exclusion blocks `-m evals.l0.redact` and `evals/l0/redact.py` under `labenv` for the evaluator. docs-writer, blog-writer and developer are blocked for every `evals/l0` form. Evaluator `ping_check.sh` and `pods_check` are allowed, and lab-ops `redact.py --append -o` is allowed | **Partly closed**, see R2 |
| **S-I2** redact side (`fce5968`) | Fake values: NUL-joined environ sample (as a file and on stdin), token followed by letters, fingerprint hex followed by a letter, pool name inside the environ sample. The secret and site value matches after redaction were 0 in every case. `/proc/self/environ` and `/dev/stdin` as input paths are refused with rc=2 | **Closed** |
| **S-I3** interim rules | 8/8 listed forms blocked: `env -u CLAUDECODE script -qec`, `unset CLAUDECODE`, `CLAUDECODE=`, `unbuffer`, `pty.spawn`, `scripts/appr*.sh`, `ls project/approv*`, `cat .env.l*` | **Open.** 21 variants pass (R3–R5), and the signed-approval fix is not done |

### Remaining bypasses (counts and forms only)

Of the 66 strings, 35 were bypass candidates. 32 of those pass the gate and 3 are blocked. 2 false positives also showed up.

**R1. `labenv` reached by indirection: 7 forms pass.** These are documented limits, except that any agent can use them.
- The 7 forms:
  - variable expansion in the path (`${X}env`)
  - globs (`lab*nv`, `labe?v`)
  - brace expansion
  - a string built inside `python3 -c`
  - `base64 -d | sh`
  - copying the wrapper elsewhere and running the copy
- A regex can't close these. *Fix (interim, owner):*
  - Block any command token that contains `$`, a glob or a brace and resolves under `scripts/` or `infra/`.
  - Block `base64 -d … | (ba)?sh` and `python3 -c` together with `subprocess`/`os.system`/`exec` for non-lab-ops agents.
- *Structural fix, which also closes R3–R5:* run agents as a separate OS user that can't read `.env.lab` (owned by the owner, mode 600). `labenv` then becomes a `sudo -u <owner>` entry in sudoers with an exact command allowlist (`pve_get.sh`, `lab.sh status|verify`, the named evals scripts), and `lab-ops` mutating subcommands require the owner's password. A text gate then only has to catch mistakes.

**R2. Secrets and `evals` allowance: 6 forms pass. BLOCKING (new).**
- **`cat .env.*`, `cat .env*`, `cat .env.?ab`: 3 forms (any agent).** These read the secrets file directly, with no `labenv` at all. The Read tool's basename check doesn't apply to Bash, and the new glob rule only covers `.env.l<glob>`. `set -a; . ./.env.*` (sourcing the file) also passes; that's the 4th form. This predates the patch, and an agent could hit it by accident ("show me the env file").
- **New scripts in `evals/l0/`: 2 forms (evaluator).** The allowance matches by path pattern, so the evaluator can write a new `evals/l0/<name>.sh` or `.py` (its own scope) and run it under `labenv` with the token.
- *Fix (owner, `gate.py`):*
  1. Replace the `.env` text rule with `r"\.env(\.|\b)[^\s;&|]*[*?\[{]|\.env\.lab"` and block any token whose basename starts with `.env`, for every agent.
  2. Change `EVAL_LABENV` and the `LAB` lookahead from `[a-z_]+` to an explicit list of names: `pods_check`, `ping_check`, `prom_check`, `pcap_check`, `scan_parse`, `capture_baseline`, `tls_negative`, `wsl_grep`, `compare_baseline`, `readme_static`.
  3. Also require the named file to be tracked and unmodified. The gate can check `git ls-files --error-unmatch <p>` and `git diff --quiet HEAD -- <p> evals/l0/common.py evals/l0/redact.py`, which fails closed on error.
  4. Add a `test_gate.py` case for each of these forms.

**R3. Approval path by indirection: 4 forms pass.**
- The forms: `scripts/a?prove.sh`, `scripts/ap*.sh`, `project/a*/`, and a variable that expands to the approvals folder name.
- The interim rule needs `appr` before the glob. *Fix:* block any token under `scripts/` or `project/` that contains a glob or a `$` (forms under `scripts/` and `project/` don't need globs in normal work). The real fix is still the S-I3 signature: `approve.sh` signs with an owner key an agent can't use, and `gate.py` and `approval_check.sh` verify the signature. With that in place, a forged file or a faked TTY gains nothing.

**R4. Other pty tools: 8 forms pass.**
- The forms:
  - `script --command` (long option)
  - commands piped into `script -q` (no `-c` at all)
  - `tmux new-session -d`
  - `screen -dm`
  - `socat … pty`
  - Python `from pty import spawn`
  - `pty.fork`
  - Perl `IO::Pty`
- *Fix (owner, DESTRUCTIVE list):*
  - `r"\bscript\b"` as a command word, at a segment start after `env`/`sudo`/`nohup` strip
  - `r"\b(tmux|screen|socat|unbuffer|expect|zpty)\b"`
  - `r"\bpty\b"` inside any `python3? -c` or `perl -e` text
  - `r"IO::Pty"`
  - `r"\bsystemd-run\b[^\n;&|]*--(pty|user)"`

**R5. Clearing the Claude Code markers: 9 forms pass.**
- The forms:
  - `env -i`
  - `env --unset=`
  - `export -n`
  - `unset -v`
  - `unset ${!CLAUDE@}`
  - `exec -c`
  - Python `os.environ.pop`
  - `systemd-run --user`, which starts with a fresh environment
  - `setsid -f`
- *Fix:*
  1. Extend the rule to `r"\benv\s+(-\S*\s+)*(-i|--ignore-environment|-u|--unset)\b|\b(unset|export\s+-n|declare\s+\+x|typeset\s+\+x)\b[^\n;&|]*CLAUDE|\bexec\s+-c\b|\$\{!CLAUDE|environ[^\n;&|]*CLAUDE|\bsystemd-run\b|\bsetsid\b"`.
  2. Make `approve.sh` and `approval_check.sh` stop trusting the markers: also refuse when any ancestor process is the Claude Code CLI (walk `/proc/<pid>/stat` up to PID 1 and compare `comm`/`exe`). This is still spoofable by a detached `systemd-run --user`, which is why that tool goes in the rule above.
- Only the signature in R3 closes the marker class for good.

**False positives: 2.** A read-only `grep -n expect …` and `git log --grep 'script -c'` are blocked for every agent, because the DESTRUCTIVE rules match the bare word. *Fix:* apply the pty rules only to the first word of each segment (after `segments()`), not to the flattened text.

### Status summary
- **S-I1:** closed for the reported path forms. Indirection (R1) is a documented limit with an interim fix.
- **S-I2:** redact side closed. Gate side partly closed. **New BLOCKING R2:** `.env.*` glob reads by any agent, and pattern-based evals allowance.
- **S-I3:** open. 21 variants pass (R3: 4, R4: 8, R5: 9), and the signed-approval fix is not implemented.

### Not tested
- Any of these forms against the real lab or the real `.env.lab`. By design, nothing was executed.
- lab-ops' advisory commits `6c9d655`, `0fecab1` and `2c22100`, and their live application (the Ansible run was refused by the permission check).
- Whether Claude Code's own permission layer would independently stop any of these forms. This re-check covers `gate.py` only.

## Build review: T13 site and embedded demo (2026-11-11)

Scope: commit `0e5d45d` on `stage/L0` (13 files under `site/`), plus `docs/media/tui-demo.gif`, `tui-demo.txt` and `tui-demo.tape` (`41d2e0b`, `633f451`), which the post embeds. Read-only; no product file was edited. Working tree for `site/` and `docs/media/` matched `0e5d45d` at review time (`git status --porcelain` empty for both).

### What was run
- Read every tracked file under `site/` in full, plus the built `site/dist/**` HTML (untracked, gitignored).
- `cmp`: `site/public/media/tui-demo.gif`, `site/dist/media/tui-demo.gif` and `docs/media/tui-demo.gif` are byte-identical.
- GIF container walk (own script, scratchpad): GIF89a, 1123 frames, extension blocks are 1123 graphic-control and 1 `NETSCAPE2.0` loop block. No comment or XMP block, so no embedded metadata.
- 4 of the 1123 frames rendered and viewed (0, 60, 400, 1122): prompt is `$ `, command is the relative `PYTHONPATH=phase5 phase5/.venv/bin/python3 -m neoncore_cli`, no user, host or home path in any viewed frame. The rest of the frames: not viewed by me (owner frame check per STATUS).
- `python3 -m evals.l0.redact --allow-no-site-values --scan` over all 12 tracked `site/` text files, `tui-demo.txt`, `tui-demo.tape` and the 4 built HTML files: 0 hits everywhere except `site/package-lock.json`, 133 "structural key node" hits, all `"engines": { "node": "<semver>" }` lines (checked lines 20, 48, 1291): false positives.
- The same scan **with site values** (`scripts/labenv python3 -I -m evals.l0.redact --scan …`) was **blocked by the gate** for security-reviewer ("lab-changing command: only lab-ops may run it"). I did not route around it. So the site files are **not tested** against the actual `.env.lab` value list (endpoint, node, VMID, pool, storage, bridge, fingerprint). Mitigation only: I read the post and every page in full and none of them names a node, pool, storage, bridge, VMID or fingerprint.
- Lockfile parse: lockfileVersion 3, 263 packages, all 262 `resolved` URLs on `https://registry.npmjs.org`, 262/262 with sha512 `integrity`, no `git+`/`github:`/`file:`/`link:` sources. The only `hasInstallScript` entry is `node_modules/fsevents` (macOS-only optional dependency, not installed on Linux). Root `package.json` has one dependency (`astro ^7.4.10`, locked at 7.4.10) and only `dev`/`build`/`preview` scripts, no `pre`/`postinstall`. No `.npmrc` in `site/` or `$HOME`; npm registry is the default. `npm audit --package-lock-only`: 0 vulnerabilities (2026-11-11).
- Built HTML: 0 `<script>` tags, no external `src`/`href` (only site-relative links and `/media/tui-demo.gif`), so no third-party fonts, CDNs or analytics.
- History for `site/`: `git log --all -- site` gives one commit (`0e5d45d`); its content is what was scanned above. History for `docs/media/`: `41d2e0b`, `633f451`, same content as the scanned files.
- Repo-wide history grep (`git log --all -p`) for the local username, the control machine's hostname and the `.lan` domain, and author/committer metadata (`git log --all --format`).

### BLOCKING (pre-push; not a blocker for local L0 work)
- **T13-B1. Commit metadata leaks the local username and an internal hostname.** 115 of 118 commits reachable from `--all` (including `0e5d45d`) have author and committer `Ubuntu <user@<control-machine-hostname>.<home .lan domain>>`, i.e. the local login name and the control machine's internal FQDN. Any push publishes it on every commit, and no file edit removes it. The other 3 commits (`2dca43c`, `4696330`, `327becc`, 2026-07-18) carry the owner's personal webmail address, which is the owner's call to publish (GitHub's noreply address is the usual alternative). *Fix (owner, D18 scope):* set `user.name`/`user.email` for this repo now so new commits stop adding to it, then rewrite identities before the first push (`git filter-repo --mailmap`, or fold into the D18 history decision). A rewrite changes every SHA, so the hashes quoted in `project/reports/**`, STATUS and approval files would need a mapping note.
- **T13-B2 (extends the known history hit).** `636afc7` `project/plans/W0.md` lines 9 and 22 carry the Proxmox LAN address (known, S-B8) and, on line 9, the control machine's hostname. Same D18 decision; listed so the hostname is not missed when choosing what to rewrite.

### Non-blocking
- **T13-N1. GIF/text addresses: my verdict is safe to publish.** `docs/media/tui-demo.txt` holds 10.42.0.70 (20×), 10.42.0.71 (12×), 10.42.0.76 (6×) (K3s default pod CIDR 10.42.0.0/16), 10.45.0.2 (2×) (UE pool from `phase2/manifests/01-configmaps.yaml`), 8.8.8.8 (14×). All are inside `redact.py`'s `LAB_ALLOW_NETS` and none identifies the site. The other content is synthetic: IMSI `999700000000100` (test PLMN 999/70), MSISDN `0000000100`, random pod/ReplicaSet hashes and veth names, recording timestamps. TTL 117 / about 5 ms RTT to 8.8.8.8 hints at rough proximity to a Google edge; I judge that negligible. Process note only: STATUS records that docs-writer committed despite a stop-on-IPv4 instruction; the content is fine, the deviation should still be in the close report.
- **T13-N2. Astro telemetry is on.** `~/.config/astro/config.json` has `telemetry.enabled: true` and no `ASTRO_TELEMETRY_DISABLED`/`DO_NOT_TRACK` in the environment, so `astro build` during T13 probably sent Astro's anonymous usage event (CLI command, versions, OS, a hashed project id). Whether anything was actually sent: not tested (no network capture). *Fix:* `npx astro telemetry disable` on the control machine, or `ASTRO_TELEMETRY_DISABLED=1` in the `site/package.json` scripts (blog-writer scope).
- **T13-N3. Personal/infra detail in the post.** `site/src/pages/blog/proxmox-migration.md:48` says the Proxmox API stalled because of a hung NFS mount to "the owner's NAS (switched off)". No identifier, but it tells readers the hypervisor depends on a home NAS that is off at night (an availability weak point). Owner's call; it could be reworded to "an unavailable NFS storage".
- **T13-N4. AI-disclosure statement: present and adequate.** `site/src/layouts/Base.astro:30` (footer on every page), `Base.astro:3` (default meta description), `site/src/pages/index.astro:11`, and `site/src/layouts/Post.astro:10` (panel on every post). It meets WORKFLOW.md ("states it was built with AI agents under the owner's direction") and plan §11. Accuracy nit: `Post.astro:10` says "the notes, code, evaluation and this post were written by Claude Code agents", but some L0 pieces were the owner's own (gate patch, approvals, vhs run, rollback). Suggest "mostly written by" or naming the owner steps.
- **T13-N5. "Local preview only, not published"** (`Base.astro:30`) must change when the site is published, or it becomes inaccurate. The local-only setup is otherwise sound: `astro.config.mjs:6` and `package.json:7,9` bind dev/preview to 127.0.0.1, no `site` and no deploy adapter.
- **T13-N6. Post exposure claims match the evidence.** `proxmox-migration.md:73` (allowlisted open TCP set {22, 6443, 30030, 30090}, 65531 filtered; non-allowlisted 0 of 65535 open, R3 after reboot) matches `run-2c-fromzero/README.md:48-49` and `run-3-restore/README.md:48`. The non-allowlisted scan 1 was taken at R2 and reused in R2c, which the post's "all from R2c unless noted" glosses over; that is wording, not a leak. The NodePort numbers are already public in the manifests.
- **T13-N7. Gate false positive for reviewers.** `mkdir -p` inside the session scratchpad was blocked for security-reviewer (`__unresolved_target__ is outside security-reviewer's write scope`). I worked around it by writing straight into the scratchpad without `mkdir` (no gate bypass: that path is allowed for every agent). Separately: the round-2 gate now refuses `scripts/labenv` for security-reviewer, so the R2 finding's evals allowance is narrower than in the 2026-11-10 re-check (one form tried, not a full re-test).
- **Approval files contain the owner's first name.** `project/approvals/*.sha256` (`89801b6`, `1b04884`) match the owner's first name in a history grep. I did not open those files. Include them in the D18 decision.
- No secrets, tokens, keys, fingerprints, home paths, MACs, Proxmox node/pool/storage names or employer material found in `site/**`, the built HTML, `tui-demo.txt` or `tui-demo.tape`. The only checks against real site values are my reading and the RFC1918 scan (see the block above).

### Not tested
- Redact scan with real site values (blocked by the gate, see above).
- 1119 of the 1123 GIF frames, and OCR of the GIF (no OCR tool). Coverage is the `.txt` output plus 4 frames.
- Full `git log -p --all` scrub against the redaction value list (T15c). Only username/hostname/`.lan`/RFC1918 greps plus the known hits were run; the full scrub is still due before any push.
- Where the npm Playwright used for T13's layout check was installed and what it downloaded (not in `site/package-lock.json`).
- Whether Astro telemetry was actually sent (no network capture).
- Grafana/Prometheus anonymous access and default passwords: not re-checked in this review (out of T13 scope).
- Dev/preview servers were not started; the 127.0.0.1 bind is read from config, not observed.

## Final build review (L0 close)

Reviewer: security-reviewer, 2026-11-11. Branch `stage/L0` at `0f24789`. Working tree: only `project/notes/L0-eval-summary-draft.md` is untracked (byte-identical to the committed `project/reports/L0/eval/summary.md`). `git diff HEAD` is empty, so the owner's gate patch is now committed (`1b04884`, `15de404`, `e258867`). This was read-only. I did not read `.env.lab`, contact the lab, open anything under `project/approvals/`, push, or edit product files.

### What was run
1. **Gate unit tests.** `python3 -I scripts/tests/test_gate.py`: 19/19 OK. `.claude/` and `scripts/` are clean against HEAD.
2. **Gate classification.** 50 command strings, as synthetic hook JSON, against the committed `gate.py`, in a throwaway scratchpad fixture with an approved fake plan. Nothing was executed. Forms and counts only below.
3. **Redaction re-test.** I re-ran the S-I2 checks with `redact.py` at HEAD (this includes `9a33ea7`, which postdates my last re-check), under `env -i`, with the **synthetic** `SYN_ENV` values from `evals/l0/test_redact.py`:
   - NUL-joined environ sample: secret/fingerprint occurrences after redaction = 0
   - token and fingerprint followed by letters: 0
   - `/proc/self/environ` and `/dev/stdin` as input paths: refused with rc=2
   - `test_redact.py`: 48/48 OK
4. **History scans, without site values.** I wrote a `git log -p --all` dump to the scratchpad, excluding the approvals folder, and ran `redact.scan()` over it, mapping each hit to commit/file/line. I also ran `redact.py --scan` over the 10 commits since my T13 review (`0e5d45d..0f24789`), over every tracked `site/` text file, `README.md` and `DEVLOG.md`, and over the summary and its draft.
5. **Masked greps** over tracked files and history (values masked in output) for:
   - the control machine's hostname and `.lan` domain
   - the local login and `/home/<login>`
   - the owner's first name
   - the W0 LAN /24
   - token, key and fingerprint shapes (`PVEAPIToken=`, private-key headers, `ssh-ed25519/rsa AAAA`, colon fingerprints, `ghp_`, `sk-ant-`, `AKIA`)
6. **Commit identity counts**, from `git log --all --format`, masked.
7. **Other reads:** `.claude/settings.json`; the roadmap PDF metadata (`pdfinfo` plus a byte search for `/Author`, `/Creator`, `/Producer` and XMP: none present); the Astro config on the control machine; and the R3 guard evidence.
8. **Site-value scan.** `scripts/labenv python3 -I evals/l0/redact.py --scan <history dump>` was attempted once and **blocked by the gate** for security-reviewer ("lab-changing command: only lab-ops may run it"). I did not route around it. See "Work still due before any push", item 1.

### Status of the earlier BLOCKING items

| Item | Status | Evidence |
|---|---|---|
| **S-I1** gate path variants | **Fixed** | 5/5 forms blocked: `scripts/./labenv`, `./scripts//labenv`, `cd scripts && ./labenv`, `infra/./lab.sh up`, `../infra/lab.sh up`. `labenv infra/lab.sh status` is still allowed for the evaluator. A copied wrapper is now blocked (it was a bypass in R1). Still passing: 3 indirection forms (a glob in the wrapper name, `?` in the name, a `${VAR}` in the path). That is the class documented in `docs/agent-gate.md:61` |
| **S-I2** redact | **Fixed** (re-tested at HEAD, see step 3) | — |
| **S-I2** gate side | **Fixed** | 5/5 blocked: `-m evals.l0.redact` and `evals/l0/redact.py` under `labenv` (evaluator); a new `evals/l0/newthing.sh` (explicit `EVAL_SCRIPTS` list plus the tracked-and-unchanged check, `gate.py:335-373`); docs-writer with `ping_check.sh`; security-reviewer with `redact.py --scan` |
| **R2** secrets-file globs (gate re-check) | **Partly fixed** | The 4 reported forms are blocked (`cat .env.*`, `cat .env*`, `set -a; . ./.env.lab`, and the `.env.?ab` family through the `(^\|[\s/=…])\.env` rule at `gate.py:447`). **8 new forms pass** for any agent: a glob before `env` (`.en?.lab`, `.e*.lab`, `.[e]nv.lab`), a bare `*.lab` or `.*lab`, `find … -name '*.lab' -exec cat`, a path string built in `python3 -c`, and **`grep -r <word> .` from the repo root**. The last one is an easy accident: Bash `grep -r` reads gitignored files, unlike the Grep tool. Finding **F-R2b** |
| **S-I3** TTY spoofing / approval forgery | **Open; deferred in the lead's proposal, no owner decision record found** | There is no signature: `scripts/approve.sh:14,17`, `infra/lib/approval_check.sh:15` and `infra/lib/plan_guard.py:133` still trust `[ -t 0 ]`/`-t 1` and the `CLAUDECODE`/`CLAUDE_CODE_ENTRYPOINT` markers. The interim rules (`gate.py:329-332`) block 3 forms (`env -u CLAUDECODE script -qec`, `unset CLAUDECODE`, `scripts/appr*.sh`). **15 of the 18 bypass forms I re-tested still pass**: approvals path by glob 3/4 (`a?prove.sh`, `ap*.sh`, `project/a*/`), other pty tools 6/6 (`script --command`, piped `script -q`, `tmux new-session -d`, `screen -dm`, `socat … pty`, `from pty import spawn`), marker clearing 6/7 (`env -i`, `env --unset=`, `export -n`, `exec -c`, `setsid -f`, `systemd-run --user`). `project/notes/L0-gate-proposal.md` §6 and §6b(c) frame the signed-approval and separate-OS-user fix as "your decision, later" and a W0 change needing its own plan; `project/notes/L0.md` records no owner decision on it. `docs/agent-gate.md:72-73` still says "only a human at a TTY writes them", with no line saying this is spoofable. Not exploited |
| S-B1 approval check, D16 | Implemented. Bypassable through S-I3 | — |
| S-B2 plan guard | Implemented. The fail-open create-shape advisory (interim point 1) was **not re-checked** in this pass | — |
| S-B3 TLS pin / S-B4 token out of argv | Pass (interim review). Nothing in `infra/lib/` changed since, except `pve_get.sh` | — |
| S-B5 redaction | Fixed (S-I2) | — |
| S-B6 host key | D17 TOFU (owner decision). Separate exposure fixed: `pve_get.sh` now has a path allowlist, and agent file-read is limited to the host public key (`0fecab1`, `infra/lib/pve_get.sh:18-39`). The retro-check of the TOFU key against the agent-read key: not tested | — |
| S-B7 nftables guard | **Pass, including reboot persistence** | `run-3-restore/README.md:49`: unit enabled and active after the boot, `nftables.service` masked (this closes advisory S-I-A4), table present. E7 non-allowlisted scan 2 after the reboot: 0/65535 TCP open |
| S-B8 history | **Open, due before push.** D18 is recorded in `project/notes/L0.md:20` as "accept that the Proxmox LAN address in `636afc7`/`727c20c`/`2dca43c` becomes public; no history rewrite". That covers **the LAN address only**, not the other hits below | — |
| S-B9 GIF | Done (T13 review) | — |
| **T13-B1** author metadata | **Open and grown** | 123 of 128 commits reachable from `--all` carry author and committer `Ubuntu <local login@control-machine FQDN>`. That is 8 more since the T13 review (`100fd30`, `8b9cab9`, `a59970b`, `fb1bab2`, `fed9726`, `8b47153`, `24fbf52`, `8d4b3dd`). See also F-ID |
| **T13-B2** hostname in W0 plan | **Open, and also at HEAD, not only in history** | `project/plans/W0.md:9` (HEAD) carries the control machine's hostname and the Proxmox LAN address. It was introduced in `636afc7`, and no other commit adds or removes that hostname. D18 does not cover the hostname. Editing `W0.md` changes the bytes the W0 approval hash binds (owner decision) |

### New findings

**F-ID. Placeholder commit identity (BLOCKING-for-push).**
- The repo-local `.git/config` now sets `user.name "Your Name"` and `user.email you@users.noreply.github.com`.
- `02b264d` and `0f24789` carry exactly that, as both author and committer. STATUS still says "no git user.name/email set".
- `you@users.noreply.github.com` is not the owner's GitHub noreply address, which has the form `<id>+<login>@users.noreply.github.com`. GitHub attributes legacy `<login>@users.noreply.github.com` addresses to the account with that login. A push would therefore credit these commits to whoever owns the login `you`, if that account exists (not checked; I made no network lookup).
- *Fix (owner):* set the real noreply address, and include these 2 commits in the D18 mailmap along with the 123 from T13-B1.

**F-NAME. The owner's first name and the old WSL hostname are in tracked files, and part of that is already on `origin/main` (BLOCKING-for-push, owner decision).**
- **Already on `origin/main`.** `2dca43c` (one of the 3 commits on `origin/main`) has:
  - the owner's first name in a Windows profile path: `DEVLOG.md:41` (HEAD)
  - the old WSL hostname, which contains the login: `DEVLOG.md:123` (HEAD) and `wireshark-hosts:33` (HEAD, together with an RFC1918 address)
  - a `README.md` line, since removed in `5404fb7`

  Whether `origin` is public: not tested. If it is, a rewrite cannot recall these lines. Clones, forks and caches may already hold them.
- **Also on the L0 branch:**
  - `project/plans/W0.md:22` (HEAD, `636afc7`) has the local login.
- **New on L0.** E6(a) evidence copies the `DEVLOG.md:41` line verbatim. There are 15 copies in tracked evidence. `redact.py` doesn't look for names, so its scans report 0:

  | File | Lines | Commit |
  |---|---|---|
  | `project/reports/L0/eval/wsl/allowlist-hits.txt` | 10 | `1e1e9c7` |
  | `project/reports/L0/eval/run-2b-fromzero/wsl/allowlist-hits.txt` | 10, 137 | `51b534d` |
  | `project/reports/L0/eval/run-2c-fromzero/wsl/allowlist-hits.txt` | 10, 144, 271, 426 | `9918be5` |
  | `project/reports/L0/eval/close/wsl/allowlist-hits.txt` | 10, 146, 273, 434, 568, 695, 850, 1010 | `8d4b3dd` |

- *Fix:*
  - The owner decides whether the name, login and old hostname may be public.
  - If they may not:
    - edit `DEVLOG.md:41`, `:123`, `wireshark-hosts:33` and `W0.md:22` (docs-writer for DEVLOG; the W0 plan is the owner's call)
    - regenerate or mask the four `allowlist-hits.txt` files (evaluator)
    - add the name and login to the D18 rewrite (filter-repo `--replace-text`). Rewriting `main` means a force push of a published branch.
  - Evaluator, for later stages: `wsl_grep.sh` should mask `Users\<x>` and `/home/<x>` segments before writing the evidence.

**F-PUB. Two publication paths the gate does not see (BLOCKING-for-push).**
- `git -C . push origin main` passes the gate for the lead. The gate has no rule for a plain push and relies on the `ask` rule `Bash(git push *)` in `.claude/settings.json`, and a `-C`/`-c` prefix may not match that prefix rule. Whether Claude Code would still prompt for it: not tested.
- `npx wrangler pages deploy site/dist` and `npx netlify deploy --prod` pass for blog-writer. No rule covers site-deploy CLIs, and `npx` can fetch them.
- *Fix (owner, `gate.py` DESTRUCTIVE):*
  - `r"\bgit\b[^\n;&|]*\spush\b"`, which leaves plain `git push` to the owner as WORKFLOW rule 7 intends
  - `r"\b(wrangler|netlify|vercel|surge|gh-pages|firebase)\b[^\n;&|]*\bdeploy\b|\bgh-pages\b"`
  - plus tests for both

**F-R2b. Secrets-file read forms that remain (BLOCKING-for-close, unless the owner records the risk as accepted in `close.md`).**
- These are the 8 forms in the table above. `grep -r` from the root is the one an agent is likely to hit by mistake, and it would put the token in the transcript.
- *Interim fix (owner, `gate.py:447`):* block any token that contains a glob and could match `.env.lab` (`[*?\[]` in a token ending in `lab` or `lab*`). Block `grep`/`rg -uu`/`ag` with `-r`/`-R` on `.`, `./`, `$CLAUDE_PROJECT_DIR` or the repo root, unless `--exclude=.env*` is given. Block `find … -exec`/`-execdir` together with `cat|less|head|tail|xxd|od|strings`.
- *Structural fix:* the separate-OS-user / sandbox read-deny already in `L0-gate-proposal.md` §6b(c).

### Re-check of the items the lead listed

**`site/` after `100fd30` and the post-E9 edit `8b47153`.**
- All tracked `site/` text files scan 0 hits without site values (`package-lock.json` excluded; known `engines.node` false positives).
- No secrets, node/pool/storage/bridge names, VMID, fingerprint, home path or hostname were found by reading the diff.
- Status of the T13 non-blocking items:
  - T13-N3 (NAS) is **fixed**: `proxmox-migration.md:48` now says "unavailable NFS storage".
  - T13-N4 (disclosure accuracy) is **fixed** at `Post.astro:10` and `index.astro:11`.
  - T13-N2 (telemetry) is **partly fixed**. The `package.json` scripts set `ASTRO_TELEMETRY_DISABLED=1`, but `~/.config/astro/config.json` on the control machine still has `telemetry.enabled: true`, so a direct `npx astro …` would still report.
  - T13-N5 is unchanged: `Base.astro:30` "Local preview only, not published" must change at publication.
- The post's build-note timestamps (`03:43:53Z` to `03:59:04Z`) identify nothing.

**`README.md` (`a59970b`).** One sentence linking `docs/roadmap/neoncore-roadmap.pdf`. The PDF has no author, creator, producer or XMP metadata. Scan: 0 hits.

**`DEVLOG.md` (`24fbf52`).** The added lines (tracer, 5GMM #101, E9) scan 0 hits and hold no identifiers. The old lines `DEVLOG.md:41` and `:123` are F-NAME.

**`readme30s/` and `readme30s/run2/` (`8b9cab9`, `fb1bab2`, `fed9726`).** 0 hits in the commit-range scan. No hostnames, paths or names.

**`close/wsl/` (`8d4b3dd`).**
- `grep.txt` and `static.json` are clean. The SHA, counts and README line numbers are fine.
- `allowlist-hits.txt` contains F-NAME (8 lines) and recursive copies of the earlier allowlist files (1164 lines). Content otherwise matches E6(a) as designed.

**`.claude/settings.json` (`02b264d`).**
- `frontend-design` and `playwright` are `false` again. The rest of the plugin state matches WORKFLOW: 7 enabled; `grafana-mcp`, `huggingface-skills` and `aws-core` are `false`.
- The deny and ask rules and the hook matcher are unchanged. `disableBypassPermissionsMode` is still set.
- No `.claude/settings.local.json` exists (it is gitignored). `~/.claude/settings.json` enables no plugins.

**Secret shapes over all history: 7 hits, all synthetic.**
- `fce5968` `evals/l0/redact.py` comment
- `fce5968`, `5c75743` `evals/l0/test_redact.py`, which use `SYN_ENV` with the `1111…5555` UUID and the `pve-synth.example.internal` endpoint
- `3ee1a0f` `infra/tests/test_pve_get.sh` (`…=secret`)
- `2c22100` `infra/tests/test_hostkey.sh` (`ssh-rsa AAAA` stub)
- `d2a785a` `infra/tests/test_tf_apply.sh` (`AAAA fake`) and `infra/terraform/terraform.tfvars.example` (`AAAA...`)

No private-key headers, colon fingerprints, GitHub/Anthropic/AWS keys or `/home/<login>` paths anywhere in history.

**`redact.scan()` over all history (no site values): 225 hits.**
- 48 non-allowlisted RFC1918:
  - 44 are test fixtures in `evals/l0/test_redact.py` and `redact.py:62` (`5c75743`, `3b89588`, `11aafc0`, `fce5968`, `b834ad6`)
  - the other 4: `636afc7 project/plans/W0.md:9`, `727c20c project/reports/W0/close.md:45`, `2dca43c wireshark-hosts:33`, and `5c75743 evals/l0/test_redact.py:205` (now `:272` at HEAD), which is in the same /24 as the LAN address
- 1 ULA IPv6 (fixture).
- 3 instance labels (fixtures).
- 173 structural-key hits:
  - 135 are `structural key node`, nearly all `engines.node` in `site/package-lock.json`
  - the rest are fixtures, `2dca43c phase5/neoncore_cli/k8s.py:158`, and the `d2a785a`/`7aaab7f` `terraform.tfvars.example:3` line

  No new non-fixture hit since my last review.
- **The W0 LAN address is still in HEAD**, not only in history: `project/plans/W0.md:9` and `project/reports/W0/close.md:45`. D18 accepts it becoming public.

### Work still due before any push (T15c / D18)

1. **T15c site-value scrub.** lab-ops (the only agent the gate allows) runs `scripts/labenv python3 -I evals/l0/redact.py --scan` on a `git log -p --all` dump written to the state dir or scratchpad, and records hits by commit/file/line here. My scans had no site values (endpoint, node, VMID, pool, storage, bridge, fingerprint, admin CIDR), so that part is **not tested**.
2. **D18 identity rewrite (T13-B1 + F-ID).**
   - Mailmap 125 commits: the 123 with the local login at the control machine's FQDN, and the 2 placeholder commits `02b264d`, `0f24789`.
   - The owner decides whether the 3 `origin/main` commits with the personal webmail address stay as they are. They are already published, so rewriting them means a force push of `main`.
   - Set the real `user.email` first.
   - A rewrite changes every SHA quoted in `project/reports/**`, STATUS, notes and the approval files, so keep a SHA mapping note.
3. **Hostname and login in the W0 plan (T13-B2, F-NAME).** `project/plans/W0.md:9` (control-machine hostname, together with the LAN address) and `:22` (local login): at HEAD and in `636afc7`. The owner decides whether to edit them (this breaks the W0 plan hash in the approval record) or to rewrite history.
4. **Owner name and old hostname (F-NAME).**
   - HEAD: `DEVLOG.md:41`, `:123`, `wireshark-hosts:33`, and the 15 evidence lines listed under F-NAME.
   - History: the same lines in `2dca43c` (already on `origin/main`), plus the old `README.md` line in `2dca43c`.
5. **Approval files.** A masked `git grep` (file:line output only; I did not open the files) matches the owner's first name at line 1 of `project/approvals/W0.plan.sha256`, `W0.close.sha256` (`89801b6`) and `L0.plan.sha256` (`1b04884`, the only commit that touches that file; `15de404` and `e258867` touch only `gate.py` and `test_gate.py`). The file **names** themselves (`<stage>.<kind>.sha256`, `.gitkeep`) hold nothing sensitive. The owner decides whether the name stays, and changes these files themselves (agents may not).
6. **Known history hits under D18 (LAN address, accepted):** `636afc7 project/plans/W0.md:9`, `727c20c project/reports/W0/close.md:45`. The RFC1918 address at `wireshark-hosts:33` (`2dca43c`) is not on the D18 list by value. The owner should confirm it is covered.
7. **Low risk, list only.** These matter only if they equal the real values:
   - `d2a785a infra/terraform/terraform.tfvars.example:3,6,8` (Proxmox default node/storage/bridge names)
   - the `evals/l0/test_redact.py:272` /24 fixture (moot under D18)
8. **Gate before publishing:** F-PUB rules. T13-N5 footer text at `site/src/layouts/Base.astro:30`.
9. **WORKFLOW rule 7:** the owner's employer-policy confirmation (not mine to check).

### Classification

| Finding | Class |
|---|---|
| S-I1, S-I2 (both sides), S-B3–S-B7, S-B9 | Closed / pass |
| **S-I3** (TTY spoof, approval forgery; 15/18 forms pass; no signature) | **BLOCKING-for-close**, unless the owner records the deferral and the accepted risk in `close.md` and names the follow-up plan (W0 amendment) |
| **F-R2b** (8 secrets-file read forms, including `grep -r .`) | **BLOCKING-for-close**, same condition |
| S-B8, **T13-B1**, **T13-B2**, **F-ID**, **F-NAME**, approval-file name content, T15c site-value scrub | **BLOCKING-for-push** |
| **F-PUB** (gate misses `git -C … push` and deploy CLIs) | **BLOCKING-for-push** |
| R1 indirection (3 forms, documented class) | Non-blocking (documented limit) |
| T13-N2 telemetry (global config still on), T13-N5 footer at publication, `tfvars.example` defaults, `test_redact.py:272` /24 | Non-blocking |
| `eval/summary.md` is byte-identical to the lead's draft in `project/notes/` and was committed under the placeholder identity. Who copied it into the evaluator's folder: not determined. That's a process note for the close report, not a security issue | Non-blocking |

### Not checked / not tested
- Any scan with real site values. The gate blocks it for me; it is T15c, item 1.
- Whether `origin` is public, and whether GitHub login `you` exists (no network lookup).
- Whether Claude Code's own permission layer prompts for `git -C . push` or `npx … deploy`. Only `gate.py` was classified.
- `.env.lab` file mode. The gate blocks any command naming it, correctly; I did not try another route.
- The S-B2 fail-open create-shape fix, lab-ops' advisory commits `6c9d655`, `0fecab1`, `2c22100` beyond the `pve_get.sh` allowlist, and the S-I-A1/A3/A5/A6/A7 advisories.
- The TOFU host key against the agent-read key.
- Grafana anonymous Admin and Prometheus no-auth, live. Covered only by the guard and the allowlisted scan evidence. Default passwords and the VM's open services were not re-checked by me (E7 evidence only).
- GIF frames beyond the 4 viewed at T13. Binary files in history (`traces/rogue-ue-reject.pcap` in `2dca43c`, the GIF): no pcap or OCR inspection.
- The contents of `project/approvals/*` (not opened, by rule).
