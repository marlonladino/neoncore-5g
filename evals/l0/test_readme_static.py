"""Unit tests for readme_static.py against a synthetic throwaway git repo."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import readme_static as rs  # noqa: E402

GOOD = """# NeonCore 5G

[![ci](https://img.shields.io/badge/x-y-green)](https://example.org)

A 5G standalone core lab: Open5GS and UERANSIM on single-node K3s in a Proxmox VM,
with a TUI, Grafana dashboards and packet captures. It is growing into an AI
troubleshooter for labeled faults.

![TUI demo showing pods and a registration](docs/media/tui-demo.gif)

## Quick start

```bash
scripts/labenv infra/lab.sh up
```

See [the runbook](docs/lab-proxmox.md) and [phase6](phase6/).

## Roadmap

Full plan: [roadmap PDF](docs/roadmap/neoncore-roadmap.pdf)

| Stage | What | Status |
|---|---|---|
| W0 | agent workflow | done |
| L0 | Proxmox lab | in progress |
| 7 | fault injection | planned |
| 8 | dataset | planned |
| 9 | troubleshooter | planned |
| 10 | tools | planned |
| 9B | eval | planned |
| 11 | MCP | planned |
| 12 | release | planned |
"""

META = """# GitHub metadata

## Description

A 5G SA core testbed (Open5GS, UERANSIM, K3s on Proxmox) growing into an AI troubleshooter.

## Topics

- 5g
- open5gs
- ueransim
- kubernetes
"""


class TestReadme(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="readme-test-")
        for p in ("docs/media", "docs/roadmap", "phase6"):
            os.makedirs(os.path.join(self.d, p))
        self.write("docs/media/tui-demo.gif", b"GIF89a" + b"\x00" * 64)
        self.write("docs/roadmap/neoncore-roadmap.pdf", b"%PDF-1.4\n")
        self.write("docs/lab-proxmox.md", b"x\n")
        self.write("phase6/__init__.py", b"")
        self.write("docs/github-metadata.md", META.encode())
        self.write("README.md", GOOD.encode())
        self.git("init", "-q")
        self.git("add", "-A")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def write(self, rel, data):
        with open(os.path.join(self.d, rel), "wb") as f:
            f.write(data)

    def git(self, *args):
        subprocess.run(["git", "-C", self.d] + list(args), check=True, capture_output=True)

    def test_good(self):
        r = rs.check(self.d)
        for k in ("S1", "S3", "S4", "S5", "S6"):
            self.assertTrue(r[k]["pass"], (k, r[k]))
        if shutil.which("file"):
            self.assertTrue(r["S2"]["pass"], r["S2"])
            self.assertEqual(r["result"], "PASS")
        self.assertEqual(r["S6"]["directory_links"], ["phase6"])

    def test_s1_too_long(self):
        self.write("README.md", GOOD.replace("troubleshooter for labeled faults.",
                                             "troubleshooter. " + "word " * 120).encode())
        self.assertFalse(rs.check(self.d)["S1"]["pass"])

    def test_s1_alt_and_urls_not_counted(self):
        r = rs.check(self.d)
        self.assertLess(r["S1"]["prose_words"], 40)

    def test_s3_missing_stage(self):
        self.write("README.md", GOOD.replace("| 9B | eval | planned |\n", "").encode())
        r = rs.check(self.d)
        self.assertEqual(r["S3"]["missing"], ["9B"])

    def test_s3_no_status(self):
        self.write("README.md", GOOD.replace("| 11 | MCP | planned |", "| 11 | MCP | |").encode())
        self.assertIn("11", rs.check(self.d)["S3"]["missing"])

    def test_s4_absent(self):
        self.write("README.md", GOOD.replace("scripts/labenv infra/lab.sh up", "./lab up").encode())
        self.assertFalse(rs.check(self.d)["S4"]["pass"])

    def test_s5_bad_topic(self):
        self.write("docs/github-metadata.md", META.replace("- 5g", "- 5G_SA").encode())
        self.assertFalse(rs.check(self.d)["S5"]["pass"])

    def test_s5_too_long(self):
        self.write("docs/github-metadata.md", META.replace("troubleshooter.", "x" * 400).encode())
        self.assertFalse(rs.check(self.d)["S5"]["pass"])

    def test_s6_untracked(self):
        self.write("README.md", (GOOD + "\n[x](docs/missing.md)\n").encode())
        r = rs.check(self.d)
        self.assertEqual(r["S6"]["unresolved"], ["docs/missing.md"])

    def test_s2_not_gif(self):
        self.write("docs/media/tui-demo.gif", b"not a gif at all")
        if shutil.which("file"):
            self.assertFalse(rs.check(self.d)["S2"]["pass"])


if __name__ == "__main__":
    unittest.main()
