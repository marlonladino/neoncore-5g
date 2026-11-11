#!/usr/bin/env bash
# NeonCore 5G approval gate -- run by the USER, in their own terminal, never by an agent.
#
#   scripts/approve.sh <stage> plan    approve project/plans/<stage>.md
#   scripts/approve.sh <stage> close   approve project/reports/<stage>/close.md
#
# Writes project/approvals/<stage>.<kind>.sha256. The gate hook
# (.claude/hooks/gate.py) compares that hash with the file's current hash, so any
# later edit to the approved file voids the approval.
set -euo pipefail

die() { echo "approve.sh: $*" >&2; exit 1; }

if [ ! -t 0 ] || [ ! -t 1 ]; then
    die "refusing to run without an interactive terminal (stdin and stdout must be a TTY)."
fi
if [ -n "${CLAUDECODE:-}" ] || [ -n "${CLAUDE_CODE_ENTRYPOINT:-}" ]; then
    die "refusing to run inside a Claude Code shell. Run it yourself in your own terminal."
fi

[ $# -eq 2 ] || die "usage: scripts/approve.sh <stage> <plan|close>"
stage="$1"; kind="$2"

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
stages="W0 L0 7 8 9 10 9B 11 12"
case " $stages " in *" $stage "*) ;; *) die "unknown stage '$stage' (known: $stages)";; esac

case "$kind" in
    plan)  target="project/plans/${stage}.md" ;;
    close) target="project/reports/${stage}/close.md" ;;
    *)     die "kind must be 'plan' or 'close'" ;;
esac
[ -f "$repo/$target" ] || die "$target does not exist"

current_stage="$(tr -d '[:space:]' < "$repo/project/STAGE" 2>/dev/null || true)"
[ "$current_stage" = "$stage" ] || echo "WARNING: project/STAGE is '$current_stage', not '$stage'."

hash="$(sha256sum "$repo/$target" | cut -d' ' -f1)"
title="$(grep -m1 '^# ' "$repo/$target" || echo '(no # title)')"
lastlog="$(git -C "$repo" log -1 --format='%h %ad %s' --date=short -- "$target" 2>/dev/null || true)"
dirty="$(git -C "$repo" status --porcelain -- "$target" 2>/dev/null || true)"

echo "============================================================"
echo " NeonCore approval: stage $stage, $kind"
echo "============================================================"
echo " File:    $target"
echo " Title:   $title"
echo " SHA-256: $hash"
echo " Last commit touching it: ${lastlog:-(never committed)}"
[ -n "$dirty" ] && echo " NOTE: file has uncommitted changes (you are approving the working copy)."
echo
echo "Read the file before approving. Type APPROVE (exactly) to approve, anything else aborts."
read -r -p "> " answer
[ "$answer" = "APPROVE" ] || die "not approved."

out="$repo/project/approvals/${stage}.${kind}.sha256"
mkdir -p "$repo/project/approvals"
[ -e "$out" ] && chmod u+w "$out"
printf '%s  %s  %s  %s\n' "$hash" "$target" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${USER:-unknown}" > "$out"
chmod 444 "$out"
echo "Approved. Wrote ${out#"$repo"/}"
echo "Commit it yourself when convenient: git add project/approvals && git commit -m 'Approve $stage $kind'"
