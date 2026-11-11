#!/usr/bin/env bash
# Terraform wrapper: pinned TLS, state outside the repo, plan guard before apply.
#
#   scripts/labenv infra/lib/tf.sh init
#   scripts/labenv infra/lib/tf.sh plan            # saves <state>/<run>.tfplan, prints guard summary
#   scripts/labenv infra/lib/tf.sh guard <run>.tfplan
#   scripts/labenv infra/lib/tf.sh apply <run>.tfplan   # approval check + pin + guard, then apply that file
#
# There is no destroy subcommand (destroy stays an owner-only, hand-typed command) and no
# override variable for replaces. Never use set -x here.
set -euo pipefail
set +x
umask 077
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
. "$here/pin.sh"

state="${NEONCORE_STATE_DIR:-$HOME/.local/state/neoncore}"
tfdir="$repo/infra/terraform"
sub="${1:-}"; [ $# -ge 1 ] && shift

mkdir -p "$state"; chmod 700 "$state"

planfile_arg() {
    [ $# -eq 1 ] || pin_die "usage: tf.sh $sub <run>.tfplan"
    case "$1" in */*|*..*|'') pin_die "plan file must be a bare name in the state dir" ;; esac
    case "$1" in *.tfplan) ;; *) pin_die "plan file must end in .tfplan" ;; esac
    [ -f "$state/$1" ] || pin_die "plan file not found in the state dir"
    PLANFILE="$state/$1"
}

prepare_env() {
    [ -n "${PVE_API_TOKEN:-}" ] || pin_die "PVE_API_TOKEN is not set (run through scripts/labenv)"
    export PROXMOX_VE_ENDPOINT="$PVE_ENDPOINT" PROXMOX_VE_API_TOKEN="$PVE_API_TOKEN"
    if [ -z "${TF_VAR_ssh_public_key:-}" ]; then
        [ -n "${LAB_SSH_PUBKEY_FILE:-}" ] && [ -f "$LAB_SSH_PUBKEY_FILE" ] || pin_die "LAB_SSH_PUBKEY_FILE missing"
        export TF_VAR_ssh_public_key="$(cat "$LAB_SSH_PUBKEY_FILE")"
    fi
    export TF_DATA_DIR="$state/tfdata" TF_IN_AUTOMATION=1 TF_INPUT=0
}

tf_guard() {  # $1 = plan file; the pin must already be set up
    local j="$PIN_RUN/plan.json" rc=0
    pin_exec terraform -chdir="$tfdir" show -no-color -json "$1" >"$j" || pin_die "terraform show failed"
    python3 -I "$here/plan_guard.py" "${@:2}" "$j" || rc=$?
    return $rc
}

case "$sub" in
init)
    pin_setup; prepare_env
    # init talks to the provider registry with the normal system store, not the pin.
    env -u SSL_CERT_FILE -u SSL_CERT_DIR terraform -chdir="$tfdir" init -no-color -input=false \
        -backend-config="path=$state/terraform.tfstate"
    ;;
validate)
    pin_setup; prepare_env
    env -u SSL_CERT_FILE -u SSL_CERT_DIR terraform -chdir="$tfdir" validate -no-color
    ;;
plan)
    pin_setup; prepare_env
    # Plan files hold variable values: keep only the newest one. Old, never-applied plans go now.
    rm -f -- "$state"/*.tfplan
    run="$(date -u +%Y%m%dT%H%M%SZ)-$$"
    out="$state/$run.tfplan"
    pin_exec terraform -chdir="$tfdir" plan -no-color -input=false -out="$out" >"$PIN_RUN/plan.txt" \
        || { echo "tf: terraform plan failed" >&2; exit 1; }
    chmod 600 "$out"
    echo "plan file: $run.tfplan"
    rc=0; tf_guard "$out" || rc=$?
    exit $rc
    ;;
guard)
    planfile_arg "$@"; pin_setup; prepare_env
    rc=0; tf_guard "$PLANFILE" || rc=$?
    exit $rc
    ;;
apply)
    planfile_arg "$@"
    "$here/approval_check.sh" || pin_die "approval check failed; not applying"
    pin_setup; prepare_env
    # Guard first; a delete/replace needs the typed confirmation on /dev/tty.
    tf_guard "$PLANFILE" --confirm || pin_die "plan guard refused; not applying"
    pin_exec terraform -chdir="$tfdir" apply -no-color -input=false "$PLANFILE"
    rm -f "$PLANFILE"
    ;;
*)
    pin_die "usage: tf.sh init|validate|plan|guard <file>|apply <file>"
    ;;
esac
