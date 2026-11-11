#!/usr/bin/env bash
# Tests for infra/lab.sh argument handling, the approval refusal, and the start.sh/stop.sh wrappers.
# Runs in a throwaway repo tree with stub terraform/curl/ssh/kubectl/ansible-playbook/labenv on PATH,
# so no lab is needed and any attempt to reach one is detected (the stubs log their calls).
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
real="$(cd "$here/../.." && pwd)"
t="$(mktemp -d)"; trap 'rm -rf "$t"' EXIT
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }

mkdir -p "$t/bin"
for s in terraform curl ssh kubectl ansible-playbook openssl; do
    printf '#!/bin/sh\necho "%s $*" >> "%s/calls.log"\nexit 1\n' "$s" "$t" >"$t/bin/$s"
    chmod +x "$t/bin/$s"
done

mk() {  # mk <name> [approved|unapproved|missing] -> fake repo at $t/<name>
    local r="$t/$1" mode="${2:-approved}" h
    mkdir -p "$r/infra" "$r/project/plans" "$r/project/approvals" "$r/scripts"
    cp -r "$real/infra/lib" "$r/infra/lib"; cp "$real/infra/lab.sh" "$r/infra/lab.sh"
    cp "$real/start.sh" "$real/stop.sh" "$r/"
    printf '#!/bin/sh\necho "labenv $*" >> "%s/calls.log"\nexit 0\n' "$t" >"$r/scripts/labenv"
    chmod +x "$r/scripts/labenv"
    echo L0 >"$r/project/STAGE"; echo "plan body" >"$r/project/plans/L0.md"
    h="$(sha256sum "$r/project/plans/L0.md" | cut -d' ' -f1)"
    case "$mode" in
        approved)   printf '%s  x  y  z\n' "$h" >"$r/project/approvals/L0.plan.sha256" ;;
        unapproved) printf '%s  x  y  z\n' "$(printf 'old' | sha256sum | cut -d' ' -f1)" >"$r/project/approvals/L0.plan.sha256" ;;
        missing)    ;;
    esac
    echo "$r"
}
# run <repo> <args...>: no TTY, CLAUDECODE set (the owner exemption must not apply), stubs first on PATH
run() { local r="$1"; shift; : >"$t/calls.log"; env -i HOME="$t/home" PATH="$t/bin:/usr/bin:/bin" CLAUDECODE=1 "$r/infra/lab.sh" "$@" </dev/null >"$t/out" 2>"$t/err"; }
calls() { wc -l <"$t/calls.log" | tr -d ' '; }

r="$(mk a)"
# --- argument handling (exit 2 = usage, before anything runs)
run "$r"; [ $? = 2 ] && ok "no arguments: usage, exit 2" || bad "no arguments: usage, exit 2"
for c in destroy rollback delete restore teardown reset rm "" bogus; do
    run "$r" "$c"; rc=$?
    [ $rc = 2 ] && [ "$(calls)" = 0 ] && ok "refused subcommand '$c' (exit 2, nothing ran)" || bad "refused subcommand '$c' (rc=$rc)"
done
for c in up deploy verify start stop; do
    run "$r" "$c" extra; rc=$?
    [ $rc = 2 ] && [ "$(calls)" = 0 ] && ok "$c rejects extra arguments" || bad "$c rejects extra arguments (rc=$rc)"
done
run "$r" snapshot;                    [ $? = 2 ] && ok "snapshot needs a name" || bad "snapshot needs a name"
run "$r" snapshot a b;                [ $? = 2 ] && ok "snapshot takes exactly one name" || bad "snapshot takes exactly one name"
for n in foo golden-l0x '../x' 'l0-base;id' 'PRE-1' ''; do
    run "$r" snapshot "$n"; rc=$?
    [ $rc != 0 ] && [ "$(calls)" = 0 ] && ok "snapshot name '$n' rejected" || bad "snapshot name '$n' rejected (rc=$rc)"
