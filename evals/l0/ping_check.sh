#!/usr/bin/env bash
# E2 / B2: UE ping through uesimtun0 with N3 counter deltas and GTP-U evidence
# (plan section 8, E2). One invocation = one run k.
#
#   evals/l0/ping_check.sh --out-dir DIR --k K --scratch DIR [--prom nodeport|kube|URL] [--no-gtpu]
#                          [--pmtu]
#   evals/l0/ping_check.sh --tracer-check-only     (print the tracer freshness status, exit 0)
#
# Tracer freshness (telco TB5): right before the ping, the tracer's newest pcap must have
# been written within TRACER_MAX_AGE_S = 30 s (pod clock vs file mtime, both read inside
# the tracer pod). If it was not, or if after the ping the newest file is still older
# than the ping start, the [B] GTP-U item is "not tested: tracer stale (...)" and no
# frame count is reported. R1 (2026-11-10) counted a stale file as "tested, 0 frames".
# --pmtu adds one informational `ping -M do -s 1372 -I uesimtun0 -c 3 -W 2 8.8.8.8`
# (telco TB6, no threshold) after the run, recorded as ping-pmtu-<k>.txt and in
# ping-n3.json under "pmtu_informational"; it never changes the result.
#
# Steps: wait 25 s (>= 2 scrape intervals of 10 s), read N3 counters, run
#   kubectl -n neoncore exec deploy/ue -- ping -I uesimtun0 -c 20 -W 2 8.8.8.8
# wait 25 s, read N3 counters again, then copy the tracer's newest pcap into the
# scratch dir and count `gtp && icmp` frames inside the ping window (needs tshark).
# Raw output stays in the scratch dir; only redacted results are written to DIR:
#   ping-<k>.txt, ping-n3.json (one entry per k, with the E2 window for E4),
#   ping-gtpu.json (one entry per k).
# Thresholds: >= 18/20 replies; indatapktn3upf delta >= 20; outdatapktn3upf delta
# >= replies received. [B] gtp && icmp frames > 0 (required only if B shows them).
# Exit: 0 PASS, 1 FAIL, 2 usage or tool error.
set -euo pipefail
umask 077

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out_dir="" k="" scratch="" prom="kube" gtpu=1 pmtu=0 check_only=0
TRACER_MAX_AGE_S=30
while [ $# -gt 0 ]; do
    case "$1" in
        --out-dir) out_dir="$2"; shift 2 ;;
        --k) k="$2"; shift 2 ;;
        --scratch) scratch="$2"; shift 2 ;;
        --prom) prom="$2"; shift 2 ;;
        --no-gtpu) gtpu=0; shift ;;
        --pmtu) pmtu=1; shift ;;
        --tracer-check-only) check_only=1; shift ;;
        *) echo "ping_check: unknown argument" >&2; exit 2 ;;
    esac
done
# Tracer file pick: newest mtime first; equal mtimes are broken by the greatest (newest)
# file name, so the choice is deterministic (`ls -t` alone is not). Runs inside the
# tracer pod (busybox sh/stat/sort) with the directory as $1; test_shell.py runs the
# same text locally.
PICK_NEWEST='for f in "$1"/neoncore-*.pcap*; do [ -f "$f" ] && stat -c "%Y %n" "$f"; done 2>/dev/null | sort -k1,1nr -k2,2r | head -n 1 | cut -d" " -f2-'
# Pod clock and the file's mtime, both read in the tracer pod ($1 = validated file name).
TRACER_TIMES='echo "$(date +%s) $(stat -c %Y "$1")"'
NAME_RE='^/pcaps/neoncore-[0-9]{8}-[0-9]{6}\.pcap[0-9]*(\.gz)?$'

