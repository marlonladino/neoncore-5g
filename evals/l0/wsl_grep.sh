#!/usr/bin/env bash
# E6(a) static check: no dependency on the old host OS in tracked files (plan section 8, E6).
#
#   evals/l0/<this script> [--out-dir DIR]   (DIR default: project/reports/L0/eval/<old-host dir>,
#   the evidence folder named in plan section 6; the name is built below from two parts)
#
# Runs git grep -n -I -i -E with the plan's pattern over tracked files. The pattern is
# written with one-character bracket expressions (equivalent regex) so this file and the
# other evaluator files never match it themselves.
# Classes:
#   FAIL     executables and config: *.sh *.py *.yaml *.yml *.tf *.cfg, any file with a
#            shebang or the exec bit, infra/** scripts/** start.sh stop.sh phase*/**;
#            README.md outside the first heading whose title contains "History"
#   ALLOWED  DEVLOG.md project/** .claude/** docs/roadmap/** the migration post under
#            site/ (a .md/.mdx file whose name contains "proxmox"), README History section
#   OTHER    anything else: listed, not failed (E6(a) sets no threshold for it)
# Allowed paths take precedence; an allowed file that is also executable/config is
# marked "(allowed, executable)" so it stays visible.
# Writes grep.txt (FAIL + OTHER hits), allowlist-hits.txt, static.json, via redact.py.
# Exit: 0 PASS (zero FAIL hits), 1 FAIL, 2 error.
set -euo pipefail
umask 077

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
me="$(basename "$0" .sh)"
out_dir="$repo/project/reports/L0/eval/w""sl"
usage() { echo "usage: evals/l0/$me.sh [--out-dir DIR]   (-h|--help: this text, writes nothing)"; }
# Strict argument parsing before any work: --help and unknown arguments never write.
case "$#:${1:-}" in
    0:) ;;
    1:-h|1:--help) usage; exit 0 ;;
    2:--out-dir) [ -n "$2" ] || { usage >&2; exit 2; }; out_dir="$2" ;;
    *) echo "$me: unknown or incomplete arguments" >&2; usage >&2; exit 2 ;;
esac

pattern='w[s]l|w[i]ndows|\.w[s]lconfig|/mnt/[a-z]/|p[o]wershell|\.e[x]e\b'

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

set +e
git -C "$repo" grep -n -I -i -E "$pattern" > "$tmp/hits.txt"
rc=$?
set -e
[ $rc -le 1 ] || { echo "$me: git grep failed" >&2; exit 2; }

# README History section line range (first heading containing "History").
hist_range="$(awk '
    /^#+[ \t]/ {
        lvl = match($0, /[^#]/) - 1
        if (start && !end && lvl <= slvl) { end = NR - 1 }
        if (!start && tolower($0) ~ /history/) { start = NR; slvl = lvl }
    }
    END { if (start && !end) end = NR; print start + 0, end + 0 }' "$repo/README.md" 2>/dev/null || echo "0 0")"
read -r hist_start hist_end <<< "$hist_range"

is_exec_or_config() {
    local f="$1"
    case "$f" in
        *.sh|*.py|*.yaml|*.yml|*.tf|*.cfg|infra/*|scripts/*|start.sh|stop.sh|phase*/*) return 0 ;;
    esac
    local mode
    mode="$(git -C "$repo" ls-files -s -- "$f" | awk '{print $1; exit}')"
    [ "$mode" = "100755" ] && return 0
    [ "$(head -c 2 "$repo/$f" 2>/dev/null)" = "#!" ] && return 0
    return 1
}

is_allowed() {
    local f="$1" line="$2"
    case "$f" in
        DEVLOG.md|project/*|.claude/*|docs/roadmap/*) return 0 ;;
        site/*)
            local b; b="$(basename "$f" | tr '[:upper:]' '[:lower:]')"
            case "$b" in *proxmox*.md|*proxmox*.mdx) return 0 ;; esac ;;
        README.md)
            [ "$hist_start" -gt 0 ] && [ "$line" -ge "$hist_start" ] && [ "$line" -le "$hist_end" ] && return 0 ;;
    esac
    return 1
}

: > "$tmp/fail.txt"; : > "$tmp/allowed.txt"; : > "$tmp/other.txt"
while IFS= read -r hit; do
    f="${hit%%:*}"; rest="${hit#*:}"; line="${rest%%:*}"
    if is_allowed "$f" "$line"; then
        if is_exec_or_config "$f"; then
            printf '%s  (allowed, executable)\n' "$hit" >> "$tmp/allowed.txt"
        else
            printf '%s\n' "$hit" >> "$tmp/allowed.txt"
        fi
    elif is_exec_or_config "$f" || [ "$f" = "README.md" ]; then
        printf '%s\n' "$hit" >> "$tmp/fail.txt"
    else
        printf '%s\n' "$hit" >> "$tmp/other.txt"
    fi
done < "$tmp/hits.txt"

n_fail=$(wc -l < "$tmp/fail.txt"); n_allow=$(wc -l < "$tmp/allowed.txt"); n_other=$(wc -l < "$tmp/other.txt")
sha="$(git -C "$repo" rev-parse HEAD)"
dirty="$(git -C "$repo" status --porcelain | wc -l)"

mkdir -p "$out_dir"
{
    echo "# E6(a) git grep, commit $sha, porcelain lines $dirty"
    echo "# FAIL hits: $n_fail"
    cat "$tmp/fail.txt"
    echo "# OTHER hits (listed, not failed): $n_other"
    cat "$tmp/other.txt"
} | python3 -I "$here/redact.py" --allow-no-site-values --format text -o "$out_dir/grep.txt"
{
    echo "# E6(a) allowed hits, commit $sha"
    cat "$tmp/allowed.txt"
} | python3 -I "$here/redact.py" --allow-no-site-values --format text -o "$out_dir/allowlist-hits.txt"
result=PASS; [ "$n_fail" -eq 0 ] || result=FAIL
printf '{"check":"E6a","git_sha":"%s","porcelain_lines":%d,"fail_hits":%d,"allowed_hits":%d,"other_hits":%d,"readme_history_lines":[%d,%d],"result":"%s"}\n' \
    "$sha" "$dirty" "$n_fail" "$n_allow" "$n_other" "$hist_start" "$hist_end" "$result" \
    | python3 -I "$here/redact.py" --allow-no-site-values --format json -o "$out_dir/static.json"
echo "E6(a) $result: fail=$n_fail allowed=$n_allow other=$n_other"
[ "$result" = PASS ]
