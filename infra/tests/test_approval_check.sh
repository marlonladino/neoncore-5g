#!/usr/bin/env bash
# Tests for infra/lib/approval_check.sh in a throwaway repo tree (no lab needed).
# The script derives its repo root from its own location, so each case copies it into a fake tree.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="$here/../lib/approval_check.sh"
t="$(mktemp -d)"; trap 'rm -rf "$t"' EXIT
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }

mk() {  # mk <name> -> fake repo at $t/<name>
    local r="$t/$1"
    mkdir -p "$r/infra/lib" "$r/project/plans" "$r/project/approvals"
    cp "$src" "$r/infra/lib/approval_check.sh"
    echo L0 >"$r/project/STAGE"
    echo "plan body" >"$r/project/plans/L0.md"
    h="$(sha256sum "$r/project/plans/L0.md" | cut -d' ' -f1)"
    printf '%s  %s  %s  %s\n' "$h" project/plans/L0.md 2026-01-01T00:00:00Z tester >"$r/project/approvals/L0.plan.sha256"
    echo "$r"
}
chk() { "$1/infra/lib/approval_check.sh" </dev/null >/dev/null 2>"$t/err"; }

r="$(mk match)";    chk "$r" && ok "match passes" || { bad "match passes"; cat "$t/err"; }
r="$(mk mismatch)"; echo more >>"$r/project/plans/L0.md"
chk "$r" && bad "edited plan refused" || { grep -q mismatch "$t/err" && ok "edited plan refused"; }
r="$(mk missing)";  rm "$r/project/approvals/L0.plan.sha256"
chk "$r" && bad "missing approval refused" || ok "missing approval refused"
r="$(mk noplan)";   rm "$r/project/plans/L0.md"
chk "$r" && bad "missing plan refused" || ok "missing plan refused"
r="$(mk unknown)";  echo ZZ >"$r/project/STAGE"
chk "$r" && bad "unknown stage refused" || ok "unknown stage refused"
r="$(mk nostage)";  rm "$r/project/STAGE"
chk "$r" && bad "missing STAGE refused" || ok "missing STAGE refused"
r="$(mk malformed)"; echo "nothex  x" >"$r/project/approvals/L0.plan.sha256"
chk "$r" && bad "malformed record refused" || ok "malformed record refused"
r="$(mk short)";    echo "abcd1234  x" >"$r/project/approvals/L0.plan.sha256"
chk "$r" && bad "short hash refused" || ok "short hash refused"
r="$(mk empty)";    : >"$r/project/approvals/L0.plan.sha256"
chk "$r" && bad "empty record refused" || ok "empty record refused"
r="$(mk other)";    mv "$r/project/approvals/L0.plan.sha256" "$r/project/approvals/W0.plan.sha256"
chk "$r" && bad "other stage's approval not accepted" || ok "other stage's approval not accepted"
r="$(mk readonly)"; before="$(find "$r/project/approvals" -type f -exec sha256sum {} + | sort)"
chk "$r"; after="$(find "$r/project/approvals" -type f -exec sha256sum {} + | sort)"
[ "$before" = "$after" ] && ok "never writes the approval record" || bad "never writes the approval record"

# CLAUDECODE set: even with a real terminal the exemption must not apply.
if command -v script >/dev/null; then
    r="$(mk tty_claude)"; echo more >>"$r/project/plans/L0.md"
    CLAUDECODE=1 script -qec "$r/infra/lib/approval_check.sh" /dev/null >/dev/null 2>&1 && bad "CLAUDECODE disables the owner exemption" || ok "CLAUDECODE disables the owner exemption"
    r="$(mk tty_owner)"; echo more >>"$r/project/plans/L0.md"
    env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT script -qec "$r/infra/lib/approval_check.sh" /dev/null >/dev/null 2>&1 && ok "owner at a real terminal is exempt" || bad "owner at a real terminal is exempt"
else
    echo "skip tty cases (no script(1))"
fi
exit $fail