tracer="" newest="" tr_now="" tr_mtime="" probe=""
# tracer_probe: sets tracer/newest/tr_now/tr_mtime and probe ("" = fresh, else a
# "not tested: ..." status). Called directly, never in $( ), so the globals survive.
tracer_probe() {
    probe="" tr_now="" tr_mtime=""
    tracer="$(kubectl -n neoncore get pod -l app=tracer -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)" || tracer=""
    [[ "$tracer" =~ ^tracer-[a-z0-9-]+$ ]] || { probe="not tested: tracer pod not recognised"; return 0; }
    newest="$(kubectl -n neoncore exec "$tracer" -- sh -c "$PICK_NEWEST" sh /pcaps 2>/dev/null | tr -d '\r')" || newest=""
    [[ "$newest" =~ $NAME_RE ]] || { probe="not tested: tracer pcap name not recognised"; return 0; }
    local t
    t="$(kubectl -n neoncore exec "$tracer" -- sh -c "$TRACER_TIMES" sh "$newest" 2>/dev/null | tr -d '\r')" || t=""
    [[ "$t" =~ ^([0-9]+)\ ([0-9]+)$ ]] || { probe="not tested: tracer file time unreadable"; return 0; }
    tr_now="${BASH_REMATCH[1]}" tr_mtime="${BASH_REMATCH[2]}"
    local age=$(( tr_now - tr_mtime ))
    if [ "$age" -gt "$TRACER_MAX_AGE_S" ]; then
        probe="not tested: tracer stale (last write $(date -u -d "@$tr_mtime" +%Y-%m-%dT%H:%M:%SZ), ${age} s before the run, limit ${TRACER_MAX_AGE_S} s)"
    fi
}

if [ "$check_only" = 1 ]; then
    tracer_probe
    echo "tracer: ${probe:-fresh}"
    exit 0
