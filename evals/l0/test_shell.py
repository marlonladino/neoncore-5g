"""Functional tests for the evaluator shell scripts with fake kubectl / lab.sh.

No cluster and no lab: a fake `kubectl` on PATH answers the few calls the scripts make,
and tls_negative.sh runs inside a throwaway copy of evals/l0 next to a fake
scripts/labenv and infra/lab.sh. Slow test (ping_check waits 2 x 25 s by design) is
skipped unless L0_SLOW_TESTS=1.
"""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

FAKE_KUBECTL = r"""#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
state = os.environ["FAKE_STATE"]
def n3():
    try:
        return json.load(open(state))
    except Exception:
        return {"in": 100, "out": 90}
if a[:2] == ["get", "--raw"]:
    s = n3()
    key = "in" if "indatapkt" in a[2] else "out"
    print(json.dumps({"status": "success", "data": {"result": [{"metric": {"nf": "upf"}, "value": [0, str(s[key])]}]}}))
elif a[:5] == ["-n", "neoncore", "get", "pod", "-l"] and "app=tracer" in a:
    print(os.environ.get("FAKE_TRACER", "tracer-abc12-x9z"), end="")
elif "exec" in a and "sh" in a and "-c" in a and os.environ.get("FAKE_PCAPS"):
    # In-pod snippet (PICK_NEWEST / TRACER_TIMES): run it locally, /pcaps -> FAKE_PCAPS.
    import subprocess
    i = a.index("-c")
    snippet, args = a[i + 1], a[i + 2:]
    real = os.environ["FAKE_PCAPS"]
    args = [x.replace("/pcaps", real, 1) if x.startswith("/pcaps") else x for x in args]
    r = subprocess.run(["sh", "-c", snippet] + args, capture_output=True, text=True)
    sys.stdout.write(r.stdout.replace(real, "/pcaps"))
elif "exec" in a and a[-3:] == ["ip", "-o", "link"] or ("exec" in a and a[-4:] == ["ip", "-o", "link", "show"]):
    dep = next(x.split("/", 1)[1] for x in a if x.startswith("deploy/"))
    links = json.loads(os.environ.get("FAKE_LINKS", "{}"))
    if dep not in links:
        sys.exit(1)
    print(links[dep])
elif "exec" in a and "ping" in a and "-M" in a:
    print("PING 8.8.8.8 (8.8.8.8) from 10.45.0.2 uesimtun0: 1372(1400) bytes of data.")
    print("3 packets transmitted, 3 received, 0% packet loss, time 2003ms")
elif "exec" in a and "ping" in a:
    s = n3(); s["in"] += 20; s["out"] += int(os.environ.get("FAKE_REPLIES", "20"))
    json.dump(s, open(state, "w"))
    r = int(os.environ.get("FAKE_REPLIES", "20"))
    for i in range(r):
        print(f"64 bytes from 8.8.8.8: icmp_seq={i+1} ttl=115 time={10+i}.0 ms")
    print(f"20 packets transmitted, {r} received, {100-5*r}% packet loss, time 19000ms")
    sys.exit(0 if r else 1)
else:
    sys.exit(1)
"""


