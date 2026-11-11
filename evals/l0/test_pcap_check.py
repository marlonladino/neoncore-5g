"""Unit tests for pcap_check.py analysis logic on synthetic parsed rows (no tshark)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pcap_check as pc  # noqa: E402

MSIN = "0000009901"
NAMES = [n for n, _ in pc.FIELDS]


def row(t, **kw):
    r = {n: [] for n in NAMES}
    r["t"] = [str(t)]
    r["protos"] = [kw.pop("protos", "sll:ethertype:ip:sctp:ngap:nas-5gs")]
    r["src"], r["dst"] = [kw.pop("src", "10.42.0.5")], [kw.pop("dst", "10.42.0.6")]
    r["proto"], r["ipid"], r["iplen"] = ["132"], [str(kw.pop("ipid", int(t * 1000)))], ["120"]
    for k, v in kw.items():
        r[k] = v if isinstance(v, list) else [str(v)]
    return r


def nas(t, ran, mm=None, sm=None, **kw):
    d = {"ran_id": str(ran), "tsn": str(int(t * 10))}
    if mm is not None:
        d["mm_type"] = hex(mm)
    if sm is not None:
        d["sm_type"] = hex(sm)
    d.update(kw)
    return row(t, **d)


def pfcp(t, typ, seq, seids=(), ueip=None):
    d = {"protos": "sll:ethertype:ip:udp:pfcp", "pfcp_type": str(typ), "pfcp_seq": str(seq),
         "pfcp_seid": [str(s) for s in seids], "proto": ["17"]}
    if ueip:
        d["pfcp_ueip"] = ueip
    return row(t, **d)


def initial_reg_rows(msin=MSIN, ran=3, with_pfcp=True):
    rows = [
        nas(1.0, ran, mm=0x41, msin=msin, ngap_pc="15"),
        nas(1.5, ran, mm=0x42),
        nas(1.6, ran, mm=0x43),
        nas(1.7, ran, mm=0x67, sm=0xc1),
        nas(1.9, ran, mm=0x68, sm=0xc2, pdu_addr="10.45.0.7"),
        # background ue pod (different RAN id) -- must be ignored
        nas(1.2, 1, mm=0x41, msin="0000000001"),
        nas(1.3, 1, mm=0x44, mm_cause="7"),
    ]
    if with_pfcp:
        rows += [pfcp(1.8, 50, 11, seids=["0", "0x5"], ueip="10.45.0.7"),
                 pfcp(1.85, 51, 11, seids=["0x5", "0x9"])]
    return sorted(rows, key=pc._t)


def run(rows, scenario, b_req=None, msin=MSIN):
    rows, _ = pc.dedup(rows)
    res = pc.analyze(rows, scenario, msin)
    res["V0"] = True
    return pc.verdict(res, scenario, b_req or [])


class TestInitialRegistration(unittest.TestCase):
    def test_valid(self):
        r = run(initial_reg_rows(), "initial-registration")
        self.assertTrue(r["valid"], r["reasons"])
        self.assertEqual(r["pfcp_tie"], "tied")
        self.assertIn("pfcp:50", r["items"])
        self.assertIn("pfcp:51", r["items"])
        self.assertEqual(r["run_ran_ue_ngap_ids"], ["3"])
        self.assertNotIn("5gmm:0x44", r["items"])  # the background UE's reject is not ours

    def test_wrong_msin(self):
        r = run(initial_reg_rows(msin="0000009999"), "initial-registration")
        self.assertFalse(r["valid"])
        self.assertTrue(any("MSIN" in x for x in r["reasons"]))

    def test_missing_complete(self):
        rows = [x for x in initial_reg_rows() if x["mm_type"] != ["0x43"]]
        r = run(rows, "initial-registration")
        self.assertFalse(r["valid"])
        self.assertIn("V2: missing required 5gmm:0x43", r["reasons"])

    def test_pdu_reject_invalid(self):
        rows = initial_reg_rows() + [nas(2.0, 3, mm=0x68, sm=0xc3, sm_cause="27")]
        r = run(rows, "initial-registration")
        self.assertFalse(r["valid"])
        self.assertEqual(r["pdu_reject_5gsm_causes"], [27])

    def test_b_items(self):
        rows = initial_reg_rows(with_pfcp=False)
        r = run(rows, "initial-registration", b_req=["pfcp:50", "pfcp:51"])
        self.assertFalse(r["valid"])
        self.assertEqual(r["pfcp_tie"], "no-pfcp")
        r = run(initial_reg_rows(with_pfcp=False), "initial-registration")
        self.assertTrue(r["valid"])  # B missing -> reported, not required (V3)

    def test_pfcp_untied_without_pdu_address(self):
        rows = [x for x in initial_reg_rows() if x["sm_type"] != ["0xc2"]]
        r = run(rows, "initial-registration")
        self.assertEqual(r["pfcp_tie"], "untied")
        self.assertNotIn("pfcp:50", r["items"])

    def test_pfcp_other_ue_not_tied(self):
        rows = initial_reg_rows(with_pfcp=False) + [pfcp(1.8, 50, 12, seids=["0", "0x6"], ueip="10.45.0.99")]
        r = run(rows, "initial-registration")
        self.assertNotIn("pfcp:50", r["items"])

    def test_ambiguous_frame(self):
        rows = initial_reg_rows() + [nas(2.1, 3, mm=0x44, ran_id=["3", "1"])]
        r = run(rows, "initial-registration")
        self.assertEqual(r["ambiguous_frames"], 1)
        self.assertNotIn("5gmm:0x44", r["items"])


class TestReject(unittest.TestCase):
    def rows(self, cause="7", accept=False):
        rows = [nas(1.0, 4, mm=0x41, msin="0000009902"), nas(1.2, 4, mm=0x44, mm_cause=cause)]
        if accept:
            rows.append(nas(1.3, 4, mm=0x42))
        return rows

    def test_cause7(self):
        r = run(self.rows(), "registration-reject", msin="0000009902")
        self.assertTrue(r["valid"], r["reasons"])
        self.assertEqual(r["reject_5gmm_causes"], [7])

    def test_other_cause(self):
        r = run(self.rows(cause="0x0b"), "registration-reject", msin="0000009902")
        self.assertFalse(r["valid"])

    def test_accept_invalid(self):
        r = run(self.rows(accept=True), "registration-reject", msin="0000009902")
        self.assertFalse(r["valid"])


class TestDeregistration(unittest.TestCase):
    def rows(self, switch_off="0", accept=True, pfcp_del=True, accept_first=False):
        rows = initial_reg_rows()
        t_acc = 2.5 if not accept_first else 2.9
        rows.append(nas(3.0 if not accept_first else 2.95, 3, mm=0x45, switch_off=switch_off))
        if accept:
            rows.append(nas(3.2 if not accept_first else t_acc, 3, mm=0x46))
        rows.append(nas(3.3, 3, ngap_pc="41"))
        if pfcp_del:
            rows += [pfcp(3.4, 54, 20, seids=["0x9"]), pfcp(3.45, 55, 20, seids=["0x5"]),
                     pfcp(3.5, 54, 21, seids=["0x77"])]  # another UE's session
        return [{**r} for r in sorted(rows, key=pc._t)]

    def test_valid_with_b(self):
        r = run(self.rows(), "deregistration", msin=MSIN, b_req=["ngap:41", "pfcp:54", "pfcp:55"])
        self.assertTrue(r["valid"], r["reasons"])
        self.assertEqual(sorted(r["b_items_present"]), ["ngap:41", "pfcp:54", "pfcp:55"])

    def test_switch_off_1(self):
        r = run(self.rows(switch_off="True"), "deregistration")
        self.assertFalse(r["valid"])
        self.assertIn("V2: Deregistration request with switch_off=1", r["reasons"])

    def test_accept_required(self):
        r = run(self.rows(accept=False), "deregistration")
        self.assertFalse(r["valid"])
        self.assertIn("V2: missing required 5gmm:0x46", r["reasons"])


class TestObservations(unittest.TestCase):
    """Report-only fields (telco TB7(b), TA21). They must never change the verdict."""

    def dereg_with_rereg(self, status_cause="101"):
        rows = TestDeregistration().rows()
        # run UE: auth failure #21, SMC with NEA0, accept carries 5G-TMSI 0xc000058f
        rows += [nas(1.1, 3, mm=0x56), nas(1.15, 3, mm=0x59, mm_cause="21"),
                 nas(1.4, 3, mm=0x5d, enc_algo="0")]
        for r in rows:
            if r["mm_type"] == ["0x42"]:
                r["tmsi"], r["type_id"] = ["3221226895"], ["2"]
        rows += [pfcp(2.0, 52, 13, seids=["0x9"]), pfcp(2.05, 53, 13, seids=["0x5"]),
                 # GUTI re-registration of the run UE on RAN 6, then 5GMM STATUS
                 nas(4.0, 6, mm=0x41, type_id="2", tmsi="3221226895", reg_type="1", ngap_pc="15", num="545"),
                 nas(4.2, 6, mm=0x5d, enc_algo="0"),
                 nas(4.5, 6, mm=0x64, mm_cause=status_cause),
                 # another SUCI UE (background) with its own auth failure
                 nas(4.6, 2, mm=0x41, type_id="1", msin="0000000001", reg_type="1"),
                 nas(4.7, 2, mm=0x59, mm_cause="20")]
        return sorted(rows, key=pc._t)

    def test_guti_reregistration_and_causes(self):
        r = run(self.dereg_with_rereg(), "deregistration")
        self.assertTrue(r["valid"], r["reasons"])
        o = r["observations"]
        self.assertTrue(o["report_only"])
        self.assertEqual(o["run_ue_assigned_5g_tmsi"], ["0xc000058f"])
        self.assertTrue(o["run_ue_guti_reregistration"])
        self.assertEqual(o["run_ue_guti_reregistration_ran_ids"], ["6"])
        ids = {x["ran_ue_ngap_id"]: x for x in o["other_ue_ngap_ids"]}
        self.assertEqual(ids["6"]["identity_type"], "5G-GUTI")
        self.assertEqual(ids["6"]["first_frame"], 545)
        self.assertEqual(ids["2"]["identity_type"], "SUCI")
        self.assertTrue(ids["2"]["suci_msin_present"])
        self.assertEqual(o["5gmm_status_causes"], {"run_ue": [], "other": [101]})
        self.assertEqual(o["auth_failure_causes"], {"run_ue": [21], "other": [20]})
        ta = o["ta21"]
        self.assertIs(ta["nea0_selected_in_every_smc"], True)
        self.assertEqual(ta["pfcp_52_53"], {"52": True, "53": True})
        self.assertIs(ta["accept_before_complete"], True)
        self.assertEqual(r["run_ran_ue_ngap_ids"], ["3"])  # tie unchanged by the GUTI UE

    def test_other_guti_not_run_ue(self):
        rows = self.dereg_with_rereg()
        for x in rows:
            if x["ran_id"] == ["6"] and x["mm_type"] == ["0x41"]:
                x["tmsi"] = ["3221220000"]
        o = run(rows, "deregistration")["observations"]
        self.assertFalse(o["run_ue_guti_reregistration"])

    def test_observations_do_not_change_verdict(self):
        base = run(TestDeregistration().rows(), "deregistration")
        r = run(self.dereg_with_rereg(), "deregistration")
        self.assertEqual((base["valid"], base["items"]), (r["valid"], [i for i in r["items"] if i in base["items"]]))
        self.assertNotIn("pfcp:52", r["items"])  # report-only, never an item
        self.assertNotIn("pfcp:53", r["items"])

    def test_nea_other_than_0_reported(self):
        rows = self.dereg_with_rereg()
        rows.append(nas(1.45, 3, mm=0x5d, enc_algo="2"))
        r = run(sorted(rows, key=pc._t), "deregistration")
        self.assertIs(r["observations"]["ta21"]["nea0_selected_in_every_smc"], False)
        self.assertTrue(r["valid"])  # report-only

    def test_reject_auth_before(self):
        rows = TestReject().rows()
        o = run(rows, "registration-reject", msin="0000009902")["observations"]["ta21"]
        self.assertIs(o["auth_absent_before_reject"], True)
        self.assertEqual(o["nea0_selected_in_every_smc"], "n/a: no SMC")
        self.assertTrue(o["pfcp_52_53"].startswith("n/a"))
        self.assertTrue(o["accept_before_complete"].startswith("n/a"))
        rows = sorted(rows + [nas(1.1, 4, mm=0x56)], key=pc._t)
        r = run(rows, "registration-reject", msin="0000009902")
        self.assertIs(r["observations"]["ta21"]["auth_absent_before_reject"], False)
        self.assertTrue(r["valid"])  # report-only

    def test_complete_before_accept(self):
        rows = initial_reg_rows()
        for x in rows:
            if x["mm_type"] == ["0x43"]:
                x["t"] = ["1.4"]
        o = run(sorted(rows, key=pc._t), "initial-registration")["observations"]["ta21"]
        self.assertIs(o["accept_before_complete"], False)

    def test_observation_fields_in_field_check(self):
        for f in ("nas-5gs.5g_tmsi", "nas-5gs.mm.type_id", "nas-5gs.mm.nas_sec_algo_enc",
                  "nas-5gs.mm.5gs_reg_type"):
            self.assertIn(f, pc.ALL_FIELD_NAMES)
        self.assertNotIn("nas-5gs.mm.5g_tmsi", pc.ALL_FIELD_NAMES)  # not valid in 4.2.2


class TestDedup(unittest.TestCase):
    def test_veth_and_bridge_copy(self):
        a = nas(1.0, 3, mm=0x41, msin=MSIN, ipid=7)
        b = nas(1.0001, 3, mm=0x41, msin=MSIN, ipid=7)
        b["tsn"] = a["tsn"]
        c = nas(2.0, 3, mm=0x41, msin=MSIN, ipid=7)  # same key, 1 s later: a real packet
        c["tsn"] = a["tsn"]
        out, dropped = pc.dedup([a, b, c])
        self.assertEqual(dropped, 1)
        self.assertEqual(len(out), 2)

    def test_ipid_zero_different_len_kept(self):
        a = nas(1.0, 3, mm=0x41, ipid=0)
        b = nas(1.0001, 3, mm=0x42, ipid=0)
        b["iplen"] = ["200"]
        b["tsn"] = a["tsn"]
        self.assertEqual(pc.dedup([a, b])[1], 0)


class TestParsing(unittest.TestCase):
    def test_parse_rows(self):
        spec = [("a", "x"), ("b", "y"), ("c", "z")]
        rows = pc.parse_rows("1\t0x41|0x42\t\n2\t\n", spec)
        self.assertEqual(rows[0], {"a": ["1"], "b": ["0x41", "0x42"], "c": []})
        self.assertEqual(rows[1], {"a": ["2"], "b": [], "c": []})

    def test_bool(self):
        for v, e in (("1", 1), ("True", 1), ("0", 0), ("False", 0)):
            self.assertEqual(pc.to_bool_int(v), e)

    def test_filename_and_suite(self):
        m = pc.SCEN_RE.match("scenario-deregistration-0000009904-20261109-231500.pcap")
        self.assertEqual(m.groups(), ("deregistration", "0000009904"))
        self.assertIsNone(pc.SCEN_RE.match("scenario-deregistration-00;rm-20261109-231500.pcap"))
        self.assertEqual(pc.suite_msisdns()["registration-reject"], "0000009902")


if __name__ == "__main__":
    unittest.main()
