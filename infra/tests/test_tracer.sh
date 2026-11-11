#!/usr/bin/env bash
# Static + local behaviour tests for the tracer manifests (phase4/manifests). No cluster needed.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
m="$here/../../phase4/manifests"
t="$(mktemp -d)"; trap 'rm -rf "$t"' EXIT
fail=0; ok() { echo "ok   $1"; }; bad() { echo "FAIL $1"; fail=1; }
dep="$m/02-tracer.yaml"; cm="$m/01-tracer-configmap.yaml"; sh_="$m/capture.sh"

# configmap script == capture.sh
sed 's/^    //' "$cm" | sed -n '/^#!/,/icmp/p' | diff -q - "$sh_" >/dev/null && ok "configmap script equals capture.sh" || bad "configmap script equals capture.sh"
code="$(grep -v '^ *#' "$sh_")"
echo "$code" | grep -q '^exec tcpdump -i any -n \\$' && ok "tcpdump flags: -i any -n only before -w" || bad "tcpdump head flags"
tcmd="$(awk '/^exec tcpdump/{f=1} f' "$sh_")"
echo "$tcmd" | grep -Eq -- '(^| )-z( |$)' && bad "no -z on tcpdump" || ok "no -z on tcpdump"
echo "$tcmd" | grep -Eq -- '(^| )-Z( |$)' && bad "no -Z on tcpdump" || ok "no -Z on tcpdump"
echo "$tcmd" | grep -Fq -- '-G "$ROTATE_SECONDS" -C "$MAX_FILE_MB"' && ok "rotation flags unchanged" || bad "rotation flags unchanged"
echo "$code" | grep -Fq "'(sctp) or (udp port 8805) or (udp port 2152) or (tcp port 7777) or icmp'" && ok "capture filter unchanged" || bad "capture filter unchanged"
echo "$code" | grep -Fq -- '-w "${PCAP_DIR}/neoncore-%Y%m%d-%H%M%S.pcap"' && ok "output name unchanged" || bad "output name unchanged"
grep -Fq 'image: nicolaka/netshoot@sha256:b09d9b21381f47a79b3cbcb30da25266dc17186ea00ae65e99fdc51396f48e70' "$dep" && ok "tracer image digest pinned (unchanged)" || bad "tracer image digest"
python3 -I - "$dep" <<'PY' && ok "shareProcessNamespace true; livenessProbe exec, 60 s period, threshold 3, initial delay >= 120" || bad "shareProcessNamespace / livenessProbe fields"
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
c = d["spec"]["template"]["spec"]["containers"][0]
p = c["livenessProbe"]
assert d["spec"]["template"]["spec"]["shareProcessNamespace"] is True
assert p["periodSeconds"] == 60 and p["failureThreshold"] == 3 and p["initialDelaySeconds"] >= 120
assert p["exec"]["command"][:2] == ["/bin/sh", "-c"] and "-le 120" in p["exec"]["command"][2]
PY

# probe logic against a temp dir (stat -c %Y and date +%s exist in busybox and GNU)
cmd="$(python3 -I -c "import yaml,sys;print(yaml.safe_load(open('$dep'))['spec']['template']['spec']['containers'][0]['livenessProbe']['exec']['command'][2])")"
probe() { sh -c "${cmd//\/pcaps/$t/p}"; }
mkdir -p "$t/p"
probe && ok "probe passes on an empty directory" || bad "probe passes on an empty directory"
touch "$t/p/neoncore-20260101-000000.pcap"; probe && ok "probe passes on a fresh file" || bad "probe passes on a fresh file"
touch -d '-300 seconds' "$t/p/neoncore-20260101-000000.pcap"; probe && bad "probe fails on a stale newest file" || ok "probe fails on a stale newest file"
touch "$t/p/neoncore-20260101-000500.pcap.gz"; probe && ok "probe counts a fresh .gz as newest" || bad "probe counts fresh .gz"

# housekeeping loop: one iteration run against a temp dir
r="$t/r"; mkdir -p "$r"
loop="$(awk '/^\(/{f=1;next} /^\) &/{f=0} f' "$sh_" | sed -e 's/while true; do/for _once in 1; do/' -e '/sleep 60/d')"
run_loop() { PCAP_DIR="$r" RETENTION_MINUTES=120 sh -c "$loop"; }
mk() { printf '%s' "$2" >"$r/$1"; touch -d "$3" "$r/$1"; }
mk neoncore-20260101-000100.pcap old1 '-30 minutes'
mk neoncore-20260101-000600.pcap old2 '-20 minutes'
mk neoncore-20260101-001100.pcap open '-1 minutes'            # newest: tcpdump has it open
mk neoncore-20260101-000000.pcap.gz ancient '-300 minutes'    # old, already compressed: retention deletes
mk neoncore-20260101-000050.pcap old3 '-300 minutes'          # old and uncompressed: compressed, then deleted by retention
mk scenario-x.pcap other '-300 minutes'
run_loop
[ "$(cat "$r/neoncore-20260101-001100.pcap")" = open ] && [ ! -e "$r/neoncore-20260101-001100.pcap.gz" ] && ok "newest file is never compressed or deleted" || bad "newest file untouched"
[ ! -e "$r/neoncore-20260101-000100.pcap" ] && [ "$(gzip -dc "$r/neoncore-20260101-000100.pcap.gz")" = old1 ] && [ "$(gzip -dc "$r/neoncore-20260101-000600.pcap.gz")" = old2 ] && ok "older files are compressed (content intact) and the original removed" || bad "older files compressed"
[ ! -e "$r/neoncore-20260101-000000.pcap.gz" ] && [ ! -e "$r/scenario-x.pcap" ] && ok "retention deletes files older than 120 min" || bad "retention deletes old files"
ls -A "$r" | grep -q '\.tmp$' && bad "no temp files left" || ok "no temp files left"
# idempotent second run, and the newest stays even when it is idle for 200 min (retention spares it)
run_loop; [ "$(gzip -dc "$r/neoncore-20260101-000100.pcap.gz")" = old1 ] && ok "second run is idempotent" || bad "second run idempotent"
touch -d '-200 minutes' "$r/neoncore-20260101-001100.pcap"; run_loop
[ -e "$r/neoncore-20260101-001100.pcap" ] && ok "retention spares an idle newest (open) capture" || bad "retention spares the open capture"
# a new capture appears after an old one rotated: the previous newest is now compressed
touch -d '-10 minutes' "$r/neoncore-20260101-001100.pcap"; touch "$r/neoncore-20260101-001600.pcap"; run_loop
[ -e "$r/neoncore-20260101-001100.pcap.gz" ] && [ -e "$r/neoncore-20260101-001600.pcap" ] && [ ! -e "$r/neoncore-20260101-001600.pcap.gz" ] && ok "after rotation the previous file is gzipped, the new one is left alone" || bad "rotation handling"
# a failing gzip leaves the original and no temp file
mkdir -p "$t/bin"; printf '#!/bin/sh\nexit 1\n' >"$t/bin/gzip"; chmod +x "$t/bin/gzip"
mk neoncore-20260101-002000.pcap keepme '-10 minutes'; mk neoncore-20260101-002500.pcap newest '-1 minutes'
PATH="$t/bin:$PATH" run_loop
[ "$(cat "$r/neoncore-20260101-002000.pcap")" = keepme ] && ! ls -A "$r" | grep -q '\.tmp$' && ok "failed gzip keeps the original, leaves no temp file" || bad "failed gzip handling"
exit $fail
