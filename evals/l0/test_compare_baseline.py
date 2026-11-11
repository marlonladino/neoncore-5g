"""Unit tests for compare_baseline.py (synthetic inputs)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import compare_baseline as cb  # noqa: E402


def wl(*extra, tracer="nicolaka/netshoot:latest", upf="neoncore-upf:2.8.0-metrics"):
    w = [{"ns": "neoncore", "kind": "Deployment", "name": "amf", "container": "amf", "image": "gradiant/open5gs:2.8.0"},
         {"ns": "neoncore", "kind": "Deployment", "name": "upf", "container": "upf", "image": upf},
         {"ns": "neoncore", "kind": "Deployment", "name": "tracer", "container": "tracer", "image": tracer}]
    return {"workloads": w + list(extra),
            "image_ids": [{"image": "nicolaka/netshoot:latest", "container": "tracer",
                           "imageID": "docker-pullable://nicolaka/netshoot@sha256:aa11"}]}


class TestC1(unittest.TestCase):
    def test_equal(self):
        self.assertEqual(cb.c1(wl(), wl())["result"], "PASS")

    def test_missing_extra(self):
        r = cb.c1(wl({"ns": "monitoring", "kind": "Deployment", "name": "grafana", "container": "g", "image": "x"}), wl())
        self.assertEqual(r["result"], "FAIL")
        self.assertTrue(any("missing" in f for f in r["failures"]))

    def test_upf_tag_must_match(self):
        self.assertEqual(cb.c1(wl(), wl(upf="neoncore-upf:2.8.1"))["result"], "FAIL")

    def test_netshoot_pin(self):
        ok = cb.c1(wl(), wl(tracer="nicolaka/netshoot@sha256:aa11"), netshoot_pinned=True)
        self.assertEqual(ok["result"], "PASS", ok["failures"])
        bad = cb.c1(wl(), wl(tracer="nicolaka/netshoot@sha256:bb22"), netshoot_pinned=True)
        self.assertEqual(bad["result"], "FAIL")

    def test_no_baseline(self):
        self.assertEqual(cb.c1(None, wl())["result"], cb.NOT_TESTED)


def ps(scn, items, causes=(), file="f"):
    return {"file": file, "scenario": scn, "V0": True, "V1": True, "items": items,
            "reject_5gmm_causes": list(causes)}


class TestC2(unittest.TestCase):
    B = {"pcaps": [ps("initial-registration", ["5gmm:0x41", "5gmm:0x42", "5gmm:0x43", "pfcp:50"]),
                   ps("registration-reject", ["5gmm:0x41", "5gmm:0x44"], [7])]}

    def test_superset(self):
        r = {"pcaps": [ps("initial-registration", ["5gmm:0x41", "5gmm:0x42", "5gmm:0x43", "pfcp:50", "pfcp:51"]),
                       ps("registration-reject", ["5gmm:0x41", "5gmm:0x44"], [7])]}
        out = cb.c2(self.B, r)
        self.assertEqual(out["result"], "PASS", out["failures"])
        self.assertEqual(out["extra_items_reported"]["f"]["extra_items"], ["pfcp:51"])

    def test_missing_item(self):
        r = {"pcaps": [ps("initial-registration", ["5gmm:0x41", "5gmm:0x42", "5gmm:0x43"]),
                       ps("registration-reject", ["5gmm:0x41", "5gmm:0x44"], [7])]}
        self.assertEqual(cb.c2(self.B, r)["result"], "FAIL")

    def test_cause(self):
        r = {"pcaps": [ps("initial-registration", ["5gmm:0x41", "5gmm:0x42", "5gmm:0x43", "pfcp:50"]),
                       ps("registration-reject", ["5gmm:0x41", "5gmm:0x44"], [11])]}
        self.assertEqual(cb.c2(self.B, r)["result"], "FAIL")

    def test_degraded_baseline(self):
        b = {"pcaps": [ps("registration-reject", ["5gmm:0x41", "5gmm:0x44"], [11])]}
        r = {"pcaps": [ps("registration-reject", ["5gmm:0x41", "5gmm:0x44"], [7])]}
        out = cb.c2(b, r)
        self.assertEqual(out["result"], "PASS", out["failures"])
        self.assertTrue(out["baseline_degraded"])


class TestC3(unittest.TestCase):
    def t(self, sets):
        return {"targets": [{"panel_id": 1, "index": 0, "expr": "e", "label_sets": sets}]}

    def test_hash_ip_uid_dropped(self):
        b = self.t([{"pod": "amf-5d8f7c9b4-abcde", "uid": "u1", "instance": "10.42.0.5:9090", "nf": "amf"}])
        r = self.t([{"pod": "amf-7f9c8d6b5-zzzzz", "uid": "u2", "instance": "10.42.3.9:9090", "nf": "amf"}])
        self.assertEqual(cb.c3(b, r)["result"], "PASS")

    def test_missing_series(self):
        b = self.t([{"nf": "amf"}, {"nf": "smf"}])
        r = self.t([{"nf": "amf"}])
        self.assertEqual(cb.c3(b, r)["result"], "FAIL")


class TestC4(unittest.TestCase):
    B = "kubernetes_server: v1.30.4+k3s1\nopen5gs_upfd: Open5GS daemon v2.8.0\nueransim: UERANSIM v3.3.0\n"

    def test_pass(self):
        self.assertEqual(cb.c4(self.B, self.B, wl(), wl())["result"], "PASS")

    def test_k3s_diff(self):
        r = self.B.replace("v1.30.4", "v1.31.0")
        self.assertEqual(cb.c4(self.B, r)["result"], "FAIL")

    def test_absolute_without_b(self):
        self.assertTrue(cb.c4(None, self.B)["result"].startswith("PASS (absolute"))
        self.assertEqual(cb.c4(None, self.B.replace("2.8.0", "2.7.6"))["result"], "FAIL")


if __name__ == "__main__":
    unittest.main()
