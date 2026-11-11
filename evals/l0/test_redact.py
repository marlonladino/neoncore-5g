"""Unit tests for evals/l0/redact.py. Synthetic values only (RFC 5737 / RFC1918
examples and made-up names); no lab data.

Run: python3 -m unittest discover -s evals/l0 -p 'test_*.py'
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import redact  # noqa: E402

SYN_ENV = {
    "PVE_ENDPOINT": "https://pve-synth.example.internal:8006/",
    "PVE_API_TOKEN": "neoncore@pve!labtok=11111111-2222-3333-4444-555555555555",
    "PVE_TLS_FINGERPRINT": "AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:"
                           "AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89",
    "TF_VAR_node_name": "pve",
    "TF_VAR_vm_id": "417",
    "TF_VAR_pool_id": "synthpool",
    "TF_VAR_datastore_id": "local-lvm",
    "TF_VAR_bridge": "vmbr7",
    "TF_VAR_ipv4_cidr": "192.168.77.50/24",
    "TF_VAR_gateway": "192.168.77.1",
    "TF_VAR_dns_servers": "192.168.77.2,1.1.1.1",
    "TF_VAR_vm_user": "labuser",
    "LAB_ADMIN_CIDR": "192.168.77.10/32",
    "HOME": "/home/synth",
}


def vals(env=SYN_ENV):
    v, n = redact.load_site_values(env=env, include_self_hostname=False)
    return v, n


class TestSiteValues(unittest.TestCase):
    def setUp(self):
        self.v, self.n = vals()

    def test_count(self):
        self.assertEqual(self.n, 13)

    def test_endpoint_host_and_url(self):
        out = redact.redact("curl https://pve-synth.example.internal:8006/api2/json/version\n"
                            "host pve-synth.example.internal\n", self.v, fmt="text")
        self.assertNotIn("pve-synth", out)
        self.assertIn("<pve-endpoint>", out)
        self.assertIn("<pve-host>", out)

    def test_token_parts(self):
        t = ("Authorization: PVEAPIToken=neoncore@pve!labtok=11111111-2222-3333-4444-555555555555\n"
             "secret 11111111-2222-3333-4444-555555555555\n")
        out = redact.redact(t, self.v, fmt="text")
        self.assertNotIn("11111111-2222", out)
        self.assertNotIn("labtok", out)

    def test_fingerprint_variants(self):
        fp = SYN_ENV["PVE_TLS_FINGERPRINT"]
        for form in (fp, fp.lower(), fp.replace(":", ""), fp.replace(":", "").lower()):
            out = redact.redact(f"sha256 Fingerprint={form}\n", self.v, fmt="text")
            self.assertIn("<fingerprint>", out, form[:8])
            self.assertNotIn("EF:01:23", out.upper())

    def test_cidrs_and_ips(self):
        out = redact.redact("vm 192.168.77.50/24 gw 192.168.77.1 dns 192.168.77.2 admin 192.168.77.10/32\n",
                            self.v, fmt="text")
        self.assertNotIn("192.168.77", out)
        self.assertIn("<vm-cidr>", out)
        self.assertIn("<admin-cidr>", out)

    def test_ip_boundary(self):
        # 192.168.77.5 is a different host than .50; must still be redacted (step 3) but
        # not mistaken for the VM placeholder.
        out = redact.redact("a 192.168.77.5 b 192.168.77.500\n", self.v, fmt="text")
        self.assertNotIn("<vm>", out)
        self.assertNotIn("192.168.77.5 ", out)

    def test_weak_values_contextual(self):
        t = ("GET /nodes/pve/qemu/417/status\n"
             '{"vmid":417,"pool":"synthpool"}\n'
             "PING 8.8.8.8: 417 bytes; 0% loss over 417 ms\n"
             "storage: local-lvm\n"
             "namespace neoncore local storage stays\n")
        out = redact.redact(t, self.v, fmt="text")
        self.assertIn("/nodes/<site:TF_VAR_node_name>/qemu/<site:TF_VAR_vm_id>/", out)
        self.assertIn("417 bytes", out)          # bare number untouched
        self.assertIn("over 417 ms", out)
        self.assertNotIn("synthpool", out)       # 9 chars, plain match
        self.assertIn("storage: <site:TF_VAR_datastore_id>", out)
        self.assertIn("namespace neoncore local storage", out)

    def test_weak_value_quoted_after_space(self):
        # Terraform provider warning form: keyword, space, then a quoted value (R2 E5 log).
        t = ('timeout while waiting for the QEMU agent on VM "417" to publish\n'
             "vm '417' and vmid \"417\" and VM  \"417\"\n"
             "PING: \"417\" bytes\n")
        out = redact.redact(t, self.v, fmt="text")
        self.assertIn('on VM "<site:TF_VAR_vm_id>" to publish', out)
        self.assertIn("vm '<site:TF_VAR_vm_id>' and vmid \"<site:TF_VAR_vm_id>\"", out)
        self.assertIn('VM  "<site:TF_VAR_vm_id>"', out)
        self.assertIn('PING: "417" bytes', out)   # no keyword: untouched
        self.assertEqual(redact.scan(out, self.v), [])
        self.assertNotEqual(redact.scan(t, self.v), [])   # the scan catches the raw form too

    def test_bridge_and_user(self):
        out = redact.redact("bridge=vmbr7 AllowUsers labuser\n", self.v, fmt="text")
        self.assertNotIn("vmbr7", out)
        self.assertNotIn("labuser", out)

    def test_extra_values_and_hostname(self):
        env = dict(SYN_ENV, REDACT_EXTRA_VALUES="DESKTOP-SYNTH42,asset-tag-9")
        v, _ = vals(env)
        out = redact.redact("hostname DESKTOP-SYNTH42 and desktop-synth42 tag asset-tag-9\n", v, fmt="text")
        self.assertNotIn("SYNTH42", out.upper())
        self.assertNotIn("asset-tag-9", out)

    def test_no_values_in_messages(self):
        hits = redact.scan("x 192.168.77.50 y\n", self.v)
        self.assertTrue(hits)
        for _, cat in hits:
            self.assertNotIn("192.168", cat)

    def test_spec_clause_not_an_address(self):
        ip_cat = "non-allowlisted RFC1918 IPv4"
        clean = [
            "(0x0010; TS 24.501 §9.11.4.6, TS 24.008 §10.5.6.3).\n",   # telco.md line 280
            "see clause 10.5.6.3 of the spec\n",
            "subclause 10.5.6.3\n",
            "TS 24.008 10.5.6.3 says\n",
            "clauses 9.11.4.6 and 10.5.6.3\n",
            "§ 9.11.4.6, 10.5.6.3\n",
        ]
        for t in clean:
            self.assertNotIn(ip_cat, [c for _, c in redact.scan(t, self.v)], t)
        flagged = [
            "x 10.5.6.3 y\n",                       # bare: no clause context
            "host 10.99.0.7 is up\n",               # outside documented lab ranges
            "§ 10.5.6.3/24\n",                      # CIDR is never a clause
            "§ 192.168.77.50\n",                    # component >= 100: never exempt
            "§ 172.16.5.4\n",
            "clause 9.11.4.6\nhost 10.5.6.3\n",     # context is per line
            "TS 24.008 §10.5.6.3 and then 10.99.0.7 later on the line\n",
        ]
        for t in flagged:
            self.assertIn(ip_cat, [c for _, c in redact.scan(t, self.v)], t)
        # 10.45.0.7 is inside the documented UE pool (10.45.0.0/16), so it is allowed,
        # with or without clause context; that is unchanged.
        self.assertEqual(redact.scan("ue 10.45.0.7\n", self.v), [])
        # Redaction stays fail-closed: the clause exemption is scan-only.
        self.assertIn("<ip>", redact.redact("§10.5.6.3\n", self.v, fmt="text"))


class TestStructure(unittest.TestCase):
    def setUp(self):
        self.v, _ = vals({})

    def test_pod_json(self):
        pod = {"apiVersion": "v1", "items": [{
            "metadata": {"name": "amf-abc", "namespace": "neoncore",
                         "labels": {"kubernetes.io/hostname": "DESKTOP-XYZ"}},
            "spec": {"nodeName": "DESKTOP-XYZ", "hostname": "amf"},
            "status": {"hostIP": "172.29.10.4", "hostIPs": [{"ip": "172.29.10.4"}],
                       "podIP": "10.42.0.17", "podIPs": [{"ip": "10.42.0.17"}], "phase": "Running"}}]}
        out = redact.redact(json.dumps(pod), self.v)
        self.assertNotIn("DESKTOP-XYZ", out)
        self.assertNotIn("172.29.10.4", out)
        self.assertIn("10.42.0.17", out)       # pod CIDR is allowlisted
        self.assertEqual(json.loads(out)["items"][0]["status"]["phase"], "Running")
        self.assertEqual(redact.scan(out, self.v), [])

    def test_node_addresses_and_annotations(self):
        node = {"kind": "Node", "metadata": {"name": "neoncore-lab", "annotations": {
            "flannel.alpha.coreos.com/public-ip": "192.168.5.9",
            "k3s.io/internal-ip": "192.168.5.9", "k3s.io/hostname": "secret-host"}},
            "status": {"addresses": [{"type": "InternalIP", "address": "192.168.5.9"},
                                     {"type": "Hostname", "address": "secret-host"}]}}
        out = redact.redact(json.dumps(node), self.v)
        self.assertNotIn("192.168.5.9", out)
        self.assertNotIn("secret-host", out)
        self.assertIn("<node-address>", out)

    def test_kubeconfig(self):
        kc = {"kind": "Config", "current-context": "corp-ctx",
              "clusters": [{"name": "corp-cluster", "cluster": {"server": "https://192.168.5.9:6443"}}],
              "contexts": [{"name": "corp-ctx", "context": {"cluster": "corp-cluster", "user": "u"}}]}
        out = redact.redact(json.dumps(kc), self.v)
        self.assertNotIn("corp-", out)
        self.assertNotIn("192.168.5.9", out)

    def test_instance_labels(self):
        series = {"data": {"result": [
            {"metric": {"instance": "10.42.0.9:9090", "nf": "amf"}},
            {"metric": {"instance": "192.168.5.9:10250", "node": "DESKTOP-XYZ"}},
            {"metric": {"instance": "kube-state-metrics.monitoring.svc.cluster.local:8080"}},
            {"metric": {"instance": "DESKTOP-XYZ:9100"}}]}}
        out = json.loads(redact.redact(json.dumps(series), self.v))
        res = out["data"]["result"]
        self.assertEqual(res[0]["metric"]["instance"], "10.42.0.9:9090")
        self.assertEqual(res[1]["metric"]["instance"], "<instance>")
        self.assertEqual(res[1]["metric"]["node"], "<node>")
        self.assertTrue(res[2]["metric"]["instance"].startswith("kube-state-metrics"))
        self.assertEqual(res[3]["metric"]["instance"], "<instance>")

    def test_text_forms(self):
        t = ("Node:         DESKTOP-XYZ/172.29.10.4\n"
             "  InternalIP:  172.29.10.4\n"
             "  Hostname:    DESKTOP-XYZ\n"
             "nodeName: DESKTOP-XYZ\n"
             'up{instance="172.29.10.4:10250",job="kubelet"} 1\n'
             "current-context: corp-ctx\n")
        out = redact.redact(t, self.v, fmt="text")
        self.assertNotIn("DESKTOP-XYZ", out)
        self.assertNotIn("172.29", out)
        self.assertNotIn("corp-ctx", out)
        self.assertEqual(redact.scan(out, self.v), [])

    def test_prose_not_structural(self):
        t = "never restart it on a live node: that would wipe the cluster: bad\n"
        self.assertEqual(redact.redact(t, self.v, fmt="text"), t)
        self.assertEqual(redact.scan(t, self.v), [])
        out = redact.redact("  node: DESKTOP-XYZ\n- cluster: corp\nnode=\"DESKTOP-XYZ\"\n", self.v, fmt="text")
        self.assertNotIn("DESKTOP", out)
        self.assertNotIn("corp", out)

    def test_terraform_reference_not_structural(self):
        # `node_name` is an attribute name in .tf files; `var.node_name` is not a value.
        t = ('resource "x" "lab" {\n  node_name = var.node_name\n'
             '  initialization {\n    node_name    = local.node_name\n  }\n}\n')
        self.assertEqual(redact.redact(t, self.v, fmt="text"), t)
        self.assertEqual(redact.scan(t, self.v), [])

    def test_terraform_reference_fail_closed(self):
        # Literals, quoted "var.x", dotted or hyphenated names and other prefixes stay structural.
        for line in ('node_name = "pve-synth"\n', 'node_name = "var.node_name"\n',
                     "node_name = var.node.example\n", "node_name = var.pve-synth\n",
                     "node_name = data.pve\n", "nodeName: var.x.y\n"):
            out = redact.redact(line, self.v, fmt="text")
            self.assertIn("<node", out, line)
            self.assertNotEqual(redact.scan(line, self.v), [], line)
        # JSON mode (e.g. a plan JSON carrying the real value) is unaffected.
        out = json.loads(redact.redact(json.dumps({"node_name": "var.node_name"}), self.v))
        self.assertEqual(out["node_name"], "<node_name>")
        # The real site value is still caught by step 1 even next to a reference.
        v, _ = vals({"TF_VAR_node_name": "pvesynthnode"})
        t = "node_name = var.node_name\n# deployed on pvesynthnode\n"
        self.assertNotIn("pvesynthnode", redact.redact(t, v, fmt="text"))
        self.assertNotEqual(redact.scan(t, v), [])

    def test_meta_labels(self):
        t = {"discoveredLabels": {"__meta_kubernetes_pod_node_name": "DESKTOP-XYZ",
                                  "__meta_kubernetes_pod_host_ip": "172.29.10.4"}}
        out = redact.redact(json.dumps(t), self.v)
        self.assertNotIn("DESKTOP-XYZ", out)
        self.assertNotIn("172.29", out)


class TestIPs(unittest.TestCase):
    def setUp(self):
        self.v, _ = vals({})

    def test_allowlist_kept(self):
        t = "pod 10.42.1.2 svc 10.43.0.10 ue 10.45.0.3 dns 8.8.8.8 lo 127.0.0.1 nad 192.168.200.50\n"
        self.assertEqual(redact.redact(t, self.v, fmt="text"), t)

    def test_others_replaced(self):
        out = redact.redact("lan 192.168.1.20 docker 172.17.0.1 pub 203.0.113.9 w 10.0.0.5/8\n",
                            self.v, fmt="text")
        self.assertEqual(out, "lan <ip> docker <ip> pub <ip> w <ip>/8\n")

    def test_versions_untouched(self):
        t = "open5gs 2.8.0 k3s v1.30.4+k3s1 tshark 4.2.2 time 23:26:01 sha256:ab12\n"
        self.assertEqual(redact.redact(t, self.v, fmt="text"), t)

    def test_ipv6(self):
        out = redact.redact("v6 2001:db8::1 fd00:1::5 fe80::1 ::1\n", self.v, fmt="text")
        self.assertNotIn("2001:db8", out)
        self.assertNotIn("fd00:1", out)
        self.assertIn("fe80::1", out)

    def test_mac_and_fingerprint_not_ipv6(self):
        t = "mac bc:24:11:aa:bb:cc\n"
        self.assertEqual(redact.redact(t, self.v, fmt="text"), t)


class TestControl(unittest.TestCase):
    def test_ansi_stripped(self):
        v, _ = vals({})
        out = redact.redact("\x1b[31mred\x1b[0m\x07 ok\r\n\x1b]0;title\x07x\n", v, fmt="text")
        # ANSI sequences are removed; the stray BEL becomes a newline (S-I2).
        self.assertEqual(out, "red\n ok\nx\n")

    def test_controls_become_newlines(self):
        v, _ = vals({})
        self.assertEqual(redact.strip_control("a\x00b\x01c\x7fd\u0085e​f"), "a\nb\nc\nd\ne\nf")


class TestSecretClass(unittest.TestCase):
    """Security review S-I2: token and fingerprint forms match as plain substrings."""
    SECRET = "11111111-2222-3333-4444-555555555555"
    FP_HEX = "ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789"

    def setUp(self):
        self.v, _ = vals()

    def assert_clean(self, text, *needles):
        out = redact.redact(text, self.v, fmt="text")
        for n in needles:
            self.assertNotIn(n.lower(), out.lower())
        self.assertEqual(redact.scan(out, self.v), [])
        # The raw text must be flagged by the scanner on its own as well.
        self.assertNotEqual(redact.scan(text, self.v), [])
        return out

    def test_token_followed_by_letter_or_digit(self):
        tok = SYN_ENV["PVE_API_TOKEN"]
        for suffix in ("xyz", "7", "_a", "Z9"):
            self.assert_clean(f"auth {tok}{suffix} done\n", self.SECRET, "labtok")
            self.assert_clean(f"secret={self.SECRET}{suffix}\n", self.SECRET)
            self.assert_clean(f"x{self.SECRET.upper()}{suffix}\n", self.SECRET)

    def test_token_parts(self):
        out = self.assert_clean("user neoncore@pveX id labtokZ\n", "neoncore@pve", "labtok")
        self.assertIn("<token>", out)

    def test_nul_joined_environ(self):
        env = (f"HOME=/home/synth\x00PVE_API_TOKEN={SYN_ENV['PVE_API_TOKEN']}\x00"
               f"PVE_TLS_FINGERPRINT={SYN_ENV['PVE_TLS_FINGERPRINT']}\x00TERM=xterm\x00"
               f"PROXMOX_VE_API_TOKEN=PVEAPIToken={SYN_ENV['PVE_API_TOKEN']}\x00SHELL=/bin/bash\x00")
        out = self.assert_clean(env, self.SECRET, "labtok", "AB:CD:EF:01", self.FP_HEX)
        self.assertNotIn("\x00", out)
        self.assertIn("TERM=xterm", out)

    def test_fingerprint_forms_any_case(self):
        colon = SYN_ENV["PVE_TLS_FINGERPRINT"]
        for form in (colon, colon.lower(), self.FP_HEX, self.FP_HEX.lower()):
            self.assert_clean(f"pin {form}abc\n", self.FP_HEX, colon)
            self.assert_clean(f"pin9{form}9\n", self.FP_HEX, colon)

    def test_header_prefixed_token_value(self):
        env = dict(SYN_ENV, PVE_API_TOKEN="PVEAPIToken=" + SYN_ENV["PVE_API_TOKEN"])
        v, _ = vals(env)
        kinds = {sv.name for sv in v if sv.mode == "secret"}
        self.assertTrue({"PVE_API_TOKEN#full", "PVE_API_TOKEN#secret", "PVE_API_TOKEN#user"} <= kinds)
        out = redact.redact(f"a neoncore@pveQ b {self.SECRET}Q c PVEAPIToken header\n", v, fmt="text")
        self.assertNotIn(self.SECRET, out)
        self.assertNotIn("neoncore@pve", out)
        self.assertIn("PVEAPIToken header", out)  # the header word alone is not a value

    def test_weak_token_id_stays_contextual(self):
        env = dict(SYN_ENV, PVE_API_TOKEN="neoncore@pve!lab=" + self.SECRET)
        v, _ = vals(env)
        out = redact.redact(f"the lab is fine; neoncore pods ok; key {self.SECRET}x\n", v, fmt="text")
        self.assertIn("the lab is fine", out)
        self.assertNotIn(self.SECRET, out)


class TestInputRefusal(unittest.TestCase):
    """Security review S-I2: /proc, /sys, /dev and non-regular inputs are refused."""

    def run_cli(self, args, stdin=""):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/home/synth", **SYN_ENV}
        return subprocess.run([sys.executable, "-I", os.path.join(HERE, "redact.py")] + args,
                              input=stdin, capture_output=True, text=True, env=env)

    def test_proc_self_environ_refused(self):
        for args in (["--stdout", "/proc/self/environ"], ["--scan", "/proc/self/environ"],
                     ["-o", os.path.join(tempfile.mkdtemp(prefix="redact-ref-"), "o.txt"),
                      "/proc/self/environ"]):
            r = self.run_cli(args)
            self.assertEqual(r.returncode, 2, args)
            self.assertEqual(r.stdout, "")
            self.assertNotIn("environ", r.stderr)  # the path is not echoed
            self.assertNotIn(self.__class__.__name__, r.stderr)

    def test_sys_dev_and_symlink_refused(self):
        d = tempfile.mkdtemp(prefix="redact-ref-")
        link = os.path.join(d, "innocent.txt")
        os.symlink("/proc/self/environ", link)
        for p in ("/sys/kernel/hostname" if os.path.exists("/sys/kernel/hostname") else "/sys/power",
                  "/dev/null", "/dev/stdin", link):
            r = self.run_cli(["--stdout", p])
            self.assertEqual(r.returncode, 2, p)
            self.assertEqual(r.stdout, "")

    def test_non_regular_refused(self):
        d = tempfile.mkdtemp(prefix="redact-ref-")
        fifo = os.path.join(d, "fifo")
        os.mkfifo(fifo)
        for p in (d, fifo):
            r = self.run_cli(["--stdout", p])
            self.assertEqual(r.returncode, 2, p)
        self.assertRaises(redact.InputRefused, redact.read_input, fifo)

    def test_describe_prints_no_values(self):
        r = self.run_cli(["--describe"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PVE_API_TOKEN#secret: 1 secret", r.stdout)
        self.assertIn("secret", r.stdout)
        for name, val in SYN_ENV.items():
            if name != "HOME":
                for part in re.split(r"[=!@:,/]", val):
                    if len(part) >= 4 and part not in ("https", "8006"):
                        self.assertNotIn(part, r.stdout, name)

    def test_regular_file_and_stdin_allowed(self):
        d = tempfile.mkdtemp(prefix="redact-ref-")
        p = os.path.join(d, "in.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("x 192.168.9.9\n")
        r = self.run_cli(["--stdout", p])
        self.assertEqual((r.returncode, r.stdout), (0, "x <ip>\n"))
        r = self.run_cli(["--stdout", "-"], "y 192.168.9.9\n")
        self.assertEqual((r.returncode, r.stdout), (0, "y <ip>\n"))


class TestWriteAndScan(unittest.TestCase):
    def setUp(self):
        self.v, _ = vals()
        self.d = tempfile.mkdtemp(prefix="redact-test-")

    def test_write_clean(self):
        p = os.path.join(self.d, "o.md")
        rc = redact.write_redacted(p, "vm 192.168.77.50 node pve ok\n", self.v)
        self.assertEqual(rc, 0)
        with open(p) as f:
            self.assertNotIn("192.168.77.50", f.read())

    def test_append_keeps_old(self):
        p = os.path.join(self.d, "n.md")
        with open(p, "w") as f:
            f.write("old line")
        self.assertEqual(redact.write_redacted(p, "new 192.168.77.1\n", self.v, append=True), 0)
        with open(p) as f:
            c = f.read()
        self.assertTrue(c.startswith("old line\nnew <site:TF_VAR_gateway>"))

    def test_append_refused_if_old_has_hit(self):
        p = os.path.join(self.d, "bad.md")
        with open(p, "w") as f:
            f.write("leak 192.168.77.50\n")
        rc = redact.write_redacted(p, "fine\n", self.v, append=True)
        self.assertEqual(rc, 3)
        with open(p) as f:   # original left as it was; the new content is not written
            self.assertEqual(f.read(), "leak 192.168.77.50\n")
        self.assertEqual([x for x in os.listdir(self.d) if x.startswith(".redact-")], [])

    def test_post_write_hit_deletes(self):
        # Simulate a redaction bug: redact() returns the raw text. The post-write
        # scan must catch it and delete the file.
        p = os.path.join(self.d, "x.md")
        orig = redact.redact
        try:
            redact.redact = lambda text, values, fmt="auto": text
            rc = redact.write_redacted(p, "vm 192.168.77.50\n", self.v)
        finally:
            redact.redact = orig
        self.assertEqual(rc, 3)
        self.assertFalse(os.path.exists(p))
        self.assertEqual(os.listdir(self.d), [])

    def test_scan_hits(self):
        t = "a 192.168.77.50\nb 10.42.0.1\nnodeName: DESKTOP-X\nc 172.20.0.4\n"
        cats = redact.scan(t, self.v)
        lines = sorted({ln for ln, _ in cats})
        self.assertEqual(lines, [1, 3, 4])


class TestCLI(unittest.TestCase):
    def run_cli(self, args, stdin="", env_extra=None, site=True):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/home/synth"}
        if site:
            env.update(SYN_ENV)
        env.update(env_extra or {})
        return subprocess.run([sys.executable, "-I", os.path.join(HERE, "redact.py")] + args,
                              input=stdin, capture_output=True, text=True, env=env)

    def test_refuses_without_site_values(self):
        r = self.run_cli(["--stdout"], "x\n", site=False)
        self.assertEqual(r.returncode, 4)
        r = self.run_cli(["--stdout", "--allow-no-site-values"], "x 192.168.9.9\n", site=False)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "x <ip>\n")

    def test_common_write_refuses_without_site_values(self):
        # common.write_text (used by every evals/l0 writer) fails closed like the CLI.
        d = tempfile.mkdtemp(prefix="redact-common-")
        out = os.path.join(d, "o.txt")
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import common; "
                "common.write_text(sys.argv[2], 'x 192.168.9.9\\n')")
        base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/home/synth"}
        r = subprocess.run([sys.executable, "-I", "-c", code, HERE, out],
                           capture_output=True, text=True, env=base)
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertFalse(os.path.exists(out))
        for extra in ({"L0_ALLOW_NO_SITE_VALUES": "1"}, SYN_ENV):
            r = subprocess.run([sys.executable, "-I", "-c", code, HERE, out],
                               capture_output=True, text=True, env={**base, **extra})
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(f.read(), "x <ip>\n")
            os.unlink(out)
        # Any other value of the opt-in does not count.
        r = subprocess.run([sys.executable, "-I", "-c", code, HERE, out],
                           capture_output=True, text=True,
                           env={**base, "L0_ALLOW_NO_SITE_VALUES": "yes"})
        self.assertEqual(r.returncode, 4)

    def test_output_and_scan(self):
        d = tempfile.mkdtemp(prefix="redact-cli-")
        out = os.path.join(d, "o.json")
        r = self.run_cli(["-o", out], json.dumps({"spec": {"nodeName": "pve-synth"},
                                                  "ip": "192.168.77.50"}))
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_cli(["--scan", out])
        self.assertEqual(r.returncode, 0, r.stdout)
        bad = os.path.join(d, "bad.txt")
        with open(bad, "w") as f:
            f.write("pve-synth.example.internal 192.168.77.50\n")
        r = self.run_cli(["--scan", bad])
        self.assertEqual(r.returncode, 3)
        self.assertNotIn("192.168.77", r.stdout + r.stderr)
        self.assertNotIn("pve-synth", r.stdout + r.stderr)

    def test_bad_json(self):
        d = tempfile.mkdtemp(prefix="redact-cli-")
        r = self.run_cli(["--format", "json", "-o", os.path.join(d, "o")], "{not json")
        self.assertEqual(r.returncode, 2)
        self.assertFalse(os.path.exists(os.path.join(d, "o")))


if __name__ == "__main__":
    unittest.main()
