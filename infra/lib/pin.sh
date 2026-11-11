#!/usr/bin/env bash
# Per-run TLS leaf pin for the Proxmox endpoint (plan L0 S-B3, S-B4). Source it; do not run it.
#
#   . infra/lib/pin.sh
#   pin_setup [--selftest-bad-pin]    # fetch leaf, compare to PVE_TLS_FINGERPRINT, or abort
#   pin_exec CMD [ARGS...]            # re-hash the leaf, export SSL_CERT_*, then run CMD
#   (pin_cleanup runs on EXIT)
#
# Needs PVE_ENDPOINT (https://host[:port]) and PVE_TLS_FINGERPRINT. Never prints a fingerprint
# or a token. There is no re-pin path: a mismatch always aborts. Never use set -x here.
set +x
umask 077

pin_die() { echo "pin: $*" >&2; exit 1; }

pin_check_env() {
    local v
    for v in PVE_ENDPOINT PVE_TLS_FINGERPRINT; do
        [ -n "${!v:-}" ] || pin_die "$v is not set (run through scripts/labenv)"
    done
    [ -z "${PROXMOX_VE_INSECURE+x}" ] || pin_die "PROXMOX_VE_INSECURE must not be set"
    [ -z "${TF_LOG+x}" ] || pin_die "TF_LOG must not be set"
    [ -z "${TF_LOG_PROVIDER+x}" ] || pin_die "TF_LOG_PROVIDER must not be set"
    if [ -n "$(compgen -v PROXMOX_VE_SSH_)" ]; then pin_die "PROXMOX_VE_SSH_* must not be set"; fi
}

pin_norm() { tr -d ': \n' | tr 'A-F' 'a-f'; }
pin_fp_of() { openssl x509 -in "$1" -noout -fingerprint -sha256 | sed 's/^[^=]*=//' | pin_norm; }

# Replace the first hex digit with a different one (0 becomes 1, anything else becomes 0).
pin_flip_first() { local c="${1:0:1}" n=0; [ "$c" != 0 ] || n=1; printf '%s' "$n${1:1}"; }

pin_cleanup() { [ -z "${PIN_RUN:-}" ] || rm -rf "$PIN_RUN"; }

pin_setup() {
    local bad=0 hp state sni=()
    [ "${1:-}" != "--selftest-bad-pin" ] || bad=1
    pin_check_env
    case "$PVE_ENDPOINT" in https://*) ;; *) pin_die "endpoint must be https" ;; esac
    hp="${PVE_ENDPOINT#https://}"; hp="${hp%%/*}"
    case "$hp" in
        \[*) pin_die "IPv6 literal endpoints are not supported" ;;
        *:*) PIN_HOST="${hp%%:*}"; PIN_PORT="${hp##*:}" ;;
        *)   PIN_HOST="$hp"; PIN_PORT=8006 ;;
    esac
    case "$PIN_PORT" in ''|*[!0-9]*) pin_die "bad port" ;; esac
    case "$PIN_HOST" in ''|*[!A-Za-z0-9.-]*) pin_die "bad host" ;; esac

    state="${NEONCORE_STATE_DIR:-$HOME/.local/state/neoncore}"
    mkdir -p "$state"; chmod 700 "$state"
    PIN_RUN="$(mktemp -d "$state/pin.XXXXXX")"; chmod 700 "$PIN_RUN"
    trap pin_cleanup EXIT
    mkdir -m 700 "$PIN_RUN/emptycerts"
    PIN_LEAF="$PIN_RUN/leaf.pem"

    # Unauthenticated fetch of the leaf only, before any credential is used.
    case "$PIN_HOST" in *[!0-9.]*) sni=(-servername "$PIN_HOST") ;; esac
    openssl s_client -connect "$PIN_HOST:$PIN_PORT" "${sni[@]}" </dev/null 2>/dev/null \
        | openssl x509 -outform PEM >"$PIN_LEAF" 2>/dev/null || true
    [ -s "$PIN_LEAF" ] || pin_die "could not fetch the node certificate"

    PIN_WANT="$(printf '%s' "$PVE_TLS_FINGERPRINT" | pin_norm)"
    if [ "$bad" = 1 ]; then
        # Fail-only: flip the first hex digit so the comparison can only fail.
        PIN_WANT="$(pin_flip_first "$PIN_WANT")"
    fi
    pin_verify || exit 1
    PIN_PK="$(openssl x509 -in "$PIN_LEAF" -pubkey -noout | openssl pkey -pubin -outform der \
              | openssl dgst -sha256 -binary | openssl base64 -A)"
}

# Re-hash the leaf and export the trust settings. Call right before every exec.
pin_verify() {
    [ -s "${PIN_LEAF:-}" ] || { echo "pin: no pinned leaf" >&2; return 1; }
    if [ "$(pin_fp_of "$PIN_LEAF")" != "$PIN_WANT" ]; then
        echo "pin: TLS fingerprint mismatch: aborting before any authenticated call" >&2
        return 1
    fi
    export SSL_CERT_FILE="$PIN_LEAF" SSL_CERT_DIR="$PIN_RUN/emptycerts"
}

pin_exec() { pin_verify || exit 1; "$@"; }
