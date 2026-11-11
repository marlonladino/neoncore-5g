#!/usr/bin/env python3
"""NeonCore 5G approval gate -- a Claude Code PreToolUse command hook.

Reads the hook JSON on stdin and exits 0 (allow) or 2 (block, reason on stderr).
It FAILS CLOSED: any error, missing field, or missing/unknown project/STAGE blocks.

What it enforces (see docs/agent-gate.md for the full rationale and its limits):
  * writes outside the process folders need an approved plan whose SHA-256 still
    matches project/approvals/<STAGE>.plan.sha256 (editing the plan voids it);
  * every agent writes only inside its own scope; the lead has no product scope
    (except in stage W0, which builds this workflow);
  * lab-changing commands run only as lab-ops, and only with an approved plan;
  * developer cannot read datasets/holdout/; nobody touches project/approvals,
    approve.sh or .env.lab; destructive git/kubectl/rm commands are left to the user.

Bash rules parse command TEXT. They catch mistakes, not a determined adversary:
aliases, encoded commands and writes made from inside python/node are invisible.
The policy tables live in this file on purpose: .claude/hooks/** is edit-denied in
.claude/settings.json, so changing the policy takes the user's hand.
"""
import hashlib
import json
import os
import re
import shlex
import sys
import subprocess

STAGES = ["W0", "L0", "7", "8", "9", "10", "9B", "11", "12"]
KNOWN_AGENTS = {
    "phase-planner", "developer", "lab-ops", "evaluator",
    "telco-reviewer", "security-reviewer", "docs-writer", "blog-writer",
}

# Section 5 product scopes ("/" suffix = directory prefix, else exact file).
PRODUCT_SCOPE = {
    "developer": ["phase5/", "phase6/", "phase7/", "phase8/", "phase9/", "phase10/",
                  "phase11/", "phase12/", "tests/"],
    "lab-ops": ["infra/", "setup/", "start.sh", "stop.sh",
                "phase2/manifests/", "phase3/manifests/", "phase4/manifests/"],
    "evaluator": ["evals/"],
    "docs-writer": ["docs/", "README.md", "DEVLOG.md"],
    "blog-writer": ["site/"],
    "phase-planner": [],
    "telco-reviewer": [],
    "security-reviewer": [],
    "lead": [],
}
# Stage W0 builds this workflow, so only then does the lead get a product scope.
LEAD_W0_SCOPE = [".claude/", "project/", "scripts/", "CLAUDE.md", ".gitignore",
                 "docs/roadmap/", "docs/agent-gate.md", "DEVLOG.md"]

PROCESS_PREFIXES = ["project/plans/", "project/notes/", "project/reports/",
                    "project/STAGE", "project/STATUS.md"]

# Never writable by any agent (the gate's own files are writable by the lead in W0 only).
ALWAYS_BLOCKED = ["project/approvals/", ".env.lab"]
GATE_FILES = [".claude/hooks/", ".claude/settings.json", "scripts/approve.sh",
              "docs/roadmap/"]


def process_scope(actor, stage):
    rep = f"project/reports/{stage}/"
    return {
        "phase-planner": ["project/plans/"],
        "developer": ["project/notes/"],
        "lab-ops": ["project/notes/"],
        "evaluator": [rep + "eval/"],
        "telco-reviewer": [rep + "telco.md"],
        "security-reviewer": [rep + "security.md"],
        "lead": ["project/STAGE", "project/STATUS.md", "project/notes/", rep + "close.md"],
    }.get(actor, [])


class Block(Exception):
    pass


# ---------------------------------------------------------------- helpers

def in_scope(rel, prefixes):
    for p in prefixes:
        if p.endswith("/"):
            if rel == p[:-1] or rel.startswith(p):
                return True
        elif rel == p:
            return True
    return False


