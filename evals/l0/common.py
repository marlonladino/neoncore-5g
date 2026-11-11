"""Shared helpers for the L0 evaluator scripts (stdlib only).

Every repo write goes through redact.write_redacted (S-B5). Strings that end up in
Markdown are passed through md_code() (control/ANSI stripped, put in a code span).
"""
import hashlib
import json
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import redact  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
MSIN_RE = re.compile(r"^[0-9]{9,10}$")


def valid_msin(s):
    return isinstance(s, str) and bool(MSIN_RE.match(s))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(argv, timeout=120, env=None, input_text=None):
    """subprocess.run with a list argv, never a shell. Returns CompletedProcess."""
    if isinstance(argv, str):
        raise TypeError("argv must be a list")
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env,
                          input=input_text)


def git_provenance():
    out = {}
    try:
        out["git_sha"] = run(["git", "-C", REPO, "rev-parse", "HEAD"]).stdout.strip()
        st = run(["git", "-C", REPO, "status", "--porcelain"]).stdout
        out["git_porcelain_lines"] = len([x for x in st.splitlines() if x.strip()])
        out["git_clean"] = out["git_porcelain_lines"] == 0
    except (OSError, subprocess.SubprocessError):
        out["git_sha"] = None
    return out


def site_values():
    """Site values for redaction. Fails closed like the redact.py CLI (exit 4) when no
    site variable is in the environment, so evidence is never written with only the
    structural and IP steps by accident. L0_ALLOW_NO_SITE_VALUES=1 is the explicit
    opt-in for unit tests and outputs that cannot contain site values."""
    vals, found = redact.load_site_values()
    if found == 0 and os.environ.get("L0_ALLOW_NO_SITE_VALUES") != "1":
        print("redact: no site variables in the environment; refusing to write evidence "
              "(run under the lab env wrapper, or set L0_ALLOW_NO_SITE_VALUES=1 where no "
              "site value can occur)", file=sys.stderr)
        sys.exit(4)
    return vals


def write_text(path, text, append=False):
    """Redacted, fail-closed write. Exits the process with 3 on a redaction hit."""
    rc = redact.write_redacted(path, text, site_values(), append=append)
    if rc != 0:
        print(f"refusing to keep {os.path.basename(path)}: redaction scan hit", file=sys.stderr)
        sys.exit(rc)


def write_json(path, obj):
    write_text(path, json.dumps(obj, indent=2, sort_keys=True) + "\n")


def append_sha256sums(dirpath, files):
    """Append '<sha256>  <relative name>' lines to dirpath/SHA256SUMS."""
    lines = []
    for f in files:
        rel = os.path.relpath(f, dirpath)
        lines.append(f"{sha256_file(f)}  {rel}\n")
    if lines:
        write_text(os.path.join(dirpath, "SHA256SUMS"), "".join(lines), append=True)


def md_code(s, maxlen=200):
    s = redact.strip_control(str(s)).replace("\n", " ").replace("`", "'")
    if len(s) > maxlen:
        s = s[:maxlen] + "..."
    return f"`{s}`"


def wilson(k, n, z=1.959963984540054):
    """Wilson score interval for k successes in n trials (95% by default)."""
    if n == 0:
        return (None, None)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def percentile(xs, q):
    """Nearest-rank percentile (no interpolation): the value at rank ceil(q*n)."""
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    r = max(1, math.ceil(q * len(xs)))
    return xs[r - 1]
