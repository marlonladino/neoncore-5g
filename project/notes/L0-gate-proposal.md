# Gate patch proposal for the owner (L0 security interim review S-I1, S-I2, S-I3)

Drafted by the lead on 2026-11-10 from `project/reports/L0/security.md` ("Build review (interim)").
**Not tested.** The gate blocks the lead from running any Bash command whose text names the lab
wrapper, so these regexes could not be tried here. Your `test_gate.py` run is the check.
`.claude/hooks/gate.py` and `scripts/tests/test_gate.py` are yours to edit; no agent may.

## 1. Normalize paths before matching (S-I1)

In `check_bash`, right after `flat = ...`, add:

```python
    flat = re.sub(r"/(?:\.?/)+", "/", flat)   # collapse // and /./ (S-I1)
```

## 2. Replace your three D16 patterns in `LAB` (S-I1, S-I2)

Anchor on the basename so `cd scripts && ./labenv ...`, `scripts/./labenv` and `infra/./lab.sh`
are caught, and take `redact` out of the evaluator allowance:

```python
    r"(^|[\s;&|(/])lab\.sh\s+(up|deploy|start|stop|snapshot)\b",
    r"(^|[\s;&|(/])(start|stop)\.sh\b",
    r"(^|[\s;&|(/])labenv\b(?!\s+(infra/lib/pve_get\.sh|infra/lab\.sh\s+(status|verify)|python3\s+-I\s+(-m\s+evals\.l0\.(?!redact\b)[a-z_]+|evals/l0/(?!redact\.py)[a-z_]+\.py)|evals/l0/[a-z_]+\.sh)\b)",
```

Effect on lab-ops' own notes command (`scripts/labenv python3 -I evals/l0/redact.py ...`): it now
matches LAB, so lab-ops may still run it under an approved plan; no other agent can.

## 3. Restrict the evals allowance to evaluator and lab-ops (S-I2)

Add near `LAB`:

```python
EVAL_LABENV = re.compile(
    r"(^|[\s;&|(/])labenv\s+(python3\s+-I\s+(-m\s+evals\.l0\.[a-z_]+|evals/l0/[a-z_]+\.py)|evals/l0/[a-z_]+\.sh)\b")
```

and in `check_bash`, right after the `for pat in LAB:` loop:

```python
    if EVAL_LABENV.search(flat):
        if ctx.actor not in ("evaluator", "lab-ops"):
            raise Block("evals/l0 under the lab wrapper is evaluator/lab-ops only")
        ctx.require_approval("evals/l0 under the lab wrapper")
```

## 4. Interim block on faked terminals and approval globs (S-I3)

Add to `DESTRUCTIVE` (blocks every agent; you are not affected, the gate only sees agent commands):

```python
    (r"\bscript\b[^\n;&|]*\s-\w*c", "pty wrapper (script -c)"),
    (r"\b(unbuffer|expect)\b|pty\.spawn", "pty wrapper"),
    (r"\benv\b[^\n;&|]*-u\s*CLAUDE|\bunset\s+CLAUDE|CLAUDECODE=|CLAUDE_CODE_ENTRYPOINT=",
     "unsetting Claude Code markers"),
```

and widen the existing approvals/env-file check to catch globs:

```python
    if re.search(r"project/approvals|approve\.sh|\.env\.lab|appr[a-z]*[*?\[]|\.env\.l[a-z]*[*?\[]", flat):
```

Side effect: a command whose text contains the bare word `expect` (not `expected`) is blocked.

## 5. Tests to add in `scripts/tests/test_gate.py` (inside `test_06`, after `self.fx.approve("7")`)

```python
        for c in ("scripts/./labenv printenv", "./scripts//labenv printenv",
                  "cd scripts && ./labenv printenv", "infra/./lab.sh up", "../infra/lab.sh up",
                  "scripts/labenv python3 -I -m evals.l0.redact --stdout /proc/self/environ",
                  "scripts/labenv python3 -I evals/l0/redact.py --stdout /proc/self/environ"):
            self.assertBlocked(self.bash(c, "evaluator"))
        self.assertBlocked(self.bash("scripts/labenv evals/l0/ping_check.sh 3", "docs-writer"))
        self.assertAllowed(self.bash("scripts/labenv evals/l0/ping_check.sh 3", "evaluator"))
        self.assertAllowed(self.bash("scripts/labenv python3 -I evals/l0/redact.py --append -o x -", "lab-ops"))
        for c in ("env -u CLAUDECODE script -qec ls /dev/null", "unset CLAUDECODE; ls",
                  "scripts/appr*.sh L0 plan", "ls project/approv*"):
            self.assertBlocked(self.bash(c, "lab-ops"))
```

Then run `python3 scripts/tests/test_gate.py`. All tests should pass.

## 6. The real fix for S-I3 (your decision, later)