fi
[ -n "$out_dir" ] && [ -n "$k" ] && [ -n "$scratch" ] || { echo "usage: ping_check.sh --out-dir DIR --k K --scratch DIR" >&2; exit 2; }
[[ "$k" =~ ^[0-9]{1,3}$ ]] || { echo "ping_check: --k must be a number" >&2; exit 2; }
repo="$(cd "$here/../.." && pwd)"
case "$(realpath -m "$scratch")/" in "$repo"/*) echo "ping_check: scratch must be outside the repo" >&2; exit 2 ;; esac
mkdir -p "$scratch" "$out_dir"
work="$(mktemp -d "$scratch/ping-$k-XXXXXX")"

py() { python3 -I "$@"; }


sleep 25
py "$here/prom_check.py" n3 --prom "$prom" > "$work/n3-before.json"
pre_stale=""
if [ "$gtpu" = 1 ]; then tracer_probe; pre_stale="$probe"; fi
t_start="$(date +%s.%N)"
set +e
kubectl -n neoncore exec deploy/ue -- ping -I uesimtun0 -c 20 -W 2 8.8.8.8 > "$work/ping.txt" 2>&1
ping_rc=$?
set -e
t_end="$(date +%s.%N)"
sleep 25
py "$here/prom_check.py" n3 --prom "$prom" > "$work/n3-after.json"

pmtu_rc=""
if [ "$pmtu" = 1 ]; then
    set +e
    kubectl -n neoncore exec deploy/ue -- ping -M do -s 1372 -I uesimtun0 -c 3 -W 2 8.8.8.8 > "$work/pmtu.txt" 2>&1
    pmtu_rc=$?
    set -e
fi

gtpu_status="not tested: --no-gtpu"
if [ "$gtpu" = 1 ]; then
    if [ -n "$pre_stale" ]; then
        gtpu_status="$pre_stale"
    elif ! command -v tshark >/dev/null 2>&1; then
        gtpu_status="not tested: tshark missing"
    else
        tracer_probe
        if [[ "$probe" == "not tested: tracer pod"* || "$probe" == "not tested: tracer pcap name"* || "$probe" == "not tested: tracer file time"* ]]; then
            gtpu_status="$probe"
        elif [ "$tr_mtime" -lt "${t_start%.*}" ]; then
            gtpu_status="not tested: tracer stale (newest file last written $(date -u -d "@$tr_mtime" +%Y-%m-%dT%H:%M:%SZ), before the ping start)"
        else
            local_pcap="$work/$(basename "$newest")"
            kubectl -n neoncore cp "$tracer:$newest" "$local_pcap" >/dev/null 2>&1 || true
            if [ -s "$local_pcap" ]; then
                py "$here/pcap_check.py" gtpu --start "$t_start" --end "$t_end" "$local_pcap" > "$work/gtpu.json" || true
                gtpu_status="tested"
            else
                gtpu_status="not tested: tracer pcap copy failed"
            fi
        fi
    fi
fi

py - "$here" "$work" "$out_dir" "$k" "$ping_rc" "$t_start" "$t_end" "$gtpu_status" "$pmtu_rc" "$tr_mtime" <<'PY'
import json, os, re, sys
here, work, out_dir, k, ping_rc, t0, t1, gstat, pmtu_rc, tr_mtime = sys.argv[1:11]
sys.path.insert(0, here)
import common
ping = open(os.path.join(work, "ping.txt"), encoding="utf-8", errors="replace").read()
m = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received", ping)
sent, recv = (int(m.group(1)), int(m.group(2))) if m else (None, 0)
rtts = [float(x) for x in re.findall(r"time=([0-9.]+) ?ms", ping)]
b = json.load(open(os.path.join(work, "n3-before.json")))
a = json.load(open(os.path.join(work, "n3-after.json")))
d_in, d_out = a["in"] - b["in"], a["out"] - b["out"]
fails = []
if recv < 18:
    fails.append(f"{recv}/20 replies < 18")
if sent != 20:
    fails.append(f"ping summary not found or count != 20 (sent={sent})")
if d_in < 20:
    fails.append(f"indatapktn3upf delta {d_in:g} < 20")
if d_out < recv:
    fails.append(f"outdatapktn3upf delta {d_out:g} < replies {recv}")
entry = {"k": int(k), "window": [float(t0), float(t1)], "ping_exit": int(ping_rc), "sent": sent,
         "received": recv, "n3_before": b, "n3_after": a, "n3_in_delta": d_in, "n3_out_delta": d_out,
         "rtt_ms": {"n": len(rtts), "p50": common.percentile(rtts, 0.5), "p95": common.percentile(rtts, 0.95)},
         "result": "FAIL" if fails else "PASS", "failures": fails}
if pmtu_rc != "":
    pm = open(os.path.join(work, "pmtu.txt"), encoding="utf-8", errors="replace").read()
    mm = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received", pm)
    entry["pmtu_informational"] = {
        "command": "ping -M do -s 1372 -I uesimtun0 -c 3 -W 2 8.8.8.8", "exit": int(pmtu_rc),
        "sent": int(mm.group(1)) if mm else None, "received": int(mm.group(2)) if mm else None,
        "loss_line": next((l.strip() for l in pm.splitlines() if "packets transmitted" in l), None),
        "note": "informational, no threshold (telco TB6)"}
    common.write_text(os.path.join(out_dir, f"ping-pmtu-{k}.txt"), pm)
g = {"k": int(k), "status": gstat, "tracer_max_age_s": 30,
     "tracer_last_write_epoch": int(tr_mtime) if tr_mtime.isdigit() else None}
gp = os.path.join(work, "gtpu.json")
if gstat == "tested" and os.path.isfile(gp):  # never merge counts for a stale tracer
    g.update(json.load(open(gp)))
def merge(name, e):
    p = os.path.join(out_dir, name)
    cur = json.load(open(p)) if os.path.isfile(p) else {"runs": []}
    cur["runs"] = [r for r in cur["runs"] if r.get("k") != e["k"]] + [e]
    cur["runs"].sort(key=lambda r: r["k"])
    common.write_json(p, cur)
common.write_text(os.path.join(out_dir, f"ping-{k}.txt"), ping)
merge("ping-n3.json", entry)
merge("ping-gtpu.json", g)
print(f"E2 run {k}: {entry['result']} ({recv}/20, N3 in +{d_in:g}, out +{d_out:g}; GTP-U {gstat})")
for f in fails:
    print("  " + f)
sys.exit(0 if not fails else 1)
PY
