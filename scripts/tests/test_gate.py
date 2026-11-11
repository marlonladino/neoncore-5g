#!/usr/bin/env python3
"""W0 gate tests: feed sample PreToolUse JSON to .claude/hooks/gate.py.

Runs against a throwaway fixture project (CLAUDE_PROJECT_DIR points at a temp dir),
so it never touches the real project/approvals. Stdlib only:

    python3 scripts/tests/test_gate.py -v
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
GATE = os.path.join(REPO, ".claude", "hooks", "gate.py")
AGENTS = ["phase-planner", "developer", "lab-ops", "evaluator", "telco-reviewer",
          "security-reviewer", "docs-writer", "blog-writer"]


class Fixture:
    def __init__(self, stage="7"):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="gatefix-"))
        for d in ("project/plans", "project/approvals", "project/notes", "project/reports",
                  "phase7", "evals", "datasets/holdout", ".claude/hooks", "scripts"):
            os.makedirs(os.path.join(self.root, d), exist_ok=True)
        self.set_stage(stage)
        self.write_plan(stage, "# Stage plan\n\nbody\n")

    def set_stage(self, stage):
        with open(os.path.join(self.root, "project", "STAGE"), "w") as f:
            f.write(stage + "\n")

    def write_plan(self, stage, text):
        with open(os.path.join(self.root, "project", "plans", f"{stage}.md"), "w") as f:
            f.write(text)

    def approve(self, stage):
        """Simulates what approve.sh writes (the real script needs a human at a TTY)."""
        plan = os.path.join(self.root, "project", "plans", f"{stage}.md")
        with open(plan, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest()
        with open(os.path.join(self.root, "project", "approvals", f"{stage}.plan.sha256"), "w") as f:
            f.write(f"{h}  project/plans/{stage}.md  2026-01-01T00:00:00Z  test\n")

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def run_gate(root, tool, tool_input, agent=None, cwd=None, raw=None):
    data = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
            "cwd": cwd or root, "session_id": "test"}
    if agent:
        data["agent_type"] = agent
        data["agent_id"] = "a1"
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root)
    p = subprocess.run([sys.executable, GATE], input=raw if raw is not None else json.dumps(data),
                       capture_output=True, text=True, env=env, timeout=20)
    return p.returncode, p.stderr.strip()


class GateTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture("7")
        self.root = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def write(self, rel, agent=None):
        return run_gate(self.root, "Write", {"file_path": os.path.join(self.root, rel),
                                             "content": "x"}, agent)

    def bash(self, cmd, agent=None, cwd=None):
        return run_gate(self.root, "Bash", {"command": cmd}, agent, cwd)

    def commit_evals(self):
        d = os.path.join(self.root, "evals", "l0")
        os.makedirs(d, exist_ok=True)
        import importlib.util
        spec = importlib.util.spec_from_file_location("gate_mod", GATE)
        gate_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate_mod)   # safe: gate.py only runs main() under __main__
        for n in (*gate_mod.EVAL_SCRIPTS, "common.py", "redact.py"):
            with open(os.path.join(d, n), "w") as f:
                f.write("x\n")
        for args in (["init", "-q"], ["add", "evals"],
                     ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fx"]):
            subprocess.run(["git", "-C", self.root, *args], check=True, capture_output=True)

    def assertBlocked(self, res, msg=None):
        code, err = res
        self.assertEqual(code, 2, f"expected block, got {code} {err} {msg or ''}")
        self.assertIn("GATE BLOCKED", err)
        print(f"      blocked: {err}")

    def assertAllowed(self, res, msg=None):
        code, err = res
        self.assertEqual(code, 0, f"expected allow, got {code}: {err} {msg or ''}")

    # ---- section 11 required tests -------------------------------------------------
    def test_01_phase7_write_blocked_without_approval(self):
        self.assertBlocked(self.write("phase7/x.py", "developer"))

    def test_02_phase7_write_passes_after_approval_then_blocked_after_plan_edit(self):
        self.fx.approve("7")
        self.assertAllowed(self.write("phase7/x.py", "developer"))
        self.fx.write_plan("7", "# Stage plan\n\nbody edited after approval\n")
        self.assertBlocked(self.write("phase7/x.py", "developer"))

    def test_03_evaluator_cannot_edit_phase7(self):
        self.fx.approve("7")
        self.assertBlocked(self.write("phase7/x.py", "evaluator"))
        self.assertAllowed(self.write("evals/metrics.py", "evaluator"))

    def test_04_developer_cannot_edit_evals(self):
        self.fx.approve("7")
        self.assertBlocked(self.write("evals/m.py", "developer"))
        self.assertBlocked(run_gate(self.root, "Edit", {"file_path": os.path.join(self.root, "evals/m.py"),
                                                       "old_string": "a", "new_string": "b"}, "developer"))

    def test_05_developer_cannot_read_holdout(self):
        self.assertBlocked(run_gate(self.root, "Read",
                                    {"file_path": os.path.join(self.root, "datasets/holdout/a.json")}, "developer"))
        self.assertBlocked(run_gate(self.root, "Grep", {"pattern": "cause", "path": "datasets/holdout"}, "developer"))
        self.assertBlocked(run_gate(self.root, "Glob", {"pattern": "datasets/holdout/**"}, "developer"))
        self.assertBlocked(self.bash("cat datasets/holdout/a.json", "developer"))
        self.assertAllowed(run_gate(self.root, "Read",
                                    {"file_path": os.path.join(self.root, "datasets/holdout/a.json")}, "evaluator"))

    def test_06_only_lab_ops_runs_terraform_apply(self):
        cmd = "scripts/labenv terraform -chdir=infra/terraform apply"
        self.assertBlocked(self.bash(cmd))                    # lead
        self.assertBlocked(self.bash(cmd, "developer"))
        self.assertBlocked(self.bash(cmd, "lab-ops"))         # no approval yet
        self.fx.approve("7")
        self.commit_evals()
        self.assertBlocked(self.bash(cmd))
        self.assertBlocked(self.bash(cmd, "developer"))
        self.assertAllowed(self.bash(cmd, "lab-ops"))
        self.assertBlocked(self.bash("scripts/labenv terraform -chdir=infra/terraform plan", "developer"))
        self.assertAllowed(self.bash("scripts/labenv terraform -chdir=infra/terraform plan", "lab-ops"))
        self.assertBlocked(self.bash("scripts/labenv python3 -I -m evals.l0.pods_check x", "evaluator"))
        self.assertAllowed(self.bash("scripts/labenv evals/l0/ping_check.sh 3", "evaluator"))
        self.assertBlocked(self.bash("scripts/labenv printenv", "evaluator"))
        self.assertBlocked(self.bash("scripts/labenv python3 -c x", "evaluator"))
        self.assertBlocked(self.bash("scripts/labenv evals/l0/../../infra/lab.sh up", "evaluator"))
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
        for c in ("cat .env.*", "cat .env*", "cat .env.?ab", "set -a; . ./.env.*"):
            self.assertBlocked(self.bash(c, "evaluator"))
        self.assertBlocked(self.bash("scripts/labenv evals/l0/newthing.sh", "evaluator"))
        self.assertAllowed(self.bash("scripts/labenv python3 -I evals/l0/pods_check.py x", "evaluator"))
        with open(os.path.join(self.root, "evals", "l0", "ping_check.sh"), "a") as f:
            f.write("changed\n")
        self.assertBlocked(self.bash("scripts/labenv evals/l0/ping_check.sh 3", "evaluator"))

    # ---- extra coverage -------------------------------------------------------------
    def test_10_bash_write_targets(self):
        self.assertBlocked(self.bash("echo x > phase7/y.py", "developer"))
        self.assertBlocked(self.bash("sed -i 's/a/b/' .claude/settings.json"))
        self.assertBlocked(self.bash("printf x | tee -a evals/m.py", "developer"))
        self.assertBlocked(self.bash("cd phase7 && echo x > ../evals/m.py", "developer"))
        self.fx.approve("7")
        self.assertAllowed(self.bash("echo x > phase7/y.py 2>/dev/null", "developer"))
        self.assertAllowed(self.bash("mkdir -p project/reports/7/eval", "evaluator"))

    def test_11_heredoc_body_is_not_parsed_as_commands(self):
        self.fx.approve("7")
        cmd = "cat > phase7/z.py <<'EOF'\nprint('a > /etc/passwd')\nrm -rf /\nEOF"
        self.assertAllowed(self.bash(cmd, "developer"))

    def test_12_path_escapes(self):
        self.fx.approve("7")
        self.assertBlocked(self.write("phase7/../evals/m.py", "developer"))
        os.symlink(os.path.join(self.root, "evals"), os.path.join(self.root, "phase7", "link"))
        self.assertBlocked(self.write("phase7/link/m.py", "developer"))
        self.assertBlocked(run_gate(self.root, "Write", {"file_path": "/etc/cron.d/x", "content": "x"}, "developer"))

    def test_13_fail_closed(self):
        os.remove(os.path.join(self.root, "project", "STAGE"))
        self.assertBlocked(self.write("project/notes/7.md", "developer"))
        self.fx.set_stage("banana")
        self.assertBlocked(self.write("project/notes/7.md", "developer"))
        self.assertBlocked(run_gate(self.root, "Write", {}, raw="{not json"))
        self.assertBlocked(run_gate(self.root, "Write", {}, raw='{"tool_name": "Write"}'))
        self.assertBlocked(run_gate(self.root, "WebFetch", {"url": "https://example.com"}))

    def test_14_unknown_agent_is_read_only(self):
        self.fx.approve("7")
        self.assertBlocked(self.write("phase7/x.py", "general-purpose"))
        self.assertBlocked(self.bash("touch phase7/x.py", "general-purpose"))
        self.assertAllowed(self.bash("ls phase7", "general-purpose"))

    def test_15_approvals_and_secrets_untouchable(self):
        self.fx.approve("7")
        self.assertBlocked(self.write("project/approvals/7.plan.sha256"))
        self.assertBlocked(self.bash("ls project/approvals"))
        self.assertBlocked(self.bash("bash scripts/approve.sh 7 plan"))
        self.assertBlocked(self.bash("cat .env.lab", "lab-ops"))
        self.assertBlocked(run_gate(self.root, "Read", {"file_path": os.path.join(self.root, ".env.lab")}, "lab-ops"))

    def test_16_process_paths_need_no_approval_but_respect_scope(self):
        self.assertAllowed(self.write("project/plans/8.md", "phase-planner"))
        self.assertAllowed(self.write("project/notes/7.md", "developer"))
        self.assertAllowed(self.write("project/reports/7/telco.md", "telco-reviewer"))
        self.assertBlocked(self.write("project/reports/7/security.md", "telco-reviewer"))
        self.assertAllowed(self.write("project/STATUS.md"))
        self.assertBlocked(self.write("project/plans/7.md", "developer"))

    def test_17_lead_has_no_product_scope_after_w0(self):
        self.fx.approve("7")
        self.assertBlocked(self.write("phase7/x.py"))
        self.assertBlocked(self.write("README.md"))

    def test_18_w0_lead_scope_and_gate_files(self):
        self.fx.set_stage("W0")
        self.fx.write_plan("W0", "# W0\n")
        self.assertBlocked(self.write(".claude/hooks/gate.py"))   # W0 not yet approved
        self.fx.approve("W0")
        self.assertAllowed(self.write(".claude/hooks/gate.py"))
        self.assertBlocked(self.write("phase7/x.py"))
        self.fx.set_stage("L0")
        self.fx.write_plan("L0", "# L0\n")
        self.fx.approve("L0")
        self.assertBlocked(self.write(".claude/hooks/gate.py"))
        self.assertBlocked(self.write("scripts/approve.sh"))
        self.assertBlocked(self.write("docs/roadmap/other.pdf", "docs-writer"))

    def test_19_kubectl_rules(self):
        self.assertAllowed(self.bash("kubectl -n neoncore get pods"))
        self.assertAllowed(self.bash("kubectl -n neoncore logs deploy/amf --tail=50", "telco-reviewer"))
        self.assertAllowed(self.bash("kubectl -n neoncore exec deploy/tracer -- ls -la /pcaps"))
        self.assertBlocked(self.bash("kubectl -n neoncore delete pod -l app=ue", "developer"))
        self.assertBlocked(self.bash("kubectl apply -f phase2/manifests/03-nfs.yaml", "developer"))
        self.assertBlocked(self.bash("python3 -m phase6.cli --scenario initial-registration --msisdn 0000000100"))
        self.fx.approve("7")
        self.assertAllowed(self.bash("kubectl -n neoncore delete pod -l app=ue", "developer"))
        self.assertAllowed(self.bash("python3 -m phase6.cli --scenario initial-registration --msisdn 0000000100", "developer"))
        self.assertBlocked(self.bash("kubectl apply -f phase2/manifests/03-nfs.yaml", "developer"))
        self.assertAllowed(self.bash("kubectl apply -f phase2/manifests/03-nfs.yaml", "lab-ops"))
        self.assertBlocked(self.bash("kubectl -n kube-system delete pod x", "developer"))
        self.assertBlocked(self.bash("kubectl label node n1 a=b", "developer"))
        self.assertBlocked(self.bash("kubectl delete namespace neoncore", "lab-ops"))
        self.assertBlocked(self.bash("ssh ubuntu@lab-node uptime", "developer"))
        self.assertBlocked(self.bash("qm snapshot 9001 golden-l0", "developer"))
        self.assertAllowed(self.bash("qm snapshot 9001 golden-l0", "lab-ops"))

    def test_20_destructive_left_to_user(self):
        self.fx.approve("7")
        for cmd in ("git push --force origin main", "git branch -D stage/7", "git reset --hard HEAD~1",
                    "git rebase -i main", "rm -rf phase7", "terraform destroy", "gh pr create -t x",
                    "git clean -fd"):
            self.assertBlocked(self.bash(cmd, "lab-ops"), cmd)
        scratch = f"/tmp/claude-{os.getuid()}/gatetest"
        self.assertAllowed(self.bash(f"rm -rf {scratch}", "developer"))


class AgentDefinitionTest(unittest.TestCase):
    def test_agents_frontmatter(self):
        for name in AGENTS:
            path = os.path.join(REPO, ".claude", "agents", f"{name}.md")
            self.assertTrue(os.path.isfile(path), path)
            with open(path) as f:
                text = f.read()
            m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
            self.assertTrue(m, f"{name}: no frontmatter")
            fm = dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
            fm = {k.strip(): v.strip() for k, v in fm.items()}
            self.assertEqual(fm.get("name"), name)
            self.assertIn("tools", fm, name)
            tools = [t.strip() for t in fm["tools"].split(",")]
            self.assertNotIn("Agent", tools, name)
            self.assertNotIn("Task", tools, name)
            self.assertEqual(fm.get("memory"), "local", name)
            self.assertIn(fm.get("model"), ("opus", "sonnet", "inherit"), name)

    def test_skills_not_model_invocable(self):
        for s in ("plan-stage", "build-stage", "close-stage", "lab-status"):
            with open(os.path.join(REPO, ".claude", "skills", s, "SKILL.md")) as f:
                text = f.read()
            self.assertIn("disable-model-invocation: true", text, s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
