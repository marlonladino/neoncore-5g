#!/usr/bin/env bash
# Approval-hash check (security review S-B1). Refuses (non-zero) unless
# sha256(plans/<STAGE>.md) equals the hash recorded for that stage's plan approval.
# The recorded hash is the first field of the stage's plan approval file, in the format
# the owner's approval script writes. Read-only: this script never writes there.
#
# Exemption: the owner at a real terminal outside Claude Code ([ -t 0 ] && [ -t 1 ] and
# CLAUDECODE / CLAUDE_CODE_ENTRYPOINT unset), the same test the approval script uses.
# The repo root is derived from this script's own location; there is no override variable.
set -euo pipefail
set +x
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"

if [ -t 0 ] && [ -t 1 ] && [ -z "${CLAUDECODE:-}" ] && [ -z "${CLAUDE_CODE_ENTRYPOINT:-}" ]; then
    exit 0
fi

die() { echo "approval_check: $*" >&2; exit 1; }

stage="$(tr -d '[:space:]' <"$repo/project/STAGE" 2>/dev/null || true)"
[ -n "$stage" ] || die "unknown or missing stage"
case " W0 L0 7 8 9 10 9B 11 12 " in *" $stage "*) ;; *) die "unknown or missing stage" ;; esac

plan="$repo/project/plans/$stage.md"
rec="$repo/project/approvals/$stage.plan.sha256"
[ -f "$plan" ] || die "plan file for stage $stage is missing"
[ -f "$rec" ] || die "no recorded approval for stage $stage"

have="$(sha256sum "$plan" | cut -d' ' -f1)"
want="$(head -n1 "$rec" | cut -d' ' -f1)"
case "$want" in
    *[!0-9a-f]*|"") die "recorded approval is malformed" ;;
esac
[ ${#want} -eq 64 ] || die "recorded approval is malformed"
[ "$have" = "$want" ] || die "plan for stage $stage changed since approval (hash mismatch)"
exit 0