def ancestor_of_scope(rel, prefixes):
    """True if rel is a directory on the way to a scope entry (for mkdir -p)."""
    return any(p.startswith(rel.rstrip("/") + "/") for p in prefixes)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class Ctx:
    def __init__(self, data):
        self.data = data
        self.root = os.environ.get("CLAUDE_PROJECT_DIR")
        if not self.root:
            raise Block("CLAUDE_PROJECT_DIR not set (fail closed)")
        self.root = os.path.realpath(self.root)
        self.actor = data.get("agent_type") or "lead"
        self.cwd = data.get("cwd") or self.root
        self.stage = None
        self.stage_error = None
        try:
            with open(os.path.join(self.root, "project", "STAGE")) as f:
                s = f.read().strip()
            if s not in STAGES:
                self.stage_error = f"project/STAGE '{s}' is not a known stage"
            else:
                self.stage = s
        except OSError:
            self.stage_error = "project/STAGE is missing"

    # -- stage / approval
    def need_stage(self):
        if self.stage is None:
            raise Block(f"{self.stage_error} (fail closed)")
        return self.stage

    def plan_approved(self):
        stage = self.need_stage()
        plan = os.path.join(self.root, "project", "plans", f"{stage}.md")
        appr = os.path.join(self.root, "project", "approvals", f"{stage}.plan.sha256")
        if not (os.path.isfile(plan) and os.path.isfile(appr)):
            return False
        with open(appr) as f:
            recorded = (f.read().split() or [""])[0].strip().lower()
        return bool(recorded) and recorded == sha256_file(plan)

    def require_approval(self, what):
        if not self.plan_approved():
            raise Block(f"{what} needs an approved plan: project/plans/{self.stage}.md has no "
                        f"matching approval (missing, or the plan changed since approval). "
                        f"Ask the user to run scripts/approve.sh {self.stage} plan")

    # -- paths
    def resolve(self, path, cwd=None):
        if not path:
            raise Block("tool input has no path (fail closed)")
        path = os.path.expanduser(path)
        if not os.path.isabs(path):
            path = os.path.join(cwd or self.cwd, path)
        return os.path.realpath(path)

    def rel(self, abspath):
        if abspath == self.root:
            return ""
        if abspath.startswith(self.root + os.sep):
            return os.path.relpath(abspath, self.root).replace(os.sep, "/")
        return None

    def outside_allowed(self, abspath):
        home = os.path.realpath(os.path.expanduser("~"))
        slug = self.root.replace("/", "-")
        allowed = [
            os.path.join(home, ".claude", "plans"),
            os.path.join(home, ".claude", "projects", slug, "memory"),
            f"/tmp/claude-{os.getuid()}",
        ]
        return any(abspath == a or abspath.startswith(a + os.sep) for a in allowed)

    # -- the write rule, shared by Edit/Write/NotebookEdit and Bash write targets
    def check_write(self, abspath, mkdir=False):
        rel = self.rel(abspath)
        if rel is None:
            if self.outside_allowed(abspath):
                return
            raise Block(f"write outside the repo and outside the allowed scratch/plan/memory "
                        f"dirs: {abspath}")
        if rel in ("", ".git") or rel.startswith(".git/"):
            raise Block(f"direct write to {rel or 'repo root'} is not allowed")
        if os.path.basename(rel) == ".env.lab" or in_scope(rel, ALWAYS_BLOCKED):
            raise Block(f"{rel} is never writable by an agent")
        stage = self.need_stage()
        actor = self.actor
        if actor != "lead" and actor not in KNOWN_AGENTS:
            raise Block(f"unknown agent type '{actor}' is read-only")
        if in_scope(rel, GATE_FILES) and not (actor == "lead" and stage == "W0"):
            raise Block(f"{rel} is part of the gate; only the user changes it after W0")
        if in_scope(rel, [f".claude/agent-memory-local/{actor}/"]):
            return
        pscope = process_scope(actor, stage)
        if in_scope(rel, PROCESS_PREFIXES):
            if in_scope(rel, pscope) or (mkdir and ancestor_of_scope(rel, pscope)):
                return
            if actor == "lead" and stage == "W0" and in_scope(rel, LEAD_W0_SCOPE):
                self.require_approval(f"write to {rel}")
                return
            raise Block(f"{rel} is outside {actor}'s process scope {pscope}")
        scope = list(PRODUCT_SCOPE.get(actor, []))
        if actor == "lead" and stage == "W0":
            scope += LEAD_W0_SCOPE
        if not (in_scope(rel, scope) or (mkdir and ancestor_of_scope(rel, scope))):
            raise Block(f"{rel} is outside {actor}'s write scope {scope or '(none)'}")
        self.require_approval(f"write to {rel}")


