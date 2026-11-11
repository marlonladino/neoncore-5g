#!/usr/bin/env python3
"""E1 pod health and soak, plus the B1/C1 workload inventory (plan section 8, E1, B1).

Subcommands
  snapshot --out FILE [--namespaces neoncore,monitoring]
        kubectl get pods,deploy,sts,ds,job -n <ns> -o json for each namespace, one
        redacted file {"taken_at", "namespaces": {ns: List}}. Use it for
        pods-start.json, pods-end.json and (with --namespaces kube-system) B1's
        informational kube-system view.
  soak --duration-s N [--interval-s 60] --out soak.json
        compact sample every interval (phase, readiness, restarts, waiting reasons)
  workloads --in SNAPSHOT --out workloads.json
        C1 inventory: (namespace, kind, workload, container, image ref) plus imageIDs
  evaluate --start pods-start.json --end pods-end.json --soak soak.json
           [--compare compare.json] [--out e1.json]
        E1 verdict.

E1 as frozen in the plan, with these reading notes (recorded in every e1.json):
  * "Running with all containers Ready" is checked at every sample (start, soak,
    end) for every pod owned by a Deployment, StatefulSet or DaemonSet.
  * "No pod is Pending, Failed, Unknown or CrashLoopBackOff" is checked for every
    pod at start and end, and at every soak sample for workload pods and the dbctl
    pod. phase6's short-lived scenario-ue pods are excluded from soak samples only,
    because the suite creates them between samples by design.
  * Sampling coverage: at least floor((end - start) / interval) - 1 soak samples.

Exit codes: 0 PASS, 1 FAIL, 2 usage or kubectl error.
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import common  # noqa: E402

NAMESPACES = ["neoncore", "monitoring"]
SOAK_MIN_S = 15 * 60
BAD_PHASES = {"Pending", "Failed", "Unknown"}
BAD_WAITING = {"CrashLoopBackOff"}
WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet"}
SCENARIO_LABEL = ("app", "scenario-ue")
DBCTL_JOB = "dbctl"


class KubectlError(Exception):
    pass


def kubectl_get(ns):
    r = common.run(["kubectl", "get", "pods,deploy,sts,ds,job", "-n", ns, "-o", "json"], timeout=60)
    if r.returncode != 0:
        raise KubectlError(f"kubectl get -n {ns} failed (exit {r.returncode})")
    try:
        return json.loads(r.stdout)
    except ValueError as e:
        raise KubectlError(f"kubectl output for {ns} is not JSON") from e


def take_snapshot(namespaces):
    return {"taken_at": time.time(), "namespaces": {ns: kubectl_get(ns) for ns in namespaces}}


# ------------------------------------------------------------------- compact

def owner_of(pod):
    """(kind, name) of the controlling workload. ReplicaSet -> Deployment via the
    pod-template-hash suffix."""
    md = pod.get("metadata", {})
    for o in md.get("ownerReferences") or []:
        if not o.get("controller", True):
            continue
        kind, name = o.get("kind"), o.get("name", "")
        if kind == "ReplicaSet":
            h = (md.get("labels") or {}).get("pod-template-hash")
            if h and name.endswith("-" + h):
                return ("Deployment", name[: -len(h) - 1])
            return ("ReplicaSet", name)
        return (kind, name)
    return (None, None)


def compact(snapshot):
    """Snapshot -> {taken_at, pods: [...], jobs: {...}}. Keeps no node/host fields."""
    pods, jobs = [], {}
    for ns, lst in snapshot["namespaces"].items():
        for it in lst.get("items", []):
            kind = it.get("kind")
            md = it.get("metadata", {})
            if kind == "Job":
                st = it.get("status", {})
                jobs[f"{ns}/{md.get('name')}"] = {"succeeded": st.get("succeeded", 0),
                                                  "failed": st.get("failed", 0)}
            if kind != "Pod":
                continue
            st = it.get("status", {})
            ok, ow = owner_of(it)
            cs = []
            for c in (st.get("containerStatuses") or []) + (st.get("initContainerStatuses") or []):
                waiting = ((c.get("state") or {}).get("waiting") or {}).get("reason")
                cs.append({"name": c.get("name"), "ready": bool(c.get("ready")),
                           "restarts": int(c.get("restartCount", 0)), "waiting": waiting,
                           "init": c in (st.get("initContainerStatuses") or [])})
            pods.append({"ns": ns, "name": md.get("name"), "phase": st.get("phase"),
                         "owner_kind": ok, "owner": ow,
                         "labels": {k: v for k, v in (md.get("labels") or {}).items()
                                    if k in ("app", "job-name")},
                         "deleting": bool(md.get("deletionTimestamp")),
                         "containers": cs})
    return {"taken_at": snapshot["taken_at"], "pods": pods, "jobs": jobs}


def is_scenario(p):
    return p["labels"].get(SCENARIO_LABEL[0]) == SCENARIO_LABEL[1]


def is_dbctl(p):
    return p["owner_kind"] == "Job" and p["owner"] == DBCTL_JOB


def sample_problems(s, where, all_pods):
    """all_pods=True at start/end; False in soak samples (scenario-ue pods skipped)."""
    probs = []
    for p in s["pods"]:
        pid = f"{p['ns']}/{p['name']}"
        workload = p["owner_kind"] in WORKLOAD_KINDS or p["owner_kind"] == "ReplicaSet"
        checked = workload or is_dbctl(p) or all_pods
        if not all_pods and is_scenario(p):
            continue
        if workload:
            main = [c for c in p["containers"] if not c["init"]]
            if p["phase"] != "Running":
                probs.append(f"{where}: {pid} phase {p['phase']}")
            elif not main or not all(c["ready"] for c in main):
                probs.append(f"{where}: {pid} not all containers Ready")
        elif checked and p["phase"] in BAD_PHASES:
            probs.append(f"{where}: {pid} phase {p['phase']}")
        if checked:
            for c in p["containers"]:
                if c["waiting"] in BAD_WAITING:
                    probs.append(f"{where}: {pid}/{c['name']} {c['waiting']}")
    return probs


def evaluate(start, end, soak, compare=None, interval_s=60):
    """start/end: compact samples; soak: list of compact samples. Returns dict."""
    fails, notes = [], []
    dur = end["taken_at"] - start["taken_at"]
    if dur < SOAK_MIN_S:
        fails.append(f"soak window {dur:.0f} s < {SOAK_MIN_S} s")
    need = max(0, int(dur // interval_s) - 1)
    if len(soak) < need:
        fails.append(f"{len(soak)} soak samples < {need} expected at {interval_s} s")
    samples = [("start", start, True)] + [(f"soak[{i}]", s, False) for i, s in enumerate(soak)] \
        + [("end", end, True)]
    for where, s, all_pods in samples:
        fails += sample_problems(s, where, all_pods)
    # dbctl
    for where, s in (("start", start), ("end", end)):
        job = s["jobs"].get(f"neoncore/{DBCTL_JOB}")
        if not job or job.get("succeeded") != 1:
            fails.append(f"{where}: Job dbctl succeeded={job.get('succeeded') if job else 'absent'}")
        dpods = [p for p in s["pods"] if is_dbctl(p)]
        if not dpods or not all(p["phase"] == "Succeeded" for p in dpods):
            fails.append(f"{where}: dbctl pod phase {[p['phase'] for p in dpods] or 'absent'}")
    # leftovers
    left = [p["name"] for p in end["pods"] if is_scenario(p)]
    if left:
        fails.append(f"end: {len(left)} leftover scenario-ue pod(s)")
    # restarts and pod identity, workload + dbctl pods
    def key_map(s):
        m = {}
        for p in s["pods"]:
            if is_scenario(p):
                continue
            for c in p["containers"]:
                m[(p["ns"], p["name"], c["name"])] = c["restarts"]
        return m

    def pods_by_workload(s):
        m = {}
        for p in s["pods"]:
            if p["owner_kind"] in WORKLOAD_KINDS:
                m.setdefault((p["ns"], p["owner_kind"], p["owner"]), set()).add(p["name"])
        return m

    k0 = key_map(start)
    for where, s, _ in samples[1:]:
        for k, r in key_map(s).items():
            if k in k0 and r != k0[k]:
                fails.append(f"{where}: restart delta {r - k0[k]} for {k[0]}/{k[1]}/{k[2]}")
    w0, w1 = pods_by_workload(start), pods_by_workload(end)
    for w in sorted(set(w0) | set(w1)):
        if w0.get(w) != w1.get(w):
            fails.append(f"workload {w[0]}/{w[1]}/{w[2]}: pod set changed (pod recreated)")
    # C1 / C4
    c = {}
    if compare:
        for cid in ("C1", "C4"):
            c[cid] = compare.get(cid, {}).get("result", "not tested")
            if c[cid] == "FAIL":
                fails.append(f"{cid} FAIL")
    else:
        c = {"C1": "not tested", "C4": "not tested"}
        notes.append("no compare.json given: C1/C4 not evaluated here")
    seen, uniq = set(), []
    for f in fails:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return {"result": "FAIL" if uniq else "PASS", "failures": uniq, "soak_s": round(dur, 1),
            "soak_samples": len(soak), "C": c, "notes": notes,
            "reading_notes": __doc__.split("reading notes (recorded in every e1.json):")[1]
            .split("Exit codes")[0].strip()}


# ------------------------------------------------------------------ workloads

def workloads(snapshot):
    rows, image_ids = [], []
    for ns, lst in snapshot["namespaces"].items():
        for it in lst.get("items", []):
            kind = it.get("kind")
            if kind in WORKLOAD_KINDS or kind == "Job":
                spec = it.get("spec", {}).get("template", {}).get("spec", {})
                for c in (spec.get("initContainers") or []) + (spec.get("containers") or []):
                    rows.append({"ns": ns, "kind": kind, "name": it["metadata"]["name"],
                                 "container": c.get("name"), "image": c.get("image")})
            if kind == "Pod":
                ok, ow = owner_of(it)
                for c in (it.get("status", {}).get("containerStatuses") or []) + \
                        (it.get("status", {}).get("initContainerStatuses") or []):
                    image_ids.append({"ns": ns, "owner_kind": ok, "owner": ow,
                                      "container": c.get("name"), "image": c.get("image"),
                                      "imageID": c.get("imageID")})
    rows.sort(key=lambda r: (r["ns"], r["kind"], r["name"], r["container"]))
    image_ids.sort(key=lambda r: (r["ns"], str(r["owner"]), r["container"]))
    return {"taken_at": snapshot.get("taken_at"), "workloads": rows, "image_ids": image_ids}


# ------------------------------------------------------------------ CLI

def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    ap = argparse.ArgumentParser(description="E1 pod health / B1 inventory")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--out", required=True)
    s.add_argument("--namespaces", default=",".join(NAMESPACES))
    k = sub.add_parser("soak")
    k.add_argument("--duration-s", type=int, required=True)
    k.add_argument("--interval-s", type=int, default=60)
    k.add_argument("--out", required=True)
    w = sub.add_parser("workloads")
    w.add_argument("--in", dest="inp", required=True)
    w.add_argument("--out", required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--start", required=True)
    e.add_argument("--end", required=True)
    e.add_argument("--soak", required=True)
    e.add_argument("--compare")
    e.add_argument("--interval-s", type=int, default=60)
    e.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "snapshot":
            nss = [n for n in a.namespaces.split(",") if n]
            if any(n in ("-A", "--all-namespaces") or n.startswith("-") for n in nss):
                ap.error("namespace names only")
            common.write_json(a.out, take_snapshot(nss))
            return 0
        if a.cmd == "soak":
            samples, t_end = [], time.time() + a.duration_s
            while time.time() < t_end:
                t0 = time.time()
                try:
                    samples.append(compact(take_snapshot(NAMESPACES)))
                except KubectlError as ex:
                    samples.append({"taken_at": t0, "error": str(ex), "pods": [], "jobs": {}})
                time.sleep(max(0, a.interval_s - (time.time() - t0)))
            common.write_json(a.out, {"interval_s": a.interval_s, "samples": samples})
            return 0
        if a.cmd == "workloads":
            common.write_json(a.out, workloads(load(a.inp)))
            return 0
        if a.cmd == "evaluate":
            soak = load(a.soak)
            samples = soak.get("samples", [])
            errs = [x for x in samples if x.get("error")]
            res = evaluate(compact(load(a.start)), compact(load(a.end)), samples,
                           load(a.compare) if a.compare else None, a.interval_s)
            if errs:
                res["failures"].append(f"{len(errs)} soak sample(s) failed to read the cluster")
                res["result"] = "FAIL"
            if a.out:
                common.write_json(a.out, res)
            print(f"E1 {res['result']}")
            for f in res["failures"]:
                print(f"  {f}")
            return 0 if res["result"] == "PASS" else 1
    except KubectlError as ex:
        print(f"pods_check: {ex}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