done
run "$r" status --bogus;              [ $? = 2 ] && ok "status rejects unknown flag" || bad "status rejects unknown flag"
run "$r" status --selftest-bad-pin x; [ $? = 2 ] && ok "status takes at most one flag" || bad "status takes at most one flag"
run "$r" verify --selftest-bad-pin;   [ $? = 2 ] && ok "--selftest-bad-pin only on status" || bad "--selftest-bad-pin only on status"

# --- approval refusal for every mutating subcommand (stub tools must never be called)
for mode in unapproved missing; do
    rr="$(mk "m_$mode" $mode)"
    for c in up deploy start stop "snapshot l0-base" "snapshot golden-l0" "snapshot pre-x"; do
        run "$rr" $c; rc=$?
        if [ $rc = 1 ] && grep -q "approval check failed" "$t/err" && [ "$(calls)" = 0 ]; then ok "[$mode] '$c' refused, nothing ran"; else bad "[$mode] '$c' refused, nothing ran (rc=$rc, calls=$(calls))"; fi
    done
done
# approved plan passes the approval step (then fails later on the missing env, never on approval)
rr="$(mk approved approved)"
run "$rr" up; rc=$?
if grep -q "approval check failed" "$t/err"; then bad "approved plan passes the approval step"; else ok "approved plan passes the approval step (rc=$rc, stops on env: $(head -c 60 "$t/err" | tr -d '\n' | sed 's/[0-9.]\{7,\}/<n>/g'))"; fi
[ "$(calls)" = 0 ] && ok "approved but no lab env: still nothing ran" || bad "approved but no lab env: still nothing ran"

# --- read-only subcommands need no approval
run "$(mk ro unapproved)" verify; grep -q "approval" "$t/err" && bad "verify needs no approval" || ok "verify needs no approval"
run "$(mk ro2 missing)" status;   grep -q "approval" "$t/err" && bad "status needs no approval" || ok "status needs no approval"

# --- E10 selftest: fails, even with a complete env, and before any terraform/curl
run "$(mk st unapproved)" status --selftest-bad-pin; rc=$?
[ $rc != 0 ] && ok "status --selftest-bad-pin exits non-zero" || bad "status --selftest-bad-pin exits non-zero"
grep -qE '^(terraform|curl) ' "$t/calls.log" && bad "selftest runs no terraform/curl" || ok "selftest runs no terraform/curl"

# --- start.sh / stop.sh wrappers: approval first, then labenv lab.sh
for w in start stop; do
    rr="$(mk "w_$w" unapproved)"; : >"$t/calls.log"
    env -i HOME="$t/home" PATH="$t/bin:/usr/bin:/bin" CLAUDECODE=1 "$rr/$w.sh" </dev/null >/dev/null 2>"$t/err"; rc=$?
    [ $rc != 0 ] && [ "$(calls)" = 0 ] && ok "$w.sh refused without approval, labenv never ran" || bad "$w.sh refused without approval (rc=$rc)"
    rr="$(mk "wa_$w" approved)"; : >"$t/calls.log"
    env -i HOME="$t/home" PATH="$t/bin:/usr/bin:/bin" CLAUDECODE=1 "$rr/$w.sh" </dev/null >/dev/null 2>&1
    grep -q "^labenv .*infra/lab.sh $w\$" "$t/calls.log" && ok "$w.sh runs labenv infra/lab.sh $w when approved" || bad "$w.sh runs labenv infra/lab.sh $w when approved"
done

# --- static checks on the real files
code() { grep -v '^ *#' "$@"; }
code "$real/infra/lab.sh" | grep -Eq '(^|[^a-z])set -[a-z]*x' && bad "lab.sh has no set -x" || ok "lab.sh has no set -x"
code "$real/infra/lab.sh" | grep -Eiq 'terraform +destroy|\bdestroy\b|rollback|delsnapshot|qm +(destroy|rollback)|-X *DELETE|"DELETE"' && bad "lab.sh has no destroy/rollback/delete path" || ok "lab.sh has no destroy/rollback/delete path"
code "$real/infra/lib/pve_power.sh" | grep -Eq 'status/(stop|reset)|DELETE' && bad "pve_power.sh: graceful shutdown only" || ok "pve_power.sh: graceful shutdown only"
f="$real/infra/lab.sh"
l() { awk -v pat="$1" '/^cmd_up\(\)/{u=1} u && index($0,pat){print NR; exit}' "$f"; }
prev=0; good=1
for p in 'pin_check.sh' 'tf.sh" init' 'tf.sh" plan' 'tf.sh" apply' 'hostkey.sh' 'cloud-init status' 'ansible.sh" site.yml' 'ansible.sh" k3s.yml' 'cmd_deploy' 'cmd_verify'; do
    n="$(l "$p")"; if [ -z "$n" ] || [ "$n" -lt "$prev" ]; then good=0; echo "  order problem at: $p"; fi; prev="${n:-0}"
