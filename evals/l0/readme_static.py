#!/usr/bin/env python3
"""E9(a) static README checks S1-S6 (plan section 8, "5. The 30-second test").

  readme_static.py [--repo DIR] [--out FILE]

S1  top section (title down to the first '## ') has <= 120 words of prose. Not counted:
    image alt text, badge markup, URLs, HTML tags/comments, fenced code blocks.
    Inline code is counted as words. (Reading note: fenced code is not prose.)
S2  the top section embeds docs/media/tui-demo.gif; `file` says "GIF image data"; size
    <= 5 MB (5,000,000 bytes).
S3  a '## Roadmap' section lists W0 L0 7 8 9 10 9B 11 12, each on a line (table row or
    list item) that also carries a status word, and links docs/roadmap/neoncore-roadmap.pdf,
    which exists.
S4  `scripts/labenv infra/lab.sh up` appears verbatim in the top section or the first
    section after it.
S5  docs/github-metadata.md: description <= 350 characters, <= 20 topics, each matching
    ^[a-z0-9][a-z0-9-]{0,49}$. Applied on GitHub: not tested here (after T15b, owner).
S6  every relative link and image in README.md resolves to a tracked file (a link to a
    directory passes if it holds tracked files; reported as such).

Exit codes: 0 S1-S4, S5 and S6 pass; 1 any fails; 2 usage error.
"""
import argparse
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import common  # noqa: E402

GIF = "docs/media/tui-demo.gif"
ROADMAP_PDF = "docs/roadmap/neoncore-roadmap.pdf"
COMMAND = "scripts/labenv infra/lab.sh up"
STAGES = ["W0", "L0", "7", "8", "9", "10", "9B", "11", "12"]
STATUS_WORDS = re.compile(r"\b(done|closed|complete|completed|in progress|in-progress|active|current|"
                          r"planned|next|not started|todo|to do|open|pending|building|wip)\b", re.I)
STAGE_RE = re.compile(r"(?<![\w.])(W0|L0|9B|1[0-2]|[7-9])(?![\w.])")
TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")
MAX_GIF = 5_000_000


def sections(md):
    """Split into [(heading_line or None, text)] at '## ' headings (level 2 only)."""
    out, cur_h, cur = [], None, []
    in_fence = False
    for line in md.splitlines():
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
        if not in_fence and re.match(r"^## ", line):
            out.append((cur_h, "\n".join(cur)))
            cur_h, cur = line, []
        else:
            cur.append(line)
    out.append((cur_h, "\n".join(cur)))
    return out


def prose_words(text):
    t = re.sub(r"(?ms)^\s*(```|~~~).*?^\s*\1\s*$", " ", text)          # fenced code
    t = re.sub(r"(?s)<!--.*?-->", " ", t)                                # comments
    t = re.sub(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)", " ", t)              # badges
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)                           # images (alt not counted)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)                        # links: keep text
    t = re.sub(r"<[^>]+>", " ", t)                                        # html tags
    t = re.sub(r"https?://\S+", " ", t)                                   # bare urls
    t = re.sub(r"^\s*\[[^\]]+\]:\s*\S+.*$", " ", t, flags=re.M)           # reference defs
    t = re.sub(r"[#>*_|`~-]+", " ", t)
    return [w for w in re.findall(r"[A-Za-z0-9][\w'./+-]*", t)]


def links(md):
    out = []
    for m in re.finditer(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)", md):
        out.append(m.group(1))
    for m in re.finditer(r"^\s*\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)", md, re.M):
        out.append(m.group(1))
    for m in re.finditer(r"<(?:img|a|source)\b[^>]*?(?:src|href|srcset)=\"([^\"]+)\"", md, re.I):
        out.append(m.group(1))
    return out


def is_relative(u):
    return not re.match(r"^[a-z][a-z0-9+.-]*:", u, re.I) and not u.startswith("#") and not u.startswith("//")


def tracked_files(repo):
    r = common.run(["git", "-C", repo, "ls-files", "-z"], timeout=60)
    return set(x for x in r.stdout.split("\0") if x)


