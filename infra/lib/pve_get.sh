#!/usr/bin/env bash
# GET-only client for the Proxmox API with a pinned TLS leaf (plan L0 S-B3, S-B4).
#
#   scripts/labenv infra/lib/pve_get.sh /version
#   scripts/labenv infra/lib/pve_get.sh --san        # does the leaf SAN cover the endpoint host?
#
# Pin logic lives in pin.sh. Prints the API JSON body on stdout; never the token or a
# fingerprint. No -X, no body: only GET. Never use set -x here.
set -euo pipefail
set +x
umask 077
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/pin.sh"

[ $# -eq 1 ] || pin_die "usage: pve_get.sh <api-path>|--san"
arg="$1"
[ -n "${PVE_API_TOKEN:-}" ] || pin_die "PVE_API_TOKEN is not set (run through scripts/labenv)"
# Allowlist of API paths (security review): only what the lab code uses. Everything else is
# refused before any TLS or token work, so this client cannot read arbitrary API data, and the
# guest-agent file-read only ever returns the SSH host public key.
allowed_path() {
    local p="$1" seg='[A-Za-z0-9._-]+' q='(\?[A-Za-z0-9_=&.,-]+)?'
    # dot-dot, double slash, percent escapes (except the fixed file-read form below), control chars
    case "$p" in *..*|*//*) return 1 ;; esac
    local hostkey_q='\?file=%2Fetc%2Fssh%2Fssh_host_ed25519_key\.pub'
    [[ "$p" =~ ^/nodes/${seg}/qemu/[0-9]+/agent/file-read${hostkey_q}$ ]] && return 0
    case "$p" in *%*) return 1 ;; esac
    [[ "$p" =~ ^/(version|cluster/resources|access/permissions|pools|storage)${q}$ ]] && return 0
    [[ "$p" =~ ^/(pools|storage)/${seg}${q}$ ]] && return 0
    [[ "$p" =~ ^/nodes/${seg}/status${q}$ ]] && return 0
    [[ "$p" =~ ^/nodes/${seg}/qemu/[0-9]+/status/current${q}$ ]] && return 0
    [[ "$p" =~ ^/nodes/${seg}/qemu/[0-9]+/snapshot${q}$ ]] && return 0
    [[ "$p" =~ ^/nodes/${seg}/tasks/[A-Za-z0-9:._@!-]+(/status)?${q}$ ]] && return 0
    return 1
}
if [ "$arg" != "--san" ]; then
    case "$arg" in /*) ;; *) pin_die "path must start with /" ;; esac
    case "$arg" in *[[:space:]\"\'\\]*) pin_die "path has forbidden characters" ;; esac
    allowed_path "$arg" || pin_die "path is not on the allowlist"
fi

pin_setup

if [ "$arg" = "--san" ]; then
    case "$PIN_HOST" in
        *[!0-9.]*) out="$(openssl x509 -in "$PIN_LEAF" -noout -checkhost "$PIN_HOST")" ;;
        *)         out="$(openssl x509 -in "$PIN_LEAF" -noout -checkip "$PIN_HOST")" ;;
    esac
    case "$out" in
        *"does match"*) echo "san: covers endpoint host" ;;
        *) echo "san: does NOT cover endpoint host"; exit 2 ;;
    esac
    exit 0
fi

# Token goes to curl on stdin only (--config -), never argv.
printf '%s\n' \
    "header = \"Authorization: PVEAPIToken=${PVE_API_TOKEN}\"" \
    "url = \"https://${PIN_HOST}:${PIN_PORT}/api2/json${arg}\"" \
    "cacert = \"$PIN_LEAF\"" \
    "pinnedpubkey = \"sha256//${PIN_PK}\"" \
    "silent" "show-error" "fail" "max-time = 30" "proto = \"=https\"" \
  | pin_exec curl --config -
