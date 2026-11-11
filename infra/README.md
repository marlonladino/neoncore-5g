# infra/

Terraform (`terraform/`), Ansible (`ansible/`), and the wrappers in `lib/` that the lab commands
use. Day-to-day use is `scripts/labenv infra/lab.sh <up|deploy|verify|status|...>`; see
`docs/lab-proxmox.md`. This file only holds the **owner-only from-zero procedure** (T9 / E5).

Nothing below is run by an agent. Destroying a VM is the owner's action every time, and
`tf.sh` and `lab.sh` deliberately have no destroy subcommand. The destroy steps here have not been
rehearsed ("not tested"); read every prompt.

## Owner-only: tear down for a from-zero run

Run these in **your own terminal** (not inside Claude Code), from the repo root, on the control
machine. `<state>` means `${NEONCORE_STATE_DIR:-$HOME/.local/state/neoncore}`, the same state
directory `infra/lib/tf.sh` uses (state file `<state>/terraform.tfstate`, data dir
`<state>/tfdata`).

### Recommended: Terraform destroy through the TLS pin

```bash
scripts/labenv bash -c '
set -euo pipefail
. infra/lib/pin.sh
pin_check_env
pin_setup
state="${NEONCORE_STATE_DIR:-$HOME/.local/state/neoncore}"
export PROXMOX_VE_ENDPOINT="$PVE_ENDPOINT" PROXMOX_VE_API_TOKEN="$PVE_API_TOKEN"
export TF_DATA_DIR="$state/tfdata" TF_IN_AUTOMATION=1 TF_INPUT=0
export TF_VAR_ssh_public_key="$(cat "$LAB_SSH_PUBKEY_FILE")"
pin_exec terraform -chdir=infra/terraform destroy
'
```

`destroy` prints the plan and asks you to type `yes`. The plan must show exactly one resource,
`proxmox_virtual_environment_vm.*`, with the VMID from your plan. Anything else: answer `no`.
There is no `-auto-approve`, and `TF_LOG` and `PROXMOX_VE_SSH_*` stay unset (`pin_check_env`
refuses them).

**Why this over a GUI delete:**
- The same pinned TLS leaf and the same state file as every other infra command, so Terraform's
  state ends up consistent (empty) and the plan shows exactly what goes.
- It uses the lab token, which cannot touch anything outside the NeonCore pool.
- Deleting in the Proxmox GUI uses your admin login and leaves a stale state entry, so you must
  also remove the state file by hand and cannot see an object-by-object plan first.

Fallback if the API token cannot destroy: delete the VM in the Proxmox GUI (check the VMID first,
tick "destroy unreferenced disks" and "purge from job configs"), then do the state clean-up below.

### Clear for a true from-zero

```bash
state="${NEONCORE_STATE_DIR:-$HOME/.local/state/neoncore}"
rm -f  "$state"/terraform.tfstate "$state"/terraform.tfstate.backup   # state file must be absent
rm -f  "$state"/known_hosts                                           # old VM host key pin
rm -f  "$state"/*.tfplan                                              # plan files hold variable values
rm -f  "$state"/inventory
mv -n  ~/.kube/config ~/.kube/config.before-fromzero                  # move aside, do not delete
```

- `<state>/tfdata` (provider cache, backend config) can stay; `lab.sh up` re-runs `terraform init`.
- `<state>/evidence` and `<state>/artifacts` belong to the old VM. Move them aside if you want to
  keep them, because the E5 run rewrites `evidence/*`.
- `lab.sh up` passes `--fresh` to `hostkey.sh` after a create, so a leftover `known_hosts` entry
  would be dropped anyway, but E5 expects it removed up front.

### What is deleted with the VM, and what survives

- Deleted with the VM: the root disk, **all snapshots (`l0-base`, and `golden-l0` if it exists)**,
  the K3s cluster and every pod and volume on it, the pcaps, the locally built UPF image.
  If you want `golden-l0` after the rebuild, take it again once L0 is green.
- Survives (owner-made, outside this repo's destroy): the cloud-init **template** VM
  (`TF_VAR_template_vm_id`), the **pool**, the **API token and its ACL**, `.env.lab`, the SSH key
  pair, and the Proxmox host itself. Nothing else in Proxmox is touched.

## E5 preconditions (the evaluator runs these first)

Per the plan, recorded before the from-zero command starts:

1. Clean tree, SHA logged: `git status --porcelain` is empty, then `git rev-parse HEAD`.
2. No VM with the NeonCore VMID exists. Read-only API call, result recorded as yes/no only:
   `scripts/labenv infra/lib/pve_get.sh '/cluster/resources?type=vm'` and check that no entry has
   the VMID `TF_VAR_vm_id` (do not print other guests).
3. The state file is absent: `test ! -e "<state>/terraform.tfstate"`.
4. The previous (pre-Proxmox) lab is shut down (owner's timestamp); N/A once its VM has been deleted.

Then the single command: `scripts/labenv infra/lab.sh up`, with start and end timestamps and exit
code. Idempotency afterwards: a second `scripts/labenv infra/lab.sh up` must give a Terraform plan
of 0 to add, 0 to change, 0 to destroy, and Ansible `changed=0` with `failed=0`.