# ---------------------------------------------------------------- read tools

def check_read(ctx, tool_input):
    path = tool_input.get("file_path") or tool_input.get("path") or ctx.cwd
    pattern = str(tool_input.get("pattern") or "") + " " + str(tool_input.get("glob") or "")
    rel = ctx.rel(ctx.resolve(path)) or ""
    if os.path.basename(rel) == ".env.lab" or ".env.lab" in pattern:
        raise Block(".env.lab is read only through scripts/labenv")
    if ctx.actor == "developer":
        if rel == "datasets/holdout" or rel.startswith("datasets/holdout/") or "holdout" in pattern:
            raise Block("developer may not read datasets/holdout/")


# ---------------------------------------------------------------- bash

HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def strip_heredocs(cmd):
    """Drop heredoc bodies (their text is data, not commands)."""
    out, lines, i = [], cmd.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        tags = [m.group(2) for m in HEREDOC.finditer(line)]
        i += 1
        for tag in tags:
            while i < len(lines) and lines[i].strip() != tag:
                i += 1
            i += 1  # skip terminator
    return "\n".join(out)


REDIRECTS = {">", ">>", ">|", "&>", "&>>"}


def segments(cmd):
    """Split a command line into simple-command token lists (best effort)."""
    lex = shlex.shlex(cmd.replace("\n", " ; "), posix=True, punctuation_chars=";&|()<>")
    lex.whitespace_split = True
    lex.commenters = ""
    segs, cur = [], []
    for tok in lex:
        if tok not in REDIRECTS and set(tok) <= set(";&|()"):
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        segs.append(cur)
    return segs


def nonopts(tokens):
    return [t for t in tokens if not t.startswith("-")]


def write_targets(seg):
    """Return (targets, mkdir_flag) for one command segment."""
    targets = []
    # redirections anywhere in the segment
    for i, t in enumerate(seg):
        if t in REDIRECTS and i + 1 < len(seg):
            nxt = seg[i + 1]
            if nxt.startswith("&") or nxt.isdigit():
                continue
            targets.append(nxt)
    # strip leading env assignments / sudo
    words = [t for t in seg if t not in REDIRECTS]
    while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or words[0] in ("sudo", "env", "command", "nohup", "time")):
        words = words[1:]
    if not words:
        return targets, False
    prog, args = os.path.basename(words[0]), words[1:]
    mkdir = False
    if prog == "tee":
        targets += nonopts(args)
    elif prog == "sed" and any(a.startswith("-i") or a == "--in-place" for a in args):
        rest = nonopts(args)
        has_e = any(a in ("-e", "-f") or a.startswith("--expression") for a in args)
        targets += rest if has_e else rest[1:]
    elif prog in ("cp", "install", "ln"):
        rest = nonopts(args)
        if rest:
            targets.append(rest[-1])
    elif prog in ("mv",):
        targets += nonopts(args)
    elif prog in ("rm", "rmdir", "touch", "truncate", "chmod", "chown", "unlink", "shred"):
        rest = nonopts(args)
        if prog in ("chmod", "chown") and rest:
            rest = rest[1:]
        targets += rest
    elif prog == "mkdir":
        targets += nonopts(args)
        mkdir = True
    elif prog == "dd":
        targets += [a[3:] for a in args if a.startswith("of=")]
    elif prog == "git" and args:
        sub = args[0]
        if sub == "checkout" and "--" in args:
            targets += args[args.index("--") + 1:]
        elif sub == "restore":
            targets += nonopts(args[1:]) or ["."]
    return targets, mkdir