The interim rules above are text matching and can be evaded with more effort. The reviewer's
durable fix: `scripts/approve.sh` signs `"<stage> <kind> <sha256>"` with `ssh-keygen -Y sign`
using a key an agent cannot use unattended (passphrase-protected and not in the agent's
ssh-agent, or a FIDO `-sk` key that needs a touch); `gate.py` and `infra/lib/approval_check.sh`
verify it with `ssh-keygen -Y verify` against a committed `allowed_signers`; the TTY exemption in
`approval_check.sh` and the plan guard's typed confirmation move to the same signature. This
changes W0 machinery, so it needs a W0 amendment or its own small plan.

## 6b. Second round, after the security re-check (R2, BLOCKING; added 2026-11-10)

Source: `project/reports/L0/security.md`, "Gate patch re-check (2026-11-10)". Not tested by the lead.

**(a) Any agent can read the secrets file with a glob** (`cat .env.*`, `. ./.env*`). Block any
token whose basename starts with `.env`. Replace the approvals/env-file line again with:

```python
    if re.search(r"project/approvals|approve\.sh|appr[a-z]*[*?\[]|(^|[\s/=<>;&|(])\.env", flat):
```

**(b) The evaluator could add a new script under `evals/l0/` and run it with the token.** Replace
the `[a-z_]+` name patterns with the exact list, and require those files to be tracked and
unchanged. Near `LAB`:

```python
EVAL_SCRIPTS = ("capture_baseline.sh", "compare_baseline.py", "mtu_check.sh", "pcap_check.py",
                "ping_check.sh", "pods_check.py", "prom_check.py", "readme_static.py",
                "scan_parse.py", "tls_negative.sh", "wsl_grep.sh")
_EV = "|".join(re.escape(n) for n in EVAL_SCRIPTS)
_EV_PY = "|".join(re.escape(n) for n in EVAL_SCRIPTS if n.endswith(".py"))
_EV_SH = "|".join(re.escape(n) for n in EVAL_SCRIPTS if n.endswith(".sh"))
```

Change the third LAB pattern's allowance and `EVAL_LABENV` to use the list:

```python
    rf"(^|[\s;&|(/])labenv\b(?!\s+(infra/lib/pve_get\.sh|infra/lab\.sh\s+(status|verify)|python3\s+-I\s+evals/l0/({_EV_PY})|evals/l0/({_EV_SH}))(\s|$))",
EVAL_LABENV = re.compile(
    rf"(^|[\s;&|(/])labenv\s+(python3\s+-I\s+evals/l0/({_EV_PY})|evals/l0/({_EV_SH}))(\s|$)")
```

(The `-m evals.l0.*` form is dropped: it never worked under `python3 -I`.)

Add `import subprocess` at the top, and this helper:

```python
def eval_files_clean(root):
    files = [f"evals/l0/{n}" for n in EVAL_SCRIPTS] + ["evals/l0/common.py", "evals/l0/redact.py"]
    try:
        subprocess.run(["git", "-C", root, "ls-files", "--error-unmatch", *files],
                       check=True, capture_output=True, timeout=10)
        subprocess.run(["git", "-C", root, "diff", "--quiet", "HEAD", "--", *files],
                       check=True, capture_output=True, timeout=10)
        return True
    except Exception:
        return False   # fail closed
```

and extend the `EVAL_LABENV` block in `check_bash`:

```python
    if EVAL_LABENV.search(flat):
        if ctx.actor not in ("evaluator", "lab-ops"):
            raise Block("evals/l0 under the lab wrapper is evaluator/lab-ops only")
        if not eval_files_clean(ctx.root):
            raise Block("evals/l0 scripts must be committed and unchanged before running with lab credentials")
        ctx.require_approval("evals/l0 under the lab wrapper")
```

Consequence: the evaluator must commit a script change before running it with credentials.
Update the test from round 1 that uses `-m evals.l0.pods_check` (it is no longer allowed) and add:

```python
        for c in ("cat .env.*", "cat .env*", "cat .env.?ab", "set -a; . ./.env.*"):
            self.assertBlocked(self.bash(c, "evaluator"))
        self.assertBlocked(self.bash("scripts/labenv evals/l0/newthing.sh", "evaluator"))
```

**(c) What text rules cannot fix.** The re-check found 7 indirection forms (variables, globs,
`base64 -d | sh`, a copied wrapper), 8 more pty tools and 9 more ways to clear the Claude Code
markers. A text gate cannot close these classes. The structural fix is to stop agents from being
able to read `.env.lab` at all: run Claude Code as a separate OS user that has no read access to
it, with `scripts/labenv` reachable only through a sudoers entry limited to an exact command
list (or an equivalent OS-level sandbox read-deny on the file). Together with signed approvals
(section 6) this is a W0 change: it needs its own small plan.

## 7. Also needed from the evaluator (not the gate)

`evals/l0/redact.py`: map NUL and other control characters to newlines instead of deleting them;
match the token, its parts and every fingerprint form as plain substrings with no word-boundary
checks (redact and scan); refuse inputs under `/proc/`, `/sys/`, `/dev/` and non-regular files
(stdin stays allowed); tests for each. Scheduled for after R1, because R1 uses `redact.py`.
