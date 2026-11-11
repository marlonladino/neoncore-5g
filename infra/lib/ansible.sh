#!/usr/bin/env bash
# Run an Ansible playbook against the lab VM. Strict host-key checking against the dedicated
# known_hosts; no -v, no --diff; the inventory is generated in the state dir (mode 600), so no
# address is ever in the repo or on the command line.
#
#   scripts/labenv infra/lib/ansible.sh site.yml [--tags base,kernel] [--check]
#   known tags: base kernel docker firewall k3s upf_image; nothing else is forwarded
#
# Mutating, so it needs the approval check first. Never use set -x here.
set -euo pipefail
set +x
umask 077
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"

die() { echo "ansible.sh: $*" >&2; exit 1; }
[ $# -ge 1 ] || die "usage: ansible.sh <playbook> [ansible-playbook options]"
pb="$1"; shift
case "$pb" in */*|*..*) die "playbook must be a bare file name under infra/ansible" ;; esac
[ -f "$repo/infra/ansible/$pb" ] || die "unknown playbook"
# Only these extra arguments are forwarded: --check, and --tags / -t with known role tags.
# No -e / --extra-vars, no --ssh-* / --*-args, no verbosity or diff, no combined short flags.
known_tags=" base kernel docker firewall k3s upf_image "
check_tags() {
    local t IFS=,
    [ -n "$1" ] || die "empty tag list"
    for t in $1; do
        case "$known_tags" in *" $t "*) ;; *) die "unknown tag: $t" ;; esac
    done
}
fwd=()
while [ $# -gt 0 ]; do
    case "$1" in
        --check|-C) fwd+=(--check); shift ;;
        --tags|-t) [ $# -ge 2 ] || die "--tags needs a value"; check_tags "$2"; fwd+=(--tags "$2"); shift 2 ;;
        --tags=*) check_tags "${1#--tags=}"; fwd+=("$1"); shift ;;
        *) die "argument not allowed (only --check and --tags <known tags>)" ;;
    esac
done
for v in TF_VAR_ipv4_cidr TF_VAR_vm_user LAB_SSH_KEY_FILE LAB_ADMIN_CIDR; do
    [ -n "${!v:-}" ] || die "$v is not set (run through scripts/labenv)"
done
"$here/approval_check.sh" || die "approval check failed"

state="${NEONCORE_STATE_DIR:-$HOME/.local/state/neoncore}"
mkdir -p "$state/evidence"; chmod 700 "$state" "$state/evidence"
kh="$state/known_hosts"
[ -s "$kh" ] || die "no dedicated known_hosts yet (pin the host key first)"
inv="$state/inventory"
printf '[lab]\nneoncore-lab ansible_host=%s ansible_user=%s ansible_ssh_private_key_file=%s\n' \
    "${TF_VAR_ipv4_cidr%/*}" "$TF_VAR_vm_user" "$LAB_SSH_KEY_FILE" >"$inv"
chmod 600 "$inv"

export ANSIBLE_CONFIG="$repo/infra/ansible/ansible.cfg"
export ANSIBLE_SSH_ARGS="-o StrictHostKeyChecking=yes -o UserKnownHostsFile=$kh -o IdentitiesOnly=yes -o BatchMode=yes -o ControlMaster=auto -o ControlPersist=60s"
export NEONCORE_STATE_DIR="$state"
cd "$repo/infra/ansible"
exec ansible-playbook -i "$inv" "$pb" "${fwd[@]+"${fwd[@]}"}"
