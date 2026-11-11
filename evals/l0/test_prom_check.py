"""Unit tests for prom_check.py E4 logic on synthetic Grafana/Prometheus responses."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prom_check as pc  # noqa: E402


def frame(labels, values):
    return {"schema": {"fields": [{"name": "Time", "type": "time"},
                                  {"name": "Value", "type": "number", "labels": labels}]},
            "data": {"values": [list(range(len(values))), values]}}


def resp(*frames, error=None):
    r = {"frames": list(frames)}
    if error:
        r["error"] = error
    return {"results": {"A": r}}


def series(labels, values):
    return pc.frames_to_series(resp(frame(labels, values)))[0]


def good_results(suites=5):
    out = []
    for pid, title, exprs in pc.dashboard_spec(pc.repo_dashboard()):
        for e in exprs:
            if pc.LAZY_FAIL_METRIC in e:
                s = []
            elif pc.REGREQ in e:
                s = series({"nf": "amf"}, [10, 10 + 3 * suites])
            elif pc.REGSUCC in e:
                s = series({"nf": "amf"}, [8, 8 + 2 * suites])
            elif pid == pc.PANEL1_ID:
                s = series({"pod": "amf-x"}, [1, 1]) + series({"pod": "smf-y"}, [1, 1])
            else:
                s = series({"nf": "x"}, [None, 4])
            out.append({"panel_id": pid, "expr": e, "series": s, "error": None})
    return out


def kpod(name, owner_kind, owner, phase="Running", app=None, hash_=None):
    labels = {}
    if hash_:
        labels["pod-template-hash"] = hash_
    if app:
        labels["app"] = app
    md = {"name": name, "labels": labels}
    if owner_kind:
        md["ownerReferences"] = [{"kind": owner_kind, "name": owner, "controller": True}]
    return {"kind": "Pod", "metadata": md, "status": {"phase": phase}}


PODS = {"taken_at": 0, "namespaces": {"neoncore": {"items": [
    kpod("amf-x", "ReplicaSet", "amf-5d8f7c9b4", hash_="5d8f7c9b4"),
    kpod("smf-y", "ReplicaSet", "smf-6c7d8e9f0", hash_="6c7d8e9f0")]}}}
OWNERS = pc.panel1_pods(PODS)

TARGETS_UP = {"data": {"activeTargets": [{"labels": {"job": "neoncore-5g-nfs"}, "health": "up"},
                                         {"labels": {"job": "prometheus"}, "health": "up"}]}}
E2 = [{"window": [0, 60], "in": series({}, [0, 0.5]), "out": series({}, [0.2, 0.4])}]


class TestE4(unittest.TestCase):
    def test_repo_dashboard_shape(self):
        spec = pc.dashboard_spec(pc.repo_dashboard())
        self.assertEqual(len(spec), 10)
        self.assertEqual(sum(len(x[2]) for x in spec), 18)
        self.assertEqual(pc.check_dashboard(pc.repo_dashboard(), pc.repo_dashboard()), [])

    def test_dashboard_mismatch(self):
        d = pc.repo_dashboard()
        d["panels"] = d["panels"][:-1]
        self.assertTrue(pc.check_dashboard(d, pc.repo_dashboard()))

    def test_pass(self):
        v = pc.evaluate_e4([], good_results(), TARGETS_UP, 5, E2, OWNERS)
        self.assertEqual(v["result"], "PASS", v["failures"])

    def test_target_without_data(self):
        r = good_results()
        r[3]["series"] = series({"nf": "amf"}, [None, None])
        v = pc.evaluate_e4([], r, TARGETS_UP, 5, E2, OWNERS)
        self.assertEqual(v["result"], "FAIL")

    def test_lazy_fail_metric(self):
        r = good_results()
        for x in r:
            if pc.LAZY_FAIL_METRIC in x["expr"]:
                x["series"] = series({"cause": "UE_NOT_RESPONDING"}, [1, 1])
        self.assertEqual(pc.evaluate_e4([], r, TARGETS_UP, 5, E2, OWNERS)["result"], "PASS")
        for x in r:
            if pc.LAZY_FAIL_METRIC in x["expr"]:
                x["series"] = series({"cause": "UE_NOT_RESPONDING"}, [1, 2])
        v = pc.evaluate_e4([], r, TARGETS_UP, 5, E2, OWNERS)
        self.assertEqual(v["result"], "FAIL")
        self.assertTrue(any("UE_NOT_RESPONDING" in f for f in v["failures"]))

    def with_p1(self, extra_series, extra_pods):
        r = good_results()
        for x in r:
            if x["panel_id"] == pc.PANEL1_ID:
                x["series"] += extra_series
        pods = {"taken_at": 0, "namespaces": {"neoncore": {"items":
                PODS["namespaces"]["neoncore"]["items"] + extra_pods}}}
        return pc.evaluate_e4([], r, TARGETS_UP, 5, E2, pc.panel1_pods(pods))

    def test_owners_from_owner_references(self):
        o = pc.panel1_pods({"namespaces": {"neoncore": {"items": [
            kpod("amf-x", "ReplicaSet", "amf-5d8f7c9b4", hash_="5d8f7c9b4"),
            kpod("mongo-0", "StatefulSet", "mongo"),
            kpod("ds-a1b2c", "DaemonSet", "ds"),
            kpod("dbctl-abc12", "Job", "dbctl", phase="Succeeded"),
            kpod("scenario-ue-1", None, None, app="scenario-ue"),
            # a Deployment-looking name owned by a Job: ownership wins, not the name
            kpod("upf-7f9c8d6b5-zzzzz", "Job", "upf-migrate")]}}})
        self.assertEqual(o, {"amf-x": "Deployment", "mongo-0": "StatefulSet", "ds-a1b2c": "DaemonSet",
                             "dbctl-abc12": "Job", "scenario-ue-1": "scenario-ue",
                             "upf-7f9c8d6b5-zzzzz": "Job"})

    def test_panel1_completed_dbctl_passes(self):
        v = self.with_p1(series({"pod": "dbctl-abc12"}, [0, 0]),
                         [kpod("dbctl-abc12", "Job", "dbctl", phase="Succeeded")])
        self.assertEqual(v["result"], "PASS", v["failures"])
        self.assertTrue(any("dbctl-abc12" in n for n in v["notes"]))

    def test_panel1_deployment_pod_at_0_fails(self):
        v = self.with_p1(series({"pod": "upf-7f9c8d6b5-qwert"}, [1, 0]),
                         [kpod("upf-7f9c8d6b5-qwert", "ReplicaSet", "upf-7f9c8d6b5", hash_="7f9c8d6b5")])
        self.assertEqual(v["result"], "FAIL")
        self.assertTrue(any("upf-7f9c8d6b5-qwert" in f for f in v["failures"]))

    def test_panel1_deployment_pod_without_series_fails(self):
        v = self.with_p1([], [kpod("nrf-1a2b3c4d5-asdfg", "ReplicaSet", "nrf-1a2b3c4d5", hash_="1a2b3c4d5")])
        self.assertEqual(v["result"], "FAIL")

    def test_panel1_scenario_ue_excluded(self):
        v = self.with_p1(series({"pod": "scenario-ue-1"}, [1, 0]),
                         [kpod("scenario-ue-1", None, None, phase="Succeeded", app="scenario-ue")])
        self.assertEqual(v["result"], "PASS", v["failures"])

    def test_registration_rise(self):
        v = pc.evaluate_e4([], good_results(suites=4), TARGETS_UP, 5, E2, OWNERS)
        self.assertTrue(any(pc.REGREQ in f for f in v["failures"]))

    def test_target_down(self):
        t = {"data": {"activeTargets": [{"labels": {"job": "kube-state-metrics"}, "health": "down"}]}}
        self.assertEqual(pc.evaluate_e4([], good_results(), t, 5, E2, OWNERS)["result"], "FAIL")

    def test_n3_rate_zero(self):
        e2 = [{"window": [0, 60], "in": series({}, [0, 0]), "out": series({}, [0.2, 0.4])}]
        v = pc.evaluate_e4([], good_results(), TARGETS_UP, 5, e2, OWNERS)
        self.assertTrue(any("N3 in" in f for f in v["failures"]))

    def test_frames_error(self):
        s, err = pc.frames_to_series(resp(error="bad expr"))
        self.assertEqual((s, err), ([], "bad expr"))


if __name__ == "__main__":
    unittest.main()