DESTRUCTIVE = [
    (r"\bgit\s+push\b[^\n;&|]*(\s--force\b|\s-f\b|\s--force-with-lease\b|\s\+\S)", "force push"),
    (r"\bgit\s+branch\b[^\n;&|]*(\s-D\b|\s--delete\s+--force\b|\s-d\s+-f\b)", "force branch delete"),
    (r"\bgit\s+reset\b[^\n;&|]*--hard\b", "git reset --hard"),
    (r"\bgit\s+rebase\b", "history rewrite (git rebase)"),
    (r"\bgit\s+filter-(branch|repo)\b", "history rewrite"),
    (r"\bgit\s+clean\b[^\n;&|]*\s-[a-zA-Z]*f", "git clean -f"),
    (r"\bkubectl\b[^\n;&|]*\bdelete\s+(ns|namespace|namespaces)\b", "namespace deletion"),
    (r"\b(terraform)\b[^\n;&|]*\bdestroy\b", "terraform destroy"),
    (r"\b(qm|pct)\s+destroy\b", "guest destroy"),
    (r"\bdocker\s+push\b", "image publication"),
    (r"\bgh\s+(repo\s+(create|edit|delete|rename|archive)|release\s|pr\s+(create|merge)|gist\s+create|issue\s+create)", "GitHub publication"),
    (r"\bgh\s+api\b[^\n;&|]*(-X|--method)\s*(POST|PUT|PATCH|DELETE)", "GitHub API write"),
    (r"\bscript\b[^\n;&|]*\s-\w*c", "pty wrapper (script -c)"),
    (r"\b(unbuffer|expect)\b|pty\.spawn", "pty wrapper"),
    (r"\benv\b[^\n;&|]*-u\s*CLAUDE|\bunset\s+CLAUDE|CLAUDECODE=|CLAUDE_CODE_ENTRYPOINT=",
     "unsetting Claude Code markers"),
]

EVAL_SCRIPTS = ("capture_baseline.sh", "compare_baseline.py", "mtu_check.sh", "pcap_check.py",
                "ping_check.sh", "pods_check.py", "prom_check.py", "readme_static.py",
                "scan_parse.py", "tls_negative.sh", "wsl_grep.sh")
_EV_PY = "|".join(re.escape(n) for n in EVAL_SCRIPTS if n.endswith(".py"))
_EV_SH = "|".join(re.escape(n) for n in EVAL_SCRIPTS if n.endswith(".sh"))

LAB = [
    r"\bterraform\s+(-chdir=\S+\s+)?(apply|import|taint|untaint)\b",
    r"\bterraform\s+(-chdir=\S+\s+)?state\s+(rm|mv|push|replace-provider)\b",
    r"\bansible-playbook\b",
    r"\bansible\s+\S+\s+(-m|--module-name)\b",
    r"\b(qm|pct)\s+(?!list\b|status\b|config\b|listsnapshot\b|pending\b|help\b)[a-z]",
    r"\bpvesh\s+(create|set|delete)\b",
    r"\bpvesm\s+(add|set|remove|alloc|free)\b",
    r"\bcurl\b[^\n;&|]*(-X\s*|--request\s*)(POST|PUT|DELETE|PATCH)\b[^\n;&|]*:8006",
    r"\bcurl\b[^\n;&|]*:8006[^\n;&|]*(-X\s*|--request\s*)(POST|PUT|DELETE|PATCH)\b",
    r"\bhelm\s+(install|upgrade|uninstall|delete|rollback)\b",
    r"(^|[\s;&|(])(ssh|scp|rsync|sftp)\s",
    r"\bk3s\s+(server|agent|etcd-snapshot|certificate)\b|k3s-uninstall\.sh|k3s-killall\.sh",
    r"\bsystemctl\s+(start|stop|restart|enable|disable|mask)\b",
    r"(^|[\s;&|(/])lab\.sh\s+(up|deploy|start|stop|snapshot)\b",
    r"(^|[\s;&|(/])(start|stop)\.sh\b",
    rf"(^|[\s;&|(/])labenv\b(?!\s+(infra/lib/pve_get\.sh|infra/lab\.sh\s+(status|verify)|python3\s+-I\s+evals/l0/({_EV_PY})|evals/l0/({_EV_SH}))(\s|$))",
]

EVAL_LABENV = re.compile(
    rf"(^|[\s;&|(/])labenv\s+(python3\s+-I\s+evals/l0/({_EV_PY})|evals/l0/({_EV_SH}))(\s|$)")


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

KUBE_READ = {"get", "describe", "logs", "top", "version", "explain", "api-resources",
             "api-versions", "config", "auth", "wait", "cluster-info", "events", "diff"}
KUBE_LAB_VERBS = {"apply", "create", "replace", "drain", "cordon", "uncordon", "taint",
                  "edit", "run", "expose", "autoscale", "certificate", "kustomize"}
