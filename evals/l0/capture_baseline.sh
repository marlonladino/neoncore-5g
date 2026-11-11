#!/usr/bin/env bash
# T3b: capture the infrastructure baseline B from the running old lab (plan section 8,
# "1. Infrastructure baseline B"), or (versions mode) the C4 version file for a run.
#
#   evals/l0/capture_baseline.sh capture --scratch DIR --runner owner|evaluator [--on-node]
#                                        [--out-dir DIR] [--prom kube|nodeport|URL] [--grafana kube|nodeport|URL]
#   evals/l0/capture_baseline.sh versions --out-dir DIR [--on-node]
#
# Who runs it is decision D14: (a) the owner on the old lab node itself (use --on-node,
# which adds lsmod and node MTU), or (b) the evaluator from the control machine with read
# access to the old kubeconfig (KUBECONFIG). Never run before D14 is decided.
# Read-only except the phase6 suite, which provisions/deprovisions only its reserved test
# IMSIs (99970000000990x).
#
# Writes (DIR default project/reports/L0/eval/baseline), every file through redact.py
# steps 2-4 plus this machine's hostname (step 1). Extra values to redact can be added with
# REDACT_EXTRA_VALUES=a,b in the environment (only adds, never removes):
#   B1 pods.json workloads.json kube-system-pods.json (informational)
#   B2 ping-{1,2,3}.txt ping-n3.json ping-gtpu.json
#   B3 suite-{1,2,3}.log pcaps/ (git-ignored) pcap-summary.json (needs tshark; else marked pending)
#   B4 prom-series.json prom-targets.json grafana-dashboard.json
#   B5 versions.txt     B6 timing.json      README.md SHA256SUMS
# A failing step is recorded as it is (B degraded) and the capture continues.
# Exit: 0 every step ran, 1 a step failed (recorded), 2 usage error.
set -uo pipefail
umask 077

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
mode="${1:-}"; shift || true
out_dir="$repo/project/reports/L0/eval/baseline" scratch="" runner="" on_node=0 prom="kube" grafana="kube"
while [ $# -gt 0 ]; do
    case "$1" in
        --out-dir) out_dir="$2"; shift 2 ;;
        --scratch) scratch="$2"; shift 2 ;;
        --runner) runner="$2"; shift 2 ;;
        --on-node) on_node=1; shift ;;
        --prom) prom="$2"; shift 2 ;;
        --grafana) grafana="$2"; shift 2 ;;
        *) echo "capture_baseline: unknown argument" >&2; exit 2 ;;
    esac
done

py() { python3 -I "$@"; }
red() { py "$here/redact.py" --allow-no-site-values "$@"; }   # stdin -> redacted file
failed_steps=()
step() {  # step NAME CMD...  (records failure, continues)
    local name="$1"; shift
    echo "[baseline] $name"
    if ! "$@"; then failed_steps+=("$name"); echo "[baseline] $name FAILED (recorded)"; fi
}

first_line() { head -n 1 | tr -d '\r'; }