done
[ $good = 1 ] && ok "up order: pin, init/plan(guard), apply, host key, cloud-init, ansible x2, deploy, verify" || bad "up order"
grep -q 'phase1/multus-helmchart.yaml' "$f" && ok "deploy applies the Multus HelmChart" || bad "deploy applies the Multus HelmChart"
code "$f" | grep -q 'test-macvlan-nad' && bad "deploy never applies the test NAD" || ok "deploy never applies the test NAD"
# recovery order inside recover_order: upf < smf < ue
g="$(awk '/^recover_order\(\)/{u=1} u&&/deploy\/upf/{a=NR} u&&/restart deploy\/smf/{b=NR} u&&/restart deploy\/ue/{c=NR} END{print (a&&b&&c&&a<b&&b<c)?1:0}' "$f")"
[ "$g" = 1 ] && ok "recovery order UPF -> SMF -> UE" || bad "recovery order UPF -> SMF -> UE"
grep -q 'nicolaka/netshoot@sha256:b09d9b21381f47a79b3cbcb30da25266dc17186ea00ae65e99fdc51396f48e70' "$real/phase4/manifests/02-tracer.yaml" && ok "tracer image pinned by digest (D9)" || bad "tracer image pinned by digest (D9)"
grep -q 'netshoot:latest' "$real/phase4/manifests/02-tracer.yaml" && bad "no :latest tracer tag" || ok "no :latest tracer tag"
# start race: kubectl wait on the UPF pod must retry past "no matching resources found" (bounded)
grep -q 'wait_pod_ready app=upf' "$f" && ok "cmd_start waits for the UPF pod with the retrying helper" || bad "cmd_start waits for the UPF pod with the retrying helper"
code "$f" | grep -Eq '^\s*kc -n \$ns wait .*-l app=upf' && bad "no bare kubectl wait on the UPF label" || ok "no bare kubectl wait on the UPF label"
mkdir -p "$t/race/bin"
printf '#!/bin/sh\nn=$(cat "%s/race/n" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "%s/race/n"\nif [ $n -le 2 ]; then echo "error: no matching resources found" >&2; exit 1; fi\necho "pod/upf condition met"; exit 0\n' "$t" "$t" >"$t/race/bin/kubectl"
chmod +x "$t/race/bin/kubectl"
fn="$(awk '/^wait_pod_ready\(\)/{u=1} u{print} u&&/^}/{exit}' "$f")"
( PATH="$t/race/bin:$PATH"; ns=neoncore; WAIT_POD_STEP=1; kc() { kubectl "$@"; }; eval "$fn"; wait_pod_ready app=upf 10 ) \
    && [ "$(cat "$t/race/n")" = 3 ] && ok "wait_pod_ready retries 'no matching resources' then succeeds (3 calls)" || bad "wait_pod_ready retries 'no matching resources' then succeeds"
printf '#!/bin/sh\necho "error: no matching resources found" >&2; exit 1\n' >"$t/race/bin/kubectl"
( PATH="$t/race/bin:$PATH"; ns=neoncore; WAIT_POD_STEP=1; kc() { kubectl "$@"; }; eval "$fn"; wait_pod_ready app=upf 3 ) \
    && bad "wait_pod_ready is bounded and fails when the pod never appears" || ok "wait_pod_ready is bounded and fails when the pod never appears"
exit $fail