CLUSTER_KINDS = re.compile(
    r"^(no|nodes?|ns|namespaces?|crds?|customresourcedefinitions?(\.\S+)?|clusterroles?(\.\S+)?|"
    r"clusterrolebindings?(\.\S+)?|sc|storageclass(es)?(\.\S+)?|pv|persistentvolumes?|"
    r"helmcharts?(\.\S+)?|helmchartconfigs?(\.\S+)?|mutatingwebhookconfigurations?|"
    r"validatingwebhookconfigurations?|priorityclass(es)?|apiservices?|csidrivers?|"
    r"runtimeclass(es)?|network-attachment-definitions?)(/\S*)?$", re.I)
PROJECT_NS = {"neoncore", "monitoring"}
EXEC_READ_BINS = {"ls", "cat", "ps", "stat", "df", "du", "ip", "ss", "head", "tail", "date",
                  "wc", "find", "grep", "uptime", "free", "hostname", "env", "printenv"}


def kubectl_check(ctx, seg):
    """Classify one kubectl invocation. Raises Block or returns None."""
    i = next((k for k, t in enumerate(seg) if os.path.basename(t) == "kubectl"), None)
    if i is None:
        return
    args = seg[i + 1:]
    ns, verb, positional, j = None, None, [], 0
    allns = False
    while j < len(args):
        a = args[j]
        if a == "--":
            break
        if a in ("-n", "--namespace") and j + 1 < len(args):
            ns = args[j + 1]; j += 2; continue
        if a.startswith("--namespace="):
            ns = a.split("=", 1)[1]
        elif a.startswith("-n") and len(a) > 2 and not a.startswith("--"):
            ns = a[2:]
        elif a in ("-A", "--all-namespaces"):
            allns = True
        elif a in ("--context", "--kubeconfig", "-l", "--selector", "-o", "-c", "--container",
                   "-f", "--filename", "--replicas", "--field-selector", "--timeout", "--for",
                   "-p", "--patch", "--type", "--tail", "--since", "-k", "--kustomize") and j + 1 < len(args):
            if a in ("-f", "--filename", "-k", "--kustomize"):
                positional.append("@file")
            j += 2; continue
        elif not a.startswith("-"):
            if verb is None:
                verb = a
            else:
                positional.append(a)
        j += 1
    if verb is None or verb in KUBE_READ:
        return
    exec_cmd = args[args.index("--") + 1:] if "--" in args else []
    cluster = (verb in KUBE_LAB_VERBS or "@file" in positional or allns
               or ns == "kube-system" or any(CLUSTER_KINDS.match(p) for p in positional))
    if cluster or (ns not in PROJECT_NS):
        if ctx.actor != "lab-ops":
            raise Block(f"kubectl {verb} outside the neoncore/monitoring namespaces or on "
                        f"cluster-level resources is lab-ops only")
        ctx.require_approval(f"kubectl {verb}")
        return
    if verb == "exec" and exec_cmd and \
            os.path.basename(exec_cmd[0]) in EXEC_READ_BINS:
        return  # read-only peek into a project pod
    if True:  # any other namespaced mutation (delete pod, scale, exec, ...)
        if ctx.actor != "lead" and ctx.actor not in KNOWN_AGENTS:
            raise Block(f"unknown agent type '{ctx.actor}' is read-only")
        ctx.require_approval(f"kubectl {verb} in {ns}")


