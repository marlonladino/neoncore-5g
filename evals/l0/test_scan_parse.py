"""Unit tests for scan_parse.py with synthetic nmap XML, NAD JSON and nft text."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scan_parse as sp  # noqa: E402


def xml(proto, services, ports=(), extra=None, host=True):
    p = "".join(f'<port protocol="{proto}" portid="{n}"><state state="{st}" reason="x"/></port>'
                for n, st in ports)
    ex = f'<extraports state="{extra[1]}" count="{extra[0]}"/>' if extra else ""
    h = (f'<host><status state="up"/><address addr="192.0.2.10" addrtype="ipv4"/>'
         f"<ports>{ex}{p}</ports></host>") if host else ""
    return (f'<?xml version="1.0"?><!DOCTYPE nmaprun><nmaprun scanner="nmap" args="nmap" version="7.94">'
            f'<scaninfo type="syn" protocol="{proto}" numservices="1" services="{services}"/>{h}</nmaprun>')


def parse(*docs):
    return [sp.parse_nmap_xml(d) for d in docs]


FULL = "1-65535"
UDP = "53,123,2152,4789,8472,8805,51820-51821"
SCTP = "9999,38412"


class TestScan(unittest.TestCase):
    def test_nonallow_pass(self):
        v = sp.evaluate_scan(parse(xml("tcp", FULL, extra=(65535, "filtered")),
                                   xml("udp", UDP, [(53, "open|filtered")]),
                                   xml("sctp", SCTP, [(38412, "filtered")])), "nonallow")
        self.assertEqual(v["result"], "PASS", v["failures"])
        self.assertEqual(v["open|filtered"]["udp"], [53])

    def test_nonallow_open_tcp(self):
        v = sp.evaluate_scan(parse(xml("tcp", FULL, [(30030, "open")]), xml("udp", UDP), xml("sctp", SCTP)),
                             "nonallow")
        self.assertEqual(v["result"], "FAIL")

    def test_nonallow_missing_udp_scan(self):
        v = sp.evaluate_scan(parse(xml("tcp", FULL), xml("sctp", SCTP)), "nonallow")
        self.assertTrue(any("UDP list" in f for f in v["failures"]))

    def test_partial_tcp(self):
        v = sp.evaluate_scan(parse(xml("tcp", "1-1024"), xml("udp", UDP), xml("sctp", SCTP)), "nonallow")
        self.assertTrue(any("1-65535" in f for f in v["failures"]))

    def test_allow_exact(self):
        ports = [(22, "open"), (6443, "open"), (30030, "open"), (30090, "open")]
        self.assertEqual(sp.evaluate_scan(parse(xml("tcp", FULL, ports)), "allow", "a")["result"], "PASS")
        self.assertEqual(sp.evaluate_scan(parse(xml("tcp", FULL, ports[:3])), "allow", "a")["result"], "FAIL")
        self.assertEqual(sp.evaluate_scan(parse(xml("tcp", FULL, ports + [(10250, "open")])), "allow", "a")["result"],
                         "FAIL")
        self.assertEqual(sp.evaluate_scan(parse(xml("tcp", FULL, ports[:1])), "allow", "b")["result"], "PASS")

    def test_no_host(self):
        v = sp.evaluate_scan(parse(xml("tcp", FULL, host=False), xml("udp", UDP), xml("sctp", SCTP)), "nonallow")
        self.assertEqual(v["result"], "FAIL")

    def test_entity_refused(self):
        bad = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><nmaprun/>'
        with self.assertRaises(sp.ParseError):
            sp.parse_nmap_xml(bad)

    def test_render_has_no_address(self):
        parsed = parse(xml("tcp", FULL, [(22, "open")]))
        v = sp.evaluate_scan(parsed, "allow", "b")
        self.assertNotIn("192.0.2.10", sp.render_scan_txt("allow", "1", "b", v, parsed))


class TestNad(unittest.TestCase):
    def nad(self, cfg):
        return {"items": [{"metadata": {"namespace": "neoncore", "name": "n1"}, "spec": {"config": json.dumps(cfg)}}]}

    def test_lan_master(self):
        self.assertEqual(sp.evaluate_nad(self.nad({"type": "macvlan", "master": "eth0"}), "eth0")["result"], "FAIL")

    def test_no_master(self):
        self.assertEqual(sp.evaluate_nad(self.nad({"type": "ipvlan"}), "ens18")["result"], "FAIL")

    def test_other_nic_ok(self):
        self.assertEqual(sp.evaluate_nad(self.nad({"type": "macvlan", "master": "ogstun"}), "ens18")["result"], "PASS")

    def test_empty(self):
        self.assertEqual(sp.evaluate_nad({"items": []}, "ens18")["result"], "PASS")


NFT = """table inet neoncore_guard {
\tchain prerouting {
\t\ttype filter hook prerouting priority mangle; policy accept;
\t\tiifname "ens18" ct state invalid drop
\t\tiifname "ens18" ct state established,related accept
\t\tiifname "ens18" ip saddr 192.0.2.10 tcp dport { 22, 6443, 30030, 30090 } ct state new accept
\t\tiifname "ens18" ct state new counter packets 12 bytes 720 drop
\t}
}
"""


class TestNft(unittest.TestCase):
    def test_pass(self):
        self.assertEqual(sp.evaluate_nft(NFT)["result"], "PASS")

    def test_absent(self):
        self.assertEqual(sp.evaluate_nft("table ip nat {\n}\n")["result"], "FAIL")

    def test_wrong_priority(self):
        self.assertEqual(sp.evaluate_nft(NFT.replace("priority mangle", "priority filter"))["result"], "FAIL")


if __name__ == "__main__":
    unittest.main()
