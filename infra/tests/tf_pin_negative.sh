#!/usr/bin/env bash
# Live negative test for the Terraform side of the pin (plan L0 T2, A11). Read-only: an
# empty config with one read-only data source; no resources, nothing is changed on Proxmox.
#   scripts/labenv infra/tests/tf_pin_negative.sh
# Checks: (1) with the pinned leaf, terraform plan connects; (2) with SSL_CERT_FILE pointing at a
# nonexistent file, terraform plan fails at TLS (no silent fallback to the system store).
set -uo pipefail
set +x
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/../lib/pin.sh"
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }

pin_setup
[ -n "${PVE_API_TOKEN:-}" ] || pin_die "PVE_API_TOKEN is not set"
w="$PIN_RUN/tf"; mkdir -m 700 "$w"
cat >"$w/main.tf" <<'TF'
terraform {
  required_providers {
    proxmox = { source = "bpg/proxmox", version = "0.121.0" }
  }
}
provider "proxmox" {}
data "proxmox_virtual_environment_version" "v" {}
TF
export PROXMOX_VE_ENDPOINT="$PVE_ENDPOINT" PROXMOX_VE_API_TOKEN="$PVE_API_TOKEN"
export TF_IN_AUTOMATION=1 TF_INPUT=0 TF_DATA_DIR="$w/.terraform"

# init talks only to the provider registry, with the normal system store (not the pin).
if ! env -u SSL_CERT_FILE -u SSL_CERT_DIR terraform -chdir="$w" init -no-color >"$w/init.log" 2>&1; then bad "terraform init"; grep -v "^$" "$w/init.log" | head -12 | sed -E "s#https?://[^ ]*#<url>#g"; exit 1; fi

pin_exec terraform -chdir="$w" plan -no-color -lock=false >"$w/pos.log" 2>&1; rc=$?
[ $rc -eq 0 ] && ok "pinned leaf: plan connects (read-only)" || { bad "pinned leaf: plan connects (rc=$rc)"; grep -i "error" "$w/pos.log" | head -3 | sed -E 's#https?://[^ ]*#<url>#g'; }
grep -qE 'to (add|change|destroy)' "$w/pos.log" && ! grep -qE 'No changes|0 to add, 0 to change, 0 to destroy' "$w/pos.log" && bad "plan has no changes" || ok "plan has no changes"

# Negative: nonexistent SSL_CERT_FILE, empty SSL_CERT_DIR.
SSL_CERT_FILE="$PIN_RUN/does-not-exist.pem" SSL_CERT_DIR="$PIN_RUN/emptycerts" \
    terraform -chdir="$w" plan -no-color -lock=false >"$w/neg.log" 2>&1; rc=$?
[ $rc -ne 0 ] && ok "nonexistent SSL_CERT_FILE: terraform fails" || bad "nonexistent SSL_CERT_FILE: terraform fails"
grep -qiE 'x509|certificate|tls' "$w/neg.log" && ok "failure is a TLS/certificate error" || bad "failure is a TLS/certificate error"
exit $fail
