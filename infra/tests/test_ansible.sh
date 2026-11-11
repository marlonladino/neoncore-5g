#!/usr/bin/env bash
# Static tests for infra/ansible and the wrappers (no lab needed).
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
a="$here/../ansible"; lib="$here/../lib"
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }

for pb in site.yml k3s.yml; do
    ANSIBLE_CONFIG="$a/ansible.cfg" ansible-playbook --syntax-check -i localhost, "$a/$pb" >/dev/null 2>&1 && ok "syntax $pb" || bad "syntax $pb"
done
code() { grep -rhv -e '^ *#' -e '^ *- name:' "$@"; }
code "$a" | grep -q 'flush ruleset' && bad "no flush ruleset" || ok "no flush ruleset"
# nftables.service may only be masked and inspected, never started, stopped, restarted or reloaded
code "$a/roles/firewall" | grep -Eq 'systemctl +(start|stop|restart|reload|isolate)[^#]*nftables|nftables[^#]*(state: *(started|restarted|reloaded|stopped))' && bad "nftables.service never started/restarted" || ok "nftables.service never started/restarted"
grep -q 'masked: true' "$a/roles/firewall/tasks/main.yml" && grep -q "in \['masked', 'disabled'\]" "$a/roles/firewall/tasks/main.yml" && ok "nftables.service masked and asserted masked/disabled" || bad "nftables.service masked and asserted"
svc="$a/roles/firewall/templates/neoncore-guard.service.j2"
grep -q '^After=.*nftables\.service' "$svc" && ok "unit ordered After=nftables.service" || bad "unit After=nftables.service"
grep -q '^ExecStop' "$svc" && bad "unit has no ExecStop" || ok "unit has no ExecStop"
grep -q '/32\$' "$a/roles/firewall/tasks/main.yml" && ok "admin CIDR asserted /32" || bad "admin CIDR /32"
# idempotency: no unconditional changed_when: true outside the when-guarded apply block
awk '/^- name: Apply the guard with auto-revert/{b=1} b==0 && /changed_when: *true/{print "x"}' "$a/roles/firewall/tasks/main.yml" | grep -q x && bad "no unconditional changed_when: true" || ok "changed_when: true only inside the guarded apply block"
grep -rn 'changed_when: *true' "$a/roles" | grep -v firewall >/dev/null && bad "other roles: no changed_when true" || ok "other roles: no forced changed"
grep -rq 'nf_conntrack_proto_sctp' "$a" --include=main.yml | grep -v '^#' >/dev/null 2>&1
grep -rE 'modprobe.*nf_conntrack_proto_sctp|\[.*nf_conntrack_proto_sctp' "$a" >/dev/null && bad "nf_conntrack_proto_sctp not loaded" || ok "nf_conntrack_proto_sctp not loaded"
tpl="$a/roles/firewall/templates/neoncore-guard.nft.j2"
for pat in 'table inet neoncore_guard' 'priority -150' 'ct state invalid drop' 'ct state established,related accept' 'counter drop' 'lab_admin_cidr'; do
    grep -q "$pat" "$tpl" && ok "nft template has: $pat" || bad "nft template has: $pat"
done
grep -q 'Before=network-pre.target docker.service k3s.service' "$a/roles/firewall/templates/neoncore-guard.service.j2" && ok "unit ordering" || bad "unit ordering"
# order in the firewall tasks: arm revert < apply < new ssh < cancel < enable
f="$a/roles/firewall/tasks/main.yml"
l() { grep -n "$1" "$f" | head -1 | cut -d: -f1; }
[ "$(l 'Arm the auto-revert')" -lt "$(l 'Apply the guard table')" ] && [ "$(l 'Apply the guard table')" -lt "$(l 'A NEW ssh')" ] \
  && [ "$(l 'A NEW ssh')" -lt "$(l 'Cancel the revert')" ] && [ "$(l 'Cancel the revert')" -lt "$(l 'Enable the unit')" ] && ok "revert armed first, cancelled after a new ssh, unit enabled last" || bad "task order"
