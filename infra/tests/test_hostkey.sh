#!/usr/bin/env bash
# hostkey.sh agent path: pin when absent, compare (never replace) when present, abort on mismatch.
# pin.sh, pve_api.sh and approval_check.sh are stubbed; no network, no lab.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
t="$(mktemp -d)"; trap 'rm -rf "$t"' EXIT
fail=0; ok() { echo "ok   $1"; }; bad() { echo "FAIL $1"; fail=1; }
mkdir -p "$t/lib"
cp "$here/../lib/hostkey.sh" "$here/../lib/common.sh" "$t/lib/"
cat >"$t/lib/pin.sh" <<'S'
pin_die() { echo "pin: $*" >&2; exit 1; }
pin_setup() { :; }
S
cat >"$t/lib/pve_api.sh" <<'S'
pve_preflight() { :; }
pve_check_vm_env() { :; }
pve_api() { jq -n --arg c "$FAKE_PUB" '{data:{content:$c}}'; }
S
printf '#!/bin/sh\nexit 0\n' >"$t/lib/approval_check.sh"; chmod +x "$t/lib/approval_check.sh"
ssh-keygen -q -t ed25519 -N '' -f "$t/k1"; ssh-keygen -q -t ed25519 -N '' -f "$t/k2"
k1="$(cut -d' ' -f1,2 "$t/k1.pub")"; k2="$(cut -d' ' -f1,2 "$t/k2.pub")"
run() { env NEONCORE_STATE_DIR="$t/st" TF_VAR_ipv4_cidr=192.0.2.10/24 TF_VAR_vm_user=u LAB_SSH_KEY_FILE=/nonexistent \
        TF_VAR_node_name=n1 TF_VAR_vm_id=100 FAKE_PUB="$1" bash "$t/lib/hostkey.sh" "${@:2}"; }
rm -rf "$t/st"
run "$k1 root@x" >/dev/null 2>&1 && ok "pins when no entry exists" || bad "pins when no entry exists"
grep -q "^192.0.2.10 $k1\$" "$t/st/known_hosts" && ok "entry written" || bad "entry written"
run "$k1 root@x" >/dev/null 2>&1 && ok "matching key passes" || bad "matching key passes"
before="$(cat "$t/st/known_hosts")"
out="$(run "$k2 root@x" 2>&1)"; rc=$?
[ $rc -ne 0 ] && echo "$out" | grep -q mismatch && ok "mismatch aborts" || bad "mismatch aborts ($rc)"
[ "$(cat "$t/st/known_hosts")" = "$before" ] && ok "mismatch does not replace the pin" || bad "mismatch does not replace the pin"
run "$k2 root@x" --fresh >/dev/null 2>&1 && grep -q "$k2" "$t/st/known_hosts" && ok "--fresh re-pins a new VM" || bad "--fresh re-pins"
run "ssh-rsa AAAA" >/dev/null 2>&1 && bad "non-ed25519 refused" || ok "non-ed25519 refused"
exit $fail
