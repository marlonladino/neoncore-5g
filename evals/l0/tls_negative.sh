#!/usr/bin/env bash
# E10: the TLS pin aborts on a wrong fingerprint, and the token never appears in argv
# (plan section 8, E10; security review S-B3, S-B4).
#
#   evals/l0/tls_negative.sh --scratch DIR [--out-dir DIR]   (out default: project/reports/L0/eval/tls)
#
# Negative: strace -f -e trace=execve -o <scratch>/neg.trace scripts/labenv infra/lab.sh status --selftest-bad-pin
# Positive: the same command without the flag.
# The raw traces and stdout/stderr live only in the scratch dir (outside the repo) and are
# deleted at the end. Nothing from the command's own output is written to the repo: only
# exit codes, counts, yes/no flags and the execve program basenames.
# Recorded per run: exit code; count of "PVEAPIToken" in the trace, in stdout and in stderr;
# whether the output names a fingerprint mismatch (yes/no); whether any fingerprint-like hex
# string (>= 32 hex digits, with or without colons) appears in the output (yes/no); the
# ordered execve basenames; terraform/curl execve counts.
# Pass (negative): exit != 0; mismatch named = yes; fingerprint-like string = no;
#   0 terraform and 0 curl execve anywhere in the trace (the pin check runs first, the
#   cert fetch uses openssl s_client, so any curl/terraform execve would come after it);
#   PVEAPIToken count 0.
# Pass (positive): exit 0; PVEAPIToken count 0.
# Exit: 0 both pass, 1 any fail, 2 usage or tool error.
set -euo pipefail
umask 077

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
scratch="" out_dir="$repo/project/reports/L0/eval/tls"
while [ $# -gt 0 ]; do
    case "$1" in
        --scratch) scratch="$2"; shift 2 ;;
        --out-dir) out_dir="$2"; shift 2 ;;
        *) echo "tls_negative: unknown argument" >&2; exit 2 ;;
    esac
done
[ -n "$scratch" ] || { echo "usage: tls_negative.sh --scratch DIR" >&2; exit 2; }
case "$(realpath -m "$scratch")/" in "$repo"/*) echo "tls_negative: scratch must be outside the repo" >&2; exit 2 ;; esac
command -v strace >/dev/null || { echo "tls_negative: strace missing" >&2; exit 2; }
[ -x "$repo/infra/lab.sh" ] || { echo "tls_negative: infra/lab.sh not present (T2/T7 not built)" >&2; exit 2; }
mkdir -p "$scratch" "$out_dir"
work="$(mktemp -d "$scratch/tls-XXXXXX")"
trap 'rm -rf "$work"' EXIT

run_one() {  # $1 = neg|pos
    local tag="$1" rc
    local args=(status)
    [ "$tag" = neg ] && args+=(--selftest-bad-pin)
    set +e
    (cd "$repo" && strace -f -e trace=execve -o "$work/$tag.trace" \
        scripts/labenv infra/lab.sh "${args[@]}" > "$work/$tag.out" 2> "$work/$tag.err")
    rc=$?
    set -e
    echo "$rc" > "$work/$tag.rc"
}

run_one neg
run_one pos

# This summary step runs outside the lab env (only the measured command loads it), and
# what it writes is exit codes, counts, yes/no flags and program basenames. No site value
# can occur there, so the no-site-values opt-in of common.site_values() is explicit here.
L0_ALLOW_NO_SITE_VALUES=1 python3 -I - "$here" "$work" "$out_dir" <<'PY'
import os, re, sys
here, work, out_dir = sys.argv[1:4]
sys.path.insert(0, here)
import common

FP_RE = re.compile(r"(?i)\b(?:[0-9a-f]{2}:){15,}[0-9a-f]{2}\b|\b[0-9a-f]{32,}\b")
EXEC_RE = re.compile(r'execve\("([^"]+)"')

def read(p):
    try:
        return open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""

def summarise(tag):
    tr, out, err = (read(os.path.join(work, f"{tag}.{x}")) for x in ("trace", "out", "err"))
    rc = int(read(os.path.join(work, f"{tag}.rc")).strip() or "-1")
    progs = []
    for line in tr.splitlines():
        if "= -1 " in line:     # failed execve (PATH search misses) are not executions
            continue
        m = EXEC_RE.search(line)
        if m:
            progs.append(os.path.basename(m.group(1)))
    both = out + "\n" + err
    return {
        "exit_code": rc,
        "PVEAPIToken_count_trace": tr.count("PVEAPIToken"),
        "PVEAPIToken_count_stdout": out.count("PVEAPIToken"),
        "PVEAPIToken_count_stderr": err.count("PVEAPIToken"),
        "names_fingerprint_mismatch": bool(re.search(r"(?i)fingerprint", both) and re.search(r"(?i)mismatch|does not match|differs", both)),
        "fingerprint_like_string_in_output": bool(FP_RE.search(both)),
        "execve_programs": progs,
        "terraform_execve": sum(1 for p in progs if p == "terraform"),
        "curl_execve": sum(1 for p in progs if p == "curl"),
        "trace_lines": len(tr.splitlines()),
    }

neg, pos = summarise("neg"), summarise("pos")
nf = []
if neg["exit_code"] == 0: nf.append("negative run exited 0")
if not neg["names_fingerprint_mismatch"]: nf.append("abort message does not name a fingerprint mismatch")
if neg["fingerprint_like_string_in_output"]: nf.append("a fingerprint-like string was printed")
if neg["terraform_execve"] or neg["curl_execve"]: nf.append("terraform/curl execve in the negative run")
if neg["PVEAPIToken_count_trace"] or neg["PVEAPIToken_count_stdout"] or neg["PVEAPIToken_count_stderr"]:
    nf.append("PVEAPIToken found in the negative trace or output")
if neg["trace_lines"] == 0: nf.append("empty negative trace (strace did not run?)")
pf = []
if pos["exit_code"] != 0: pf.append(f"positive run exited {pos['exit_code']}")
if pos["PVEAPIToken_count_trace"] or pos["PVEAPIToken_count_stdout"] or pos["PVEAPIToken_count_stderr"]:
    pf.append("PVEAPIToken found in the positive trace or output")
if pos["trace_lines"] == 0: pf.append("empty positive trace")
prov = common.git_provenance()
def render(name, s, fails):
    lines = [f"# E10 {name}, commit {prov.get('git_sha')}, clean={prov.get('git_clean')}",
             f"result: {'FAIL' if fails else 'PASS'}"]
    lines += [f"  FAIL: {f}" for f in fails]
    for k, v in s.items():
        if k != "execve_programs":
            lines.append(f"{k}: {v}")
    lines.append("execve_programs (basenames, in order): " + " ".join(s["execve_programs"]))
    return "\n".join(lines) + "\n"
common.write_text(os.path.join(out_dir, "negative.txt"), render("negative (--selftest-bad-pin)", neg, nf))
common.write_text(os.path.join(out_dir, "positive.txt"), render("positive", pos, pf))
print(f"E10 negative {'FAIL' if nf else 'PASS'}, positive {'FAIL' if pf else 'PASS'}")
for f in nf + pf:
    print("  " + f)
sys.exit(1 if nf or pf else 0)
PY