def check(repo):
    res = {}
    readme_p = os.path.join(repo, "README.md")
    with open(readme_p, encoding="utf-8") as f:
        md = f.read()
    secs = sections(md)
    top = secs[0][1]
    first_after = secs[1][1] if len(secs) > 1 else ""
    tracked = tracked_files(repo)

    words = prose_words(top)
    has_title = bool(re.search(r"^# ", top, re.M))
    res["S1"] = {"pass": has_title and len(words) <= 120, "prose_words": len(words), "limit": 120,
                 "title_found": has_title}

    s2 = {"embedded_in_top": GIF in " ".join(links(top))}
    gp = os.path.join(repo, GIF)
    s2["exists"] = os.path.isfile(gp)
    if s2["exists"]:
        s2["size"] = os.path.getsize(gp)
        fb = shutil.which("file")
        if fb:
            r = common.run([fb, "-b", gp], timeout=30)
            s2["file_says_gif"] = "GIF image data" in r.stdout
        else:
            s2["file_says_gif"] = False
            s2["note"] = "`file` not installed"
    s2["pass"] = bool(s2["embedded_in_top"] and s2["exists"] and s2.get("file_says_gif")
                      and s2.get("size", MAX_GIF + 1) <= MAX_GIF)
    res["S2"] = s2

    road = next((t for h, t in secs if h and re.match(r"^## Roadmap\s*$", h)), None)
    s3 = {"section_found": road is not None}
    if road is not None:
        found = {}
        for line in road.splitlines():
            if not re.match(r"^\s*(\||[-*+]\s|\d+\.\s)", line):
                continue
            m = STAGE_RE.search(line)
            if m and STATUS_WORDS.search(line):
                found.setdefault(m.group(1), line.strip()[:80])
        s3["stages_with_status"] = sorted(found, key=STAGES.index)
        s3["missing"] = [s for s in STAGES if s not in found]
        s3["links_pdf"] = any(u.split("#")[0].lstrip("./") == ROADMAP_PDF for u in links(road))
        s3["pdf_exists"] = os.path.isfile(os.path.join(repo, ROADMAP_PDF))
        s3["pass"] = not s3["missing"] and s3["links_pdf"] and s3["pdf_exists"]
    else:
        s3["pass"] = False
    res["S3"] = s3

    res["S4"] = {"pass": COMMAND in top or COMMAND in first_after,
                 "in_top": COMMAND in top, "in_first_section_after": COMMAND in first_after}

    res["S5"] = check_metadata(os.path.join(repo, "docs", "github-metadata.md"))
    res["S5"]["applied_on_github"] = "not tested (owner deferred until T15b)"

    bad, dirs, ok = [], [], 0
    for u in links(md):
        if not is_relative(u):
            continue
        path = os.path.normpath(u.split("#")[0].split("?")[0]).lstrip("./") if u.split("#")[0] else None
        if not path:
            continue
        if path in tracked:
            ok += 1
        elif any(t.startswith(path.rstrip("/") + "/") for t in tracked):
            dirs.append(path)
        else:
            bad.append(u)
    res["S6"] = {"pass": not bad, "resolved_files": ok, "directory_links": dirs, "unresolved": bad}
    res["result"] = "PASS" if all(res[k]["pass"] for k in ("S1", "S2", "S3", "S4", "S5", "S6")) else "FAIL"
    return res


def check_metadata(path):
    out = {"file_exists": os.path.isfile(path)}
    if not out["file_exists"]:
        out["pass"] = False
        return out
    with open(path, encoding="utf-8") as f:
        md = f.read()
    desc, topics = None, None
    m = re.search(r"^description:\s*(.+)$", md, re.M | re.I)
    if m:
        desc = m.group(1)
    else:
        m = re.search(r"^#{1,6}\s*Description\s*\n+(.+?)(?:\n\s*\n|\n#|\Z)", md, re.S | re.I | re.M)
        if m:
            desc = m.group(1)
    m = re.search(r"^topics:\s*(.+)$", md, re.M | re.I)
    if m:
        topics = re.split(r"[\s,]+", m.group(1).strip())
    else:
        m = re.search(r"^#{1,6}\s*Topics\s*\n+(.+?)(?:\n\s*\n#|\n#|\Z)", md, re.S | re.I | re.M)
        if m:
            body = m.group(1)
            items = re.findall(r"^\s*[-*+]\s+`?([^`\s]+)`?\s*$", body, re.M)
            topics = items or re.split(r"[\s,]+", body.replace("`", " ").strip())
    if desc is not None:
        desc = re.sub(r"^\s*>\s?", "", desc.strip(), flags=re.M).strip().strip("`\"'")
        desc = re.sub(r"\s+", " ", desc)
    topics = [t.strip("`\"'") for t in (topics or []) if t.strip("`\"'")]
    out["description_chars"] = len(desc) if desc is not None else None
    out["topics"] = topics
    out["bad_topics"] = [t for t in topics if not TOPIC_RE.match(t)]
    out["format_recognized"] = desc is not None and bool(topics)
    out["pass"] = bool(out["format_recognized"] and len(desc) <= 350 and len(topics) <= 20
                       and not out["bad_topics"])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="E9(a) static README checks")
    ap.add_argument("--repo", default=common.REPO)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        res = check(a.repo)
    except OSError as e:
        print(f"readme_static: {e.strerror}", file=sys.stderr)
        return 2
    res["provenance"] = common.git_provenance()
    if a.out:
        common.write_json(a.out, res)
    for k in ("S1", "S2", "S3", "S4", "S5", "S6"):
        print(f"{k} {'PASS' if res[k]['pass'] else 'FAIL'}")
    return 0 if res["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