versions() {  # $1 = out dir
    local d="$1" v
    {
        v="$(kubectl version -o json 2>/dev/null | py -c 'import json,sys; print(json.load(sys.stdin)["serverVersion"]["gitVersion"])' 2>/dev/null)"
        echo "kubernetes_server: ${v:-unavailable}"
        if [ "$on_node" = 1 ] && command -v k3s >/dev/null; then
            echo "k3s_cli: $(k3s --version 2>/dev/null | first_line)"
        else
            echo "k3s_cli: not captured (not on node)"
        fi
        echo "open5gs_upfd: $(kubectl -n neoncore exec deploy/upf -c upf -- open5gs-upfd -v 2>&1 | first_line)"
        echo "ueransim: $(kubectl -n neoncore exec deploy/gnb -- nr-gnb --version 2>&1 | first_line)"
        echo "netshoot_imageID: $(kubectl -n neoncore get pod -l app=tracer -o jsonpath='{.items[0].status.containerStatuses[0].imageID}' 2>/dev/null)"
        if [ "$on_node" = 1 ]; then
            for m in sctp macvlan ipvlan iptable_nat; do
                if lsmod | awk '{print $1}' | grep -qx "$m"; then echo "lsmod_$m: loaded"
                elif [ -d "/sys/module/$m" ]; then echo "lsmod_$m: built-in"
                else echo "lsmod_$m: absent"; fi
            done
            local dev; dev="$(ip -o route show default 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="dev"){print $(i+1); exit}}')"
            echo "mtu_node_nic: $( [ -n "$dev" ] && cat "/sys/class/net/$dev/mtu" 2>/dev/null || echo unavailable)"
            for i in flannel.1 cni0; do echo "mtu_$i: $(cat "/sys/class/net/$i/mtu" 2>/dev/null || echo absent)"; done
        else
            echo "lsmod: not captured (not on node)"
            echo "mtu_node_nic: not captured (not on node)"
        fi
        echo "mtu_uesimtun0: $(kubectl -n neoncore exec deploy/ue -- cat /sys/class/net/uesimtun0/mtu 2>/dev/null | first_line)"
        bash "$here/mtu_check.sh" --lines --label "versions (TB6, informational)"   # pod eth0/ogstun/uesimtun0
        echo "pmtu_1372_ping: $(kubectl -n neoncore exec deploy/ue -- ping -M do -s 1372 -I uesimtun0 -c 3 -W 2 8.8.8.8 2>&1 | grep -E 'packets transmitted' | first_line)"
        echo "kubectl_client: $(kubectl version --client -o json 2>/dev/null | py -c 'import json,sys; print(json.load(sys.stdin)["clientVersion"]["gitVersion"])' 2>/dev/null)"
        echo "tshark: $(command -v tshark >/dev/null && tshark --version 2>/dev/null | first_line || echo 'not installed')"
        echo "python3: $(python3 --version 2>&1)"
    } | red --format text -o "$d/versions.txt"
}

if [ "$mode" = versions ]; then
    [ -n "$out_dir" ] || exit 2
    mkdir -p "$out_dir"
    versions "$out_dir" || exit 1
    exit 0