grep -q 'on-active=120' "$f" && ok "120 s revert" || bad "120 s revert"
grep -rEq 'k3s_exec: "--docker --disable=traefik --disable=servicelb"' "$a/roles/k3s/defaults/main.yml" && ok "k3s flags unchanged" || bad "k3s flags unchanged"
grep -q 'checksum: "sha256:' "$a/roles/k3s/tasks/main.yml" && ok "k3s install script checksum-pinned" || bad "k3s checksum"
grep -rq 'no_log: true' "$a/roles/k3s/tasks/main.yml" && ok "no_log on kubeconfig tasks" || bad "no_log kubeconfig"
# evidence idempotency (E5): the nft listing carries live counters, which must be normalised
rd2="$(mktemp -d)"
r1='table inet neoncore_guard { chain prerouting { counter packets 5 bytes 300 drop } }'
r2='table inet neoncore_guard { chain prerouting { counter packets 912 bytes 70311 drop } }'
r3='table inet neoncore_guard { chain prerouting { counter packets 912 bytes 70311 accept } }'
render() { ANSIBLE_CONFIG="$a/ansible.cfg" ansible localhost -c local -m copy -a "dest=$rd2/$2 mode=0600 content='{{ s | regex_replace(guard_counter_re, \"counter packets N bytes N\") }}'" -e "@$a/roles/firewall/defaults/main.yml" -e "s='$1'" 2>/dev/null | grep -o '"changed": [a-z]*' | head -1; }
grep -q "regex_replace(guard_counter_re" "$a/roles/firewall/tasks/main.yml" && ok "firewall evidence normalises counters" || bad "firewall evidence normalises counters"
render "$r1" e >/dev/null; [ "$(render "$r2" e)" = '"changed": false' ] && ok "evidence unchanged when only counters differ" || bad "evidence unchanged when only counters differ"
[ "$(render "$r3" e)" = '"changed": true' ] && ok "evidence changes when the ruleset differs" || bad "evidence changes when the ruleset differs"
rm -rf "$rd2"
# the sshd -T evidence is stable text (no counters, no timestamps): it must not be normalised away or forced
grep -A6 'Keep sshd -T evidence' "$a/roles/base/tasks/main.yml" | grep -q 'content: "{{ sshd_effective.stdout }}' && ok "sshd -T evidence is the plain stable text" || bad "sshd -T evidence"
# wrapper refuses verbose/diff before doing anything else
for flag in -v --diff -vvv; do
    "$lib/ansible.sh" site.yml $flag >/dev/null 2>&1 && bad "ansible.sh rejects $flag" || ok "ansible.sh rejects $flag"
done
for flag in -vD -e --extra-vars --ssh-common-args=-oProxyCommand=x --ssh-extra-args=x -i --inventory -m --become-user --private-key --connection --limit -l --start-at-task "-e x=1" "--tags nosuch" "--tags base,nosuch" "--tags=nosuch" "--tags" "--tags ''" "-t base;id"; do
    "$lib/ansible.sh" site.yml $flag >/dev/null 2>&1 && bad "ansible.sh rejects $flag" || ok "ansible.sh rejects $flag"
done
# allowed forms get past argument parsing; they then stop at the missing env (rc!=0 but a different message)
for flag in "--check" "--tags base" "--tags=base,firewall" "-t k3s --check"; do
    out="$(env -i PATH="$PATH" "$lib/ansible.sh" site.yml $flag 2>&1)"
    echo "$out" | grep -q 'is not set' && ok "ansible.sh accepts $flag" || bad "ansible.sh accepts $flag ($out)"
done
grep -v '^ *#' "$lib/ansible.sh" "$lib/pve_snapshot.sh" | grep -Eq '(^|[^a-z])set -[a-z]*x' && bad "no set -x" || ok "no set -x"
# snapshot helper only creates
grep -v '^ *#' "$lib/pve_snapshot.sh" | grep -Eq 'rollback|DELETE|"PUT"' && bad "snapshot helper cannot rollback/delete" || ok "snapshot helper cannot rollback/delete"
# upf_image: repo Dockerfile untouched; the role adds exactly one RUN, right after the builder FROM
df="$here/../../phase2/upf-metrics-patch/Dockerfile"
git -C "$here/../.." diff --quiet HEAD -- phase2/upf-metrics-patch && ! grep -q 'archive.debian.org' "$df" && ok "repo UPF Dockerfile untouched" || bad "repo UPF Dockerfile untouched"
rd="$(mktemp -d)"
ANSIBLE_CONFIG="$a/ansible.cfg" ansible localhost -c local -m template -a "src=$a/roles/upf_image/templates/Dockerfile.j2 dest=$rd/Dockerfile" \
    -e "@$a/roles/upf_image/defaults/main.yml" -e "upf_image_src=$here/../../phase2/upf-metrics-patch" >/dev/null 2>&1
d="$(diff "$df" "$rd/Dockerfile" | grep -c '^[<>]')"
[ "$d" = 1 ] && [ "$(diff "$df" "$rd/Dockerfile" | grep '^>' | grep -c 'archive.debian.org')" = 1 ] && ok "rewrite adds one line" || bad "rewrite adds one line (diff lines: $d)"
ln="$(grep -n '^RUN .*archive.debian.org' "$rd/Dockerfile" | cut -d: -f1)"; b="$(grep -n '^FROM debian:bullseye AS builder' "$rd/Dockerfile" | cut -d: -f1)"; g="$(grep -n '^FROM gradiant' "$rd/Dockerfile" | cut -d: -f1)"
[ -n "$ln" ] && [ "$ln" = "$((b + 1))" ] && [ "$ln" -lt "$g" ] && ok "rewrite is in the builder stage only" || bad "rewrite is in the builder stage only"
grep -q 'apt-get upgrade -y' "$rd/Dockerfile" && ok "apt-get upgrade kept" || bad "apt-get upgrade kept"
rm -rf "$rd"
exit $fail