def check_bash(ctx, cmd):
    if not isinstance(cmd, str) or not cmd.strip():
        raise Block("empty command (fail closed)")
    flat = re.sub(r"\s+", " ", re.sub(r"[\"'\\`]", "", cmd))
    flat = re.sub(r"/(?:\.?/)+", "/", flat)   # collapse // and /./ (S-I1)
    if re.search(r"project/approvals|approve\.sh|appr[a-z]*[*?\[]|(^|[\s/=<>;&|(])\.env", flat):
        raise Block("commands may not mention project/approvals, approve.sh or .env.lab "
                    "(the user runs approve.sh; secrets load only via scripts/labenv)")
    for pat, what in DESTRUCTIVE:
        if re.search(pat, flat):
            raise Block(f"{what} is destructive or publishing: the user runs it themself")
    if ctx.actor == "developer" and re.search(r"datasets/+holdout|holdout", flat):
        raise Block("developer may not read or touch datasets/holdout/")
    readonly_actor = ctx.actor != "lead" and ctx.actor not in KNOWN_AGENTS
    for pat in LAB:
        if re.search(pat, flat):
            if ctx.actor != "lab-ops":
                raise Block("lab-changing command: only lab-ops may run it")
            ctx.require_approval("lab-changing command")
            break
    if EVAL_LABENV.search(flat):
        if ctx.actor not in ("evaluator", "lab-ops"):
            raise Block("evals/l0 under the lab wrapper is evaluator/lab-ops only")
        if not eval_files_clean(ctx.root):
            raise Block("evals/l0 scripts must be committed and unchanged before running with lab credentials")
        ctx.require_approval("evals/l0 under the lab wrapper")
    if re.search(r"-m\s+phase\d+\w*\.|phase\d+/run\.sh|phase\d+/\S+\.sh\b", flat) and \
            not re.search(r"\b(cat|less|head|tail|bash\s+-n|shellcheck)\s+\S*phase", flat):
        if readonly_actor:
            raise Block(f"unknown agent type '{ctx.actor}' is read-only")
        ctx.require_approval("running the project CLI against the lab")

    body = strip_heredocs(cmd)
    try:
        segs = segments(body)
    except ValueError as e:
        raise Block(f"could not parse the command ({e}); simplify it (fail closed)")
    cwd = ctx.cwd
    for seg in segs:
        if seg and seg[0] == "cd":
            dest = seg[1] if len(seg) > 1 else "~"
            cwd = ctx.resolve(dest, cwd)
            continue
        if any(os.path.basename(t) == "kubectl" for t in seg):
            kubectl_check(ctx, seg)
        targets, mkdir = write_targets(seg)
        for t in targets:
            if t in ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"):
                continue
            if any(c in t for c in "$`*?{[") or not t:
                if readonly_actor:
                    raise Block(f"unknown agent type '{ctx.actor}' is read-only")
                ctx.check_write(os.path.join(cwd, "__unresolved_target__"))
                continue
            if readonly_actor:
                raise Block(f"unknown agent type '{ctx.actor}' is read-only")
            ctx.check_write(ctx.resolve(t, cwd), mkdir=mkdir)
        # rm -r outside the scratchpad is destructive even inside scope
        if seg and os.path.basename(seg[0]) == "rm" and any(
                re.match(r"^-[a-zA-Z]*[rR]", a) or a == "--recursive" for a in seg[1:]):
            scratch = f"/tmp/claude-{os.getuid()}"
            for t in nonopts(seg[1:]):
                p = ctx.resolve(t, cwd)
                if not (p == scratch or p.startswith(scratch + os.sep)):
                    raise Block(f"recursive rm of {t} is destructive: the user runs it themself")


# ---------------------------------------------------------------- main

def evaluate(data):
    if not isinstance(data, dict):
        raise Block("hook input is not a JSON object (fail closed)")
    tool = data.get("tool_name")
    ti = data.get("tool_input")
    if not tool or not isinstance(ti, dict):
        raise Block("hook input lacks tool_name/tool_input (fail closed)")
    ctx = Ctx(data)
    if tool in ("Read", "Grep", "Glob"):
        check_read(ctx, ti)
        return ctx
    ctx.need_stage()
    if tool in ("Edit", "Write", "MultiEdit"):
        ctx.check_write(ctx.resolve(ti.get("file_path")))
    elif tool == "NotebookEdit":
        ctx.check_write(ctx.resolve(ti.get("notebook_path")))
    elif tool == "Bash":
        check_bash(ctx, ti.get("command"))
    else:
        raise Block(f"gate does not know tool '{tool}' (fail closed)")
    return ctx


def main():
    actor = "?"
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
        actor = (data.get("agent_type") if isinstance(data, dict) else None) or "lead"
        evaluate(data)
    except Block as b:
        print(f"GATE BLOCKED [{actor}] {b}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:  # noqa: BLE001 -- fail closed on anything unexpected
        print(f"GATE BLOCKED [{actor}] gate error, failing closed: {e!r}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
