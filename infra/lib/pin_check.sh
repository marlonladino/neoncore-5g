#!/usr/bin/env bash
# Verify the TLS pin only (no authenticated call). T7's lab.sh calls this before terraform/curl.
#   scripts/labenv infra/lib/pin_check.sh [--selftest-bad-pin]
# Exit 0 = pin matches; non-zero = abort. --selftest-bad-pin can only cause failure (E10).
set -euo pipefail
set +x
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/pin.sh"
[ $# -le 1 ] || pin_die "usage: pin_check.sh [--selftest-bad-pin]"
[ "${1:-}" = "" ] || [ "$1" = "--selftest-bad-pin" ] || pin_die "unknown argument"
pin_setup "${1:-}"
echo "pin: ok"