def make_exec(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


class TestPickNewest(unittest.TestCase):
    """ping_check.sh tracer-file pick: newest mtime, ties broken by the newest name."""

    def pick_cmd(self):
        with open(os.path.join(HERE, "ping_check.sh"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("PICK_NEWEST='"):
                    return line.rstrip("\n")[len("PICK_NEWEST='"):-1]
        self.fail("PICK_NEWEST not found")

    def pick(self, d):
        r = subprocess.run(["sh", "-c", self.pick_cmd(), "sh", d], capture_output=True, text=True)
        return r.stdout.strip()

    def test_tie_and_order(self):
        d = tempfile.mkdtemp(prefix="pick-")
        names = ["neoncore-20261110-044839.pcap", "neoncore-20261110-045342.pcap",
                 "neoncore-20261110-042605.pcap", "other-20261110-050000.pcap"]
        for n in names:
            open(os.path.join(d, n), "w").close()
            os.utime(os.path.join(d, n), (1000, 1000))
        # Equal mtimes: the newest neoncore name wins, whatever ls -t would do.
        self.assertEqual(self.pick(d), os.path.join(d, "neoncore-20261110-045342.pcap"))
        # A strictly newer mtime wins over the name.
        os.utime(os.path.join(d, names[2]), (2000, 2000))
        self.assertEqual(self.pick(d), os.path.join(d, names[2]))
        for _ in range(5):  # deterministic
            self.assertEqual(self.pick(d), os.path.join(d, names[2]))

    def test_empty_dir(self):
        self.assertEqual(self.pick(tempfile.mkdtemp(prefix="pick-")), "")


def fake_env(d, pcaps=None, **extra):
    bindir = os.path.join(d, "bin")
    os.makedirs(bindir, exist_ok=True)
    make_exec(os.path.join(bindir, "kubectl"), FAKE_KUBECTL)
    # Synthetic data only: no site value can occur, so evidence writes may skip site values.
    env = dict(os.environ, PATH=bindir + ":" + os.environ["PATH"], FAKE_STATE=os.path.join(d, "n3.json"),
               L0_ALLOW_NO_SITE_VALUES="1")
    if pcaps:
        env["FAKE_PCAPS"] = pcaps
    env.update({k: str(v) for k, v in extra.items()})
    return env


class TestTracerFreshness(unittest.TestCase):
    """TB5: the tracer's newest file must be written within 30 s, else GTP-U is not tested."""

    def check(self, ages, tracer="tracer-abc12-x9z"):
        d = tempfile.mkdtemp(prefix="tracer-test-")
        pcaps = os.path.join(d, "pcaps")
        os.makedirs(pcaps)
        now = int(time.time())
        for i, age in enumerate(ages):
            f = os.path.join(pcaps, f"neoncore-20261110-04{i:02d}00.pcap")
            open(f, "w").close()
            os.utime(f, (now - age, now - age))
        r = subprocess.run(["bash", os.path.join(HERE, "ping_check.sh"), "--tracer-check-only"],
                           env=fake_env(d, pcaps, FAKE_TRACER=tracer), capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_fresh(self):
        self.assertEqual(self.check([5]), "tracer: fresh")

    def test_stale_like_r1(self):
        out = self.check([1500, 1800])  # newest file written 25 min ago, as in R1
        self.assertTrue(out.startswith("tracer: not tested: tracer stale (last write "), out)
        self.assertIn("limit 30 s", out)

    def test_boundary(self):
        self.assertEqual(self.check([20]), "tracer: fresh")
        self.assertTrue(self.check([45]).startswith("tracer: not tested: tracer stale"))

    def test_no_files_and_bad_pod(self):
        self.assertEqual(self.check([]), "tracer: not tested: tracer pcap name not recognised")
        self.assertEqual(self.check([5], tracer="evil;pod"), "tracer: not tested: tracer pod not recognised")


IPLINK = ("1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode DEFAULT\\    link/loopback 00:00:00:00:00:00\n"
          "2: eth0@if17: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1450 qdisc noqueue state UP mode DEFAULT\\    link/ether 02:00:00:00:00:01\n")


class TestMtuCheck(unittest.TestCase):
    """TB6: pod MTUs via `ip -o link show`, node commands printed for lab-ops."""

    def run_mtu(self, links):
        d = tempfile.mkdtemp(prefix="mtu-test-")
        out = os.path.join(d, "out")
        r = subprocess.run(["bash", os.path.join(HERE, "mtu_check.sh"), "--out-dir", out, "--label", "pre-R2 informational"],
                           env=fake_env(d, FAKE_LINKS=json.dumps(links)), capture_output=True, text=True, timeout=60)
        return r, out

    def test_values_and_absent(self):
        upf = IPLINK + "3: ogstun: <POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UNKNOWN\n"
        ue = IPLINK + "4: uesimtun0: <POINTOPOINT,UP,LOWER_UP> mtu 1300 qdisc fq_codel state UNKNOWN\n"
        r, out = self.run_mtu({"gnb": IPLINK, "upf": upf, "ue": ue})
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(out, "mtu.txt")) as f:
            t = f.read()
        for line in ("mtu_label: pre-R2 informational", "mtu_pod_gnb_eth0: 1450", "mtu_pod_upf_eth0: 1450",
                     "mtu_pod_upf_ogstun: 1500", "mtu_pod_ue_eth0: 1450", "mtu_pod_ue_uesimtun0: 1300",
                     "mtu_vm_nic: not captured", "mtu_flannel.1: not captured", "mtu_cni0: not captured"):
            self.assertIn(line, t)
        self.assertIn("note_uesimtun0: 1300, not the SMF mtu 1400", t)

    def test_missing_iface_and_failed_exec(self):
        r, out = self.run_mtu({"gnb": IPLINK, "ue": IPLINK + "4: uesimtun0: <UP> mtu 1400 qdisc x\n"})
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(out, "mtu.txt")) as f:
            t = f.read()
        self.assertIn("mtu_pod_upf_ogstun: unavailable (exec failed)", t)
        self.assertIn("mtu_pod_ue_uesimtun0: 1400", t)
        self.assertNotIn("note_uesimtun0", t)
        r, out = self.run_mtu({"gnb": IPLINK, "upf": IPLINK, "ue": IPLINK})
        with open(os.path.join(out, "mtu.txt")) as f:
            self.assertIn("mtu_pod_upf_ogstun: absent", f.read())

    def test_node_commands(self):
        r = subprocess.run(["bash", os.path.join(HERE, "mtu_check.sh"), "--print-node-commands"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)
        cmd = [l for l in r.stdout.splitlines() if not l.startswith("#")]
        self.assertEqual(len(cmd), 1)
        sysfs = tempfile.mkdtemp(prefix="sysfs-")
        os.makedirs(os.path.join(sysfs, "class", "net", "flannel.1"))
        with open(os.path.join(sysfs, "class", "net", "flannel.1", "mtu"), "w") as f:
            f.write("1450\n")
        n = subprocess.run(["sh", "-c", cmd[0]], env=dict(os.environ, SYSFS=sysfs), capture_output=True, text=True)
        self.assertIn("mtu_flannel.1: 1450", n.stdout)
        self.assertIn("mtu_cni0: absent", n.stdout)
        self.assertRegex(n.stdout, r"mtu_vm_nic \(.*\): ")


@unittest.skipUnless(os.environ.get("L0_SLOW_TESTS") == "1", "slow (about 50 s); set L0_SLOW_TESTS=1")
class TestPingCheckStaleTracer(unittest.TestCase):
    def test_stale_tracer_not_tested_and_pmtu(self):
        d = tempfile.mkdtemp(prefix="ping-stale-")
        pcaps = os.path.join(d, "pcaps")
        os.makedirs(pcaps)
        f = os.path.join(pcaps, "neoncore-20261110-044839.pcap")
        with open(f, "wb") as fh:
            fh.write(b"x" * 100)
        old = time.time() - 1500
        os.utime(f, (old, old))
        out = os.path.join(d, "out")
        r = subprocess.run(["bash", os.path.join(HERE, "ping_check.sh"), "--out-dir", out, "--k", "1",
                            "--scratch", os.path.join(d, "scratch"), "--prom", "kube", "--pmtu"],
                           env=fake_env(d, pcaps, FAKE_REPLIES=20), capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)  # E2 result itself unaffected
        g = json.load(open(os.path.join(out, "ping-gtpu.json")))["runs"][0]
        self.assertTrue(g["status"].startswith("not tested: tracer stale"), g)
        self.assertNotIn("gtp_icmp_frames", g)
        e = json.load(open(os.path.join(out, "ping-n3.json")))["runs"][0]
        self.assertEqual(e["pmtu_informational"]["received"], 3)
        self.assertEqual(e["result"], "PASS")


@unittest.skipUnless(os.environ.get("L0_SLOW_TESTS") == "1", "slow (about 50 s); set L0_SLOW_TESTS=1")
class TestPingCheck(unittest.TestCase):
    def run_ping(self, replies):
        d = tempfile.mkdtemp(prefix="ping-test-")
        env = fake_env(d, FAKE_REPLIES=replies)
        out = os.path.join(d, "out")
        r = subprocess.run(["bash", os.path.join(HERE, "ping_check.sh"), "--out-dir", out, "--k", "1",
                            "--scratch", os.path.join(d, "scratch"), "--prom", "kube", "--no-gtpu"],
                           env=env, capture_output=True, text=True, timeout=120)
        return r, out

    def test_pass_and_fail(self):
        r, out = self.run_ping(20)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        e = json.load(open(os.path.join(out, "ping-n3.json")))["runs"][0]
        self.assertEqual((e["received"], e["n3_in_delta"], e["n3_out_delta"]), (20, 20, 20))
        r, out = self.run_ping(17)
        self.assertEqual(r.returncode, 1)
        self.assertIn("17/20 replies < 18", r.stdout)


FAKE_LABENV = "#!/usr/bin/env bash\nexec \"$@\"\n"
FAKE_LAB_OK = """#!/usr/bin/env bash
if [ "${2:-}" = "--selftest-bad-pin" ]; then
    openssl version >/dev/null 2>&1 || true
    echo "lab.sh: TLS fingerprint mismatch, aborting" >&2
    exit 3
fi
/bin/true
exit 0
"""
FAKE_LAB_BAD = """#!/usr/bin/env bash
if [ "${2:-}" = "--selftest-bad-pin" ]; then
    curl --version >/dev/null 2>&1 || true
    echo "lab.sh: fingerprint mismatch: expected AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:AB" >&2
    exit 3
fi
/bin/echo PVEAPIToken=leak >/dev/null
exit 0
"""


@unittest.skipUnless(shutil.which("strace"), "strace not installed")
class TestTlsNegative(unittest.TestCase):
    def fake_repo(self, lab):
        d = tempfile.mkdtemp(prefix="tls-test-")
        repo = os.path.join(d, "repo")
        shutil.copytree(HERE, os.path.join(repo, "evals", "l0"),
                        ignore=shutil.ignore_patterns("__pycache__", "test_*"))
        os.makedirs(os.path.join(repo, "scripts"))
        os.makedirs(os.path.join(repo, "infra"))
        make_exec(os.path.join(repo, "scripts", "labenv"), FAKE_LABENV)
        make_exec(os.path.join(repo, "infra", "lab.sh"), lab)
        subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
        return d, repo

    def run_tls(self, lab):
        d, repo = self.fake_repo(lab)
        out = os.path.join(d, "tls-out")
        r = subprocess.run(["bash", os.path.join(repo, "evals", "l0", "tls_negative.sh"),
                            "--scratch", os.path.join(d, "scratch"), "--out-dir", out],
                           capture_output=True, text=True, timeout=120)
        return r, out, d

    def test_pass(self):
        r, out, d = self.run_tls(FAKE_LAB_OK)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        neg = open(os.path.join(out, "negative.txt")).read()
        self.assertIn("result: PASS", neg)
        self.assertIn("terraform_execve: 0", neg)
        self.assertIn("openssl", neg)
        self.assertNotIn("aborting", neg)        # command output itself never copied
        self.assertEqual(os.listdir(os.path.join(d, "scratch")), [])  # raw traces deleted

    def test_fail_on_curl_fingerprint_and_token(self):
        r, out, _ = self.run_tls(FAKE_LAB_BAD)
        self.assertEqual(r.returncode, 1)
        neg = open(os.path.join(out, "negative.txt")).read()
        pos = open(os.path.join(out, "positive.txt")).read()
        self.assertIn("terraform/curl execve in the negative run", neg)
        self.assertIn("a fingerprint-like string was printed", neg)
        self.assertIn("PVEAPIToken found in the positive trace", pos)
        self.assertNotIn("AB:CD:EF", neg + pos)


class TestE6SelfClean(unittest.TestCase):
    def test_evaluator_files_do_not_match(self):
        pat = "w[s]l|w[i]ndows|\\.w[s]lconfig|/mnt/[a-z]/|p[o]wershell|\\.e[x]e\\b"
        r = subprocess.run(["grep", "-n", "-I", "-i", "-E", pat, "-r", HERE, "--exclude-dir=__pycache__"],
                           capture_output=True, text=True)
        self.assertEqual(r.stdout, "", "evaluator files would fail E6(a)")


class TestStaticGrepArgs(unittest.TestCase):
    """--help and unknown arguments must exit before writing anything (2026-11-10 incident:
    `--help` was ignored and the committed R2 evidence was overwritten)."""

    script = os.path.join(HERE, "w" "sl_grep.sh")

    def run_args(self, *args):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        cwd = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cwd, True)
        r = subprocess.run(["bash", self.script, *[a.replace("@OUT", out) for a in args]],
                           capture_output=True, text=True, cwd=cwd, timeout=30)
        return r, out

    def test_help_writes_nothing(self):
        # Without --out-dir the default target is the committed evidence folder, so also
        # check that its files are byte-identical before and after.
        ev = os.path.join(HERE, "..", "..", "project", "reports", "L0", "eval", "w" "sl")

        def snap():
            if not os.path.isdir(ev):
                return {}
            return {n: open(os.path.join(ev, n), "rb").read() for n in sorted(os.listdir(ev))}
        before = snap()
        for a in ("--help", "-h"):
            r, _ = self.run_args(a)
            self.assertEqual(r.returncode, 0, a)
            self.assertIn("usage:", r.stdout)
        self.assertEqual(snap(), before)

    def test_help_with_out_dir_refused(self):
        r, out = self.run_args("--help", "--out-dir", "@OUT")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(os.listdir(out), [])

    def test_unknown_and_incomplete_refused(self):
        for args in (("--bogus",), ("--out-dir",), ("--out-dir", ""), ("--out-dir", "@OUT", "x"),
                     ("x", "--out-dir", "@OUT")):
            r, out = self.run_args(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertEqual(os.listdir(out), [], args)


if __name__ == "__main__":
    unittest.main()