fi
[ "$mode" = capture ] || { echo "usage: capture_baseline.sh capture|versions ..." >&2; exit 2; }
[ -n "$scratch" ] || { echo "capture_baseline: --scratch DIR required (raw output stays there)" >&2; exit 2; }
case "$runner" in owner|evaluator) ;; *) echo "capture_baseline: --runner owner|evaluator (D14)" >&2; exit 2 ;; esac
case "$(realpath -m "$scratch")/" in "$repo"/*) echo "capture_baseline: scratch must be outside the repo" >&2; exit 2 ;; esac
command -v kubectl >/dev/null || { echo "capture_baseline: kubectl missing" >&2; exit 2; }
mkdir -p "$scratch" "$out_dir/pcaps"
work="$(mktemp -d "$scratch/baseline-XXXXXX")"
t_begin="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ---- B1
b1() {
    py "$here/pods_check.py" snapshot --out "$out_dir/pods.json" &&
    py "$here/pods_check.py" workloads --in "$out_dir/pods.json" --out "$out_dir/workloads.json" &&
    py "$here/pods_check.py" snapshot --namespaces kube-system --out "$out_dir/kube-system-pods.json"
}
step "B1 pods/workloads" b1

# ---- B2
for k in 1 2 3; do
    step "B2 ping $k" bash "$here/ping_check.sh" --out-dir "$out_dir" --k "$k" --scratch "$work" --prom "$prom"
done

# ---- B3
suite() {  # $1 = k
    local k="$1" before after rc
    before="$(ls -1 "$repo/traces/scenario-runs" 2>/dev/null | sort)"
    ( cd "$repo" && python3 -m phase6.tests.run_scenarios 2>&1; echo "[baseline] runner exit $?" ) \
        | while IFS= read -r l; do printf '%s %s\n' "$(date +%s.%N)" "$l"; done > "$work/suite-$k.log"
    red --format text -o "$out_dir/suite-$k.log" < "$work/suite-$k.log" || return 1
    after="$(ls -1 "$repo/traces/scenario-runs" 2>/dev/null | sort)"
    comm -13 <(printf '%s\n' "$before") <(printf '%s\n' "$after") | grep -E '^scenario-[a-z-]+-[0-9]{9,10}-[0-9]{8}-[0-9]{6}\.pcap$' \
        | while IFS= read -r f; do cp -p "$repo/traces/scenario-runs/$f" "$out_dir/pcaps/$f"; done
    grep -q '\[suite\] all scenarios passed' "$work/suite-$k.log"
}
for k in 1 2 3; do step "B3 suite $k" suite "$k"; done
pcap_summary() {
    if ! command -v tshark >/dev/null; then
        printf '{"status":"pending: tshark not available here; run pcap_check.py check on the control machine (same tshark as the runs)"}\n' \
            | red --format json -o "$out_dir/pcap-summary.json"
        return 0
    fi
    shopt -s nullglob
    local files=("$out_dir"/pcaps/*.pcap)
    [ ${#files[@]} -gt 0 ] || return 1
    py "$here/pcap_check.py" check --out "$out_dir/pcap-summary.json" "${files[@]}"
}
step "B3 pcap summary" pcap_summary

# ---- B4
step "B4 prometheus series" py "$here/prom_check.py" series --prom "$prom" --grafana "$grafana" --out-dir "$out_dir"

# ---- B5
step "B5 versions" versions "$out_dir"

# ---- B6
timing() {
    py - "$here" "$work" "$out_dir" <<'PY'
import json, os, re, sys
here, work, out_dir = sys.argv[1:4]
sys.path.insert(0, here)
import common
durs = []
for k in (1, 2, 3):
    p = os.path.join(work, f"suite-{k}.log")
    if not os.path.isfile(p):
        continue
    start = {}
    for line in open(p, encoding="utf-8", errors="replace"):
        m = re.match(r"^(\d+\.\d+) (.*)$", line.rstrip("\n"))
        if not m:
            continue
        t, msg = float(m.group(1)), m.group(2)
        a = re.match(r"^\[suite\] --- running ([a-z-]+) ---$", msg)
        b = re.match(r"^\[suite\] (PASS|FAIL)\s+([a-z-]+)\s", msg + " ")
        if a:
            start[a.group(1)] = t
        elif b and b.group(2) in start:
            durs.append({"suite": k, "scenario": b.group(2), "status": b.group(1),
                         "duration_s": round(t - start.pop(b.group(2)), 3)})
rtts = []
pn = os.path.join(out_dir, "ping-n3.json")
if os.path.isfile(pn):
    for r in json.load(open(pn)).get("runs", []):
        rtts.append(r.get("rtt_ms", {}))
ds = [d["duration_s"] for d in durs]
out = {"scenarios": durs,
       "scenario_duration_p50_s": common.percentile(ds, 0.5), "scenario_duration_p95_s": common.percentile(ds, 0.95),
       "ping_rtt_per_run": rtts,
       "ping_rtt_p50_ms": common.percentile([r.get("p50") for r in rtts], 0.5),
       "ping_rtt_p95_ms": common.percentile([r.get("p95") for r in rtts], 0.95),
       "percentile_method": "nearest rank; ping p50/p95 across runs are over per-run values"}
common.write_json(os.path.join(out_dir, "timing.json"), out)
PY
}
step "B6 timing" timing

# ---- README + SHA256SUMS
t_end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
{
    echo "# Baseline B (T3b)"
    echo
    echo "- Runner role: \`$runner\` (D14), on node: \`$on_node\`"
    echo "- Started: \`$t_begin\`, ended: \`$t_end\`"
    echo "- Git SHA: \`$(git -C "$repo" rev-parse HEAD 2>/dev/null)\`, porcelain lines: \`$(git -C "$repo" status --porcelain 2>/dev/null | wc -l)\`"
    echo "- Tool versions: see \`versions.txt\`"
    echo "- Failed steps (B degraded, recorded as they are): ${failed_steps[*]:-none}"
    echo "- Pcaps under \`pcaps/\` stay local and uncommitted; their sha256 is in \`SHA256SUMS\`."
} | red --format text -o "$out_dir/README.md"
(
    cd "$out_dir" && find . -type f ! -name SHA256SUMS ! -name '.*' -print0 | sort -z | xargs -0 sha256sum
) | red --format text -o "$out_dir/SHA256SUMS"

echo "[baseline] done; failed steps: ${failed_steps[*]:-none}"
[ ${#failed_steps[@]} -eq 0 ]
