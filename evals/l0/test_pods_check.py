"""Unit tests for pods_check.py on synthetic kubectl JSON (no cluster)."""
import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pods_check as pk  # noqa: E402


def pod(name, owner_kind="ReplicaSet", owner="amf-5d8f7c9b4", hash_="5d8f7c9b4", phase="Running",
        ready=True, restarts=0, waiting=None, app=None, image="gradiant/open5gs:2.8.0"):
    labels = {"pod-template-hash": hash_} if owner_kind == "ReplicaSet" else {}
    if app:
        labels["app"] = app
    md = {"name": name, "labels": labels}
    if owner_kind:
        md["ownerReferences"] = [{"kind": owner_kind, "name": owner, "controller": True}]
    state = {"waiting": {"reason": waiting}} if waiting else {"running": {}}
    return {"kind": "Pod", "metadata": md,
            "spec": {"nodeName": "synthetic-node"},
            "status": {"phase": phase, "hostIP": "192.0.2.4",
                       "containerStatuses": [{"name": "main", "ready": ready, "restartCount": restarts,
                                              "state": state, "image": image,
                                              "imageID": "docker-pullable://x@sha256:00"}]}}


def job(succeeded=1):
    return {"kind": "Job", "metadata": {"name": "dbctl"}, "status": {"succeeded": succeeded},
            "spec": {"template": {"spec": {"containers": [{"name": "dbctl", "image": "x/dbctl:1"}]}}}}


def deploy(name, image="gradiant/open5gs:2.8.0"):
    return {"kind": "Deployment", "metadata": {"name": name},
            "spec": {"template": {"spec": {"containers": [{"name": "main", "image": image}]}}}}


def snap(t, neo_pods, mon_pods=None, dbctl_ok=True):
    neo = neo_pods + [pod("dbctl-x1", owner_kind="Job", owner="dbctl", phase="Succeeded", ready=False),
                      job(1 if dbctl_ok else 0), deploy("amf")]
    mon = mon_pods if mon_pods is not None else [
        pod("prometheus-0", owner_kind="StatefulSet", owner="prometheus")]
    return {"taken_at": t, "namespaces": {"neoncore": {"items": neo}, "monitoring": {"items": mon}}}


def healthy(t, **kw):
    return snap(t, [pod("amf-5d8f7c9b4-abcde", **kw)])


def soak(t0, t1, step=60, mk=healthy):
    return [pk.compact(mk(t)) for t in range(int(t0) + step, int(t1), step)]


class TestEvaluate(unittest.TestCase):
    def ev(self, start, end, samples, compare=None):
        return pk.evaluate(pk.compact(start), pk.compact(end), samples, compare)

    def test_pass(self):
        r = self.ev(healthy(0), healthy(960), soak(0, 960),
                    {"C1": {"result": "PASS"}, "C4": {"result": "PASS"}})
        self.assertEqual(r["result"], "PASS", r["failures"])

    def test_short_soak(self):
        r = self.ev(healthy(0), healthy(600), soak(0, 600))
        self.assertIn("soak window 600 s < 900 s", r["failures"])

    def test_too_few_samples(self):
        r = self.ev(healthy(0), healthy(960), soak(0, 960)[:3])
        self.assertTrue(any("soak samples" in f for f in r["failures"]))

    def test_restart_delta(self):
        r = self.ev(healthy(0), healthy(960, restarts=1), soak(0, 960))
        self.assertTrue(any("restart delta 1" in f for f in r["failures"]))

    def test_not_ready_in_soak(self):
        s = soak(0, 960)
        s[5] = pk.compact(healthy(360, ready=False))
        r = self.ev(healthy(0), healthy(960), s)
        self.assertTrue(any(f.startswith("soak[5]") and "not all containers Ready" in f for f in r["failures"]))

    def test_crashloop(self):
        s = soak(0, 960)
        s[2] = pk.compact(healthy(180, ready=False, waiting="CrashLoopBackOff"))
        r = self.ev(healthy(0), healthy(960), s)
        self.assertTrue(any("CrashLoopBackOff" in f for f in r["failures"]))

    def test_dbctl(self):
        r = self.ev(snap(0, [pod("amf-5d8f7c9b4-abcde")], dbctl_ok=False), healthy(960), soak(0, 960))
        self.assertTrue(any("Job dbctl" in f for f in r["failures"]))

    def test_leftover_scenario_pod(self):
        end = snap(960, [pod("amf-5d8f7c9b4-abcde"),
                         pod("scenario-ue-1", owner_kind=None, app="scenario-ue", phase="Running")])
        r = self.ev(healthy(0), end, soak(0, 960))
        self.assertIn("end: 1 leftover scenario-ue pod(s)", r["failures"])

    def test_transient_scenario_pod_in_soak_ok(self):
        def mk(t):
            return snap(t, [pod("amf-5d8f7c9b4-abcde"),
                            pod("scenario-ue-2", owner_kind=None, app="scenario-ue", phase="Pending")])
        r = self.ev(healthy(0), healthy(960), soak(0, 960, mk=mk))
        self.assertEqual(r["result"], "PASS", r["failures"])

    def test_pending_pod_at_end(self):
        end = snap(960, [pod("amf-5d8f7c9b4-abcde"), pod("stray", owner_kind=None, phase="Pending")])
        r = self.ev(healthy(0), end, soak(0, 960))
        self.assertIn("end: neoncore/stray phase Pending", r["failures"])

    def test_pod_recreated(self):
        end = snap(960, [pod("amf-5d8f7c9b4-zzzzz")])
        r = self.ev(healthy(0), end, soak(0, 960))
        self.assertTrue(any("pod set changed" in f for f in r["failures"]))

    def test_compare_fail(self):
        r = self.ev(healthy(0), healthy(960), soak(0, 960), {"C1": {"result": "FAIL"}})
        self.assertIn("C1 FAIL", r["failures"])

    def test_owner_resolution(self):
        p = pod("amf-5d8f7c9b4-abcde")
        self.assertEqual(pk.owner_of(p), ("Deployment", "amf"))

    def test_compact_drops_node_fields(self):
        c = pk.compact(healthy(0))
        self.assertNotIn("synthetic-node", repr(c))
        self.assertNotIn("192.0.2.4", repr(c))


class TestWorkloads(unittest.TestCase):
    def test_inventory(self):
        w = pk.workloads(healthy(0))
        self.assertIn({"ns": "neoncore", "kind": "Deployment", "name": "amf", "container": "main",
                       "image": "gradiant/open5gs:2.8.0"}, w["workloads"])
        self.assertTrue(any(r["owner"] == "amf" for r in w["image_ids"]))


if __name__ == "__main__":
    unittest.main()
