#!/usr/bin/env python3
"""E4 Grafana panels, B4/C3 metric series, and N3 counters for E2 (plan section 8).

Endpoints (choose per call):
  --grafana nodeport|kube|URL   nodeport: http://<kubeconfig server host>:30030 (the plan's
                                E4 path from the control machine); kube: the API-server
                                service proxy (services/grafana:3000); URL: explicit http(s)
  --prom    nodeport|kube|URL   same, port 30090 / services/prometheus:9090
The address is taken from the kubeconfig and never printed; outputs are redacted.

Subcommands
  series --prom P [--grafana G] [--time T] --out-dir DIR
        B4 / C3: every dashboard target as an instant Prometheus query -> prom-series.json;
        /api/v1/targets -> prom-targets.json; with --grafana also grafana-dashboard.json
  e4 --grafana G --prom P --start T --end T --suites N --pods PODS_JSON [--e2-window S,E ...] --out-dir DIR
        E4 verdict. PODS_JSON is pods_check.py's snapshot at the end of the run window
        (pods-end.json); Panel 1 ownership comes from its ownerReferences (plan
        amendment 2026-11-09: only Deployment/StatefulSet/DaemonSet pods must show 1;
        Job pods (dbctl) and scenario-ue pods are excluded; dbctl is covered by E1).
        -> grafana-panels.json, prom-targets.json, e4.json
  n3 --prom P
        print {"in": x, "out": y, "series": n} for the UPF N3 counters (used by ping_check.sh)

Exit codes: 0 PASS / ok, 1 FAIL, 2 usage, network or parse error.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import common  # noqa: E402
import pods_check  # noqa: E402  (owner_of: ReplicaSet -> Deployment via pod-template-hash)

DASH_UID = "neoncore-5g"
DASH_FILE = os.path.join(common.REPO, "phase3", "manifests", "dashboards", "neoncore-5g.json")
EXPECTED_PANELS, EXPECTED_TARGETS = 10, 18
LAZY_FAIL_METRIC = "fivegs_smffunction_sm_pdusessioncreationfail"
N3_IN = 'fivegs_ep_n3_gtp_indatapktn3upf{nf="upf"}'
N3_OUT = 'fivegs_ep_n3_gtp_outdatapktn3upf{nf="upf"}'
REGREQ = "fivegs_amffunction_rm_reginitreq"
REGSUCC = "fivegs_amffunction_rm_reginitsucc"
PANEL1_ID = 1
PANEL1_NS = "neoncore"
PANEL1_KINDS = {"Deployment", "StatefulSet", "DaemonSet"}
N3_PANEL_ID = 8
STEP_MS = 15000


class FetchError(Exception):
    pass


# ----------------------------------------------------------------- transport

def kube_server_host():
    r = common.run(["kubectl", "config", "view", "--minify", "-o",
                    "jsonpath={.clusters[0].cluster.server}"], timeout=20)
    m = re.match(r"^https?://(\[[^\]]+\]|[^/:]+)", r.stdout.strip())
    if r.returncode != 0 or not m:
        raise FetchError("cannot read the API server host from the kubeconfig")
    return m.group(1)


class Endpoint:
    def __init__(self, spec, svc, port, nodeport):
        self.kube_path = None
        if spec == "kube":
            self.kube_path = f"/api/v1/namespaces/monitoring/services/{svc}:{port}/proxy"
            self.base = None
        elif spec == "nodeport":
            self.base = f"http://{kube_server_host()}:{nodeport}"
        elif re.match(r"^https?://[^\s]+$", spec or ""):
            self.base = spec.rstrip("/")
        else:
            raise FetchError("endpoint must be nodeport, kube or an http(s) URL")

    def get(self, path, params=None):
        q = ("?" + urllib.parse.urlencode(params)) if params else ""
        if self.kube_path:
            r = common.run(["kubectl", "get", "--raw", self.kube_path + path + q], timeout=60)
            if r.returncode != 0:
                raise FetchError(f"kubectl get --raw failed for {path}")
            body = r.stdout
        else:
            try:
                with urllib.request.urlopen(self.base + path + q, timeout=30) as resp:
                    body = resp.read().decode("utf-8", "replace")
            except (urllib.error.URLError, OSError) as e:
                raise FetchError(f"GET {path} failed: {type(e).__name__}") from None
        try:
            return json.loads(body)
        except ValueError:
            raise FetchError(f"GET {path}: response is not JSON") from None

    def post(self, path, obj):
        data = json.dumps(obj)
        if self.kube_path:
            r = common.run(["kubectl", "create", "--raw", self.kube_path + path, "-f", "-"],
                           timeout=60, input_text=data)
            if r.returncode != 0:
                raise FetchError(f"kubectl create --raw failed for {path}")
            body = r.stdout
        else:
            req = urllib.request.Request(self.base + path, data=data.encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    body = resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
            except (urllib.error.URLError, OSError) as e:
                raise FetchError(f"POST {path} failed: {type(e).__name__}") from None
        try:
            return json.loads(body)
        except ValueError:
            raise FetchError(f"POST {path}: response is not JSON") from None


def grafana(spec):
    return Endpoint(spec, "grafana", 3000, 30030)


def prom(spec):
    return Endpoint(spec, "prometheus", 9090, 30090)


# ----------------------------------------------------------------- dashboard

def dashboard_spec(dash):
    """[(panel_id, title, [expr...])] in panel order."""
    out = []
    for p in dash.get("panels", []):
        out.append((p.get("id"), p.get("title"), [t.get("expr") for t in p.get("targets", [])]))
    return out


def repo_dashboard():
    with open(DASH_FILE, encoding="utf-8") as f:
        return json.load(f)


def check_dashboard(live, repo):
    ls, rs = dashboard_spec(live), dashboard_spec(repo)
    fails = []
    n_p, n_t = len(ls), sum(len(x[2]) for x in ls)
    if n_p != EXPECTED_PANELS or n_t != EXPECTED_TARGETS:
        fails.append(f"dashboard has {n_p} panels / {n_t} targets, expected "
                     f"{EXPECTED_PANELS} / {EXPECTED_TARGETS}")
    if ls != rs:
        fails.append("live dashboard panels/targets differ from phase3/manifests/dashboards/neoncore-5g.json")
    return fails


# ----------------------------------------------------------------- ds/query

def ds_query(g, expr, start, end, instant=False):
    body = {"queries": [{"refId": "A", "datasource": {"type": "prometheus", "uid": "prometheus"},
                         "expr": expr, "range": not instant, "instant": instant,
                         "intervalMs": STEP_MS, "maxDataPoints": 1000}],
            "from": str(int(start * 1000)), "to": str(int(end * 1000))}
    return g.post("/api/ds/query", body)


def frames_to_series(resp):
    """Grafana ds/query response -> (series list [{labels, values}], error or None)."""
    res = (resp.get("results") or {}).get("A") or {}
    err = res.get("error")
    series = []
    for fr in res.get("frames") or []:
        fields = (fr.get("schema") or {}).get("fields") or []
        vals = (fr.get("data") or {}).get("values") or []
        for i, f in enumerate(fields):
            if f.get("type") == "time" or f.get("name") == "Time":
                continue
            v = vals[i] if i < len(vals) else []
            t = vals[0] if vals else []
            series.append({"labels": f.get("labels") or {}, "values": v, "times": t})
    return series, err


def nonnull(vs):
    return [v for v in vs if v is not None]


def increase(series):
    """Sum over series of (last non-null - first non-null)."""
    tot = 0.0
    for s in series:
        v = nonnull(s["values"])
        if v:
            tot += v[-1] - v[0]
    return tot


def panel1_pods(snapshot):
    """From a pods_check snapshot: {pod name: owner kind} for neoncore pods, by
    ownerReferences. scenario-ue pods get kind "scenario-ue" (excluded)."""
    out = {}
    lst = (snapshot.get("namespaces") or {}).get(PANEL1_NS) or {}
    for it in lst.get("items", []):
        if it.get("kind") != "Pod":
            continue
        md = it.get("metadata", {})
        if (md.get("labels") or {}).get("app") == "scenario-ue":
            out[md.get("name")] = "scenario-ue"
            continue
        kind, _ = pods_check.owner_of(it)
        out[md.get("name")] = kind
    return out


def evaluate_e4(dash_fails, target_results, prom_targets, suites, e2_results, pod_owners):
    """Pure E4 logic. target_results: [{panel_id, expr, series, error}]."""
    fails, notes, panels = list(dash_fails), [], {}
    for tr in target_results:
        with_data = [s for s in tr["series"] if nonnull(s["values"])]
        tr["series_count"], tr["series_with_data"] = len(tr["series"]), len(with_data)
        panels.setdefault(tr["panel_id"], []).append(len(with_data) > 0)
        if LAZY_FAIL_METRIC in tr["expr"]:
            inc = []
            for s in tr["series"]:
                v = nonnull(s["values"])
                if v and v[-1] - v[0] > 0:
                    inc.append({"cause": s["labels"].get("cause"), "increase": v[-1] - v[0]})
            tr["lazy_exception"] = True
            if inc:
                fails.append(f"{LAZY_FAIL_METRIC} increased over the run window: {inc}")
            continue
        if not with_data:
            fails.append(f"panel {tr['panel_id']} target `{tr['expr']}`: no series with a non-null value"
                         + (f" (error: {tr['error']})" if tr.get("error") else ""))
    for pid, oks in sorted(panels.items(), key=lambda x: (x[0] is None, x[0])):
        if not any(oks):
            fails.append(f"panel {pid}: no target shows data")
    # Panel 1 (amended): at the end of the run window, every neoncore pod owned by a
    # Deployment/StatefulSet/DaemonSet shows 1. Job and scenario-ue pods are excluded.
    p1 = [tr for tr in target_results if tr["panel_id"] == PANEL1_ID]
    last = {}
    for tr in p1:
        for s_ in tr["series"]:
            v = nonnull(s_["values"])
            last[s_["labels"].get("pod", "?")] = v[-1] if v else None
    required = sorted(p for p, k in pod_owners.items() if k in PANEL1_KINDS)
    if not required:
        fails.append("panel 1: no Deployment/StatefulSet/DaemonSet pods in the pods JSON")
    not1 = [p for p in required if last.get(p) != 1]
    if not1:
        fails.append(f"panel 1: {len(not1)} workload pod(s) not at 1 at the end of the window: {not1}")
    excluded = sorted(p for p, k in pod_owners.items() if k not in PANEL1_KINDS)
    if excluded:
        notes.append(f"panel 1 excluded (Job / scenario-ue / other owner): {excluded}")
    unknown = sorted(p for p in last if p not in pod_owners)
    if unknown:
        notes.append(f"panel 1 series for pods not in the pods JSON (not evaluated): {unknown}")
    # Prometheus targets
    act = (prom_targets.get("data") or {}).get("activeTargets") or []
    down = [f"{t.get('labels', {}).get('job')}" for t in act if t.get("health") != "up"]
    if not act:
        fails.append("Prometheus reports no active targets")
    if down:
        fails.append(f"{len(down)} active Prometheus target(s) not up (jobs: {sorted(down)})")
    # AMF registration counters over the run window
    for metric, per in ((REGREQ, 3), (REGSUCC, 2)):
        trs = [tr for tr in target_results if metric in tr["expr"]]
        inc = sum(increase(tr["series"]) for tr in trs)
        need = per * suites
        notes.append(f"{metric} increase {inc:g} (need >= {need})")
        if inc < need:
            fails.append(f"{metric} rose by {inc:g} < {need} ({per} per suite x {suites})")
    # N3 rate during each E2 window
    if not e2_results:
        fails.append("no E2 window given: N3 rate() > 0 not checked")
    for w in e2_results:
        for name in ("in", "out"):
            mx = max((max(nonnull(s["values"]) or [0]) for s in w[name]), default=0)
            w[f"{name}_max_rate"] = mx
            if not mx > 0:
                fails.append(f"N3 {name} rate() not > 0 in E2 window {w['window']}")
    return {"result": "FAIL" if fails else "PASS", "failures": fails, "notes": notes}


# ----------------------------------------------------------------- commands

def strip_series(series):
    return [{"labels": s["labels"], "points": len(s["values"]), "nonnull": len(nonnull(s["values"])),
             "first": (nonnull(s["values"]) or [None])[0], "last": (nonnull(s["values"]) or [None])[-1]}
            for s in series]


def cmd_e4(a):
    g, p = grafana(a.grafana), prom(a.prom)
    live = g.get(f"/api/dashboards/uid/{DASH_UID}").get("dashboard") or {}
    dash_fails = check_dashboard(live, repo_dashboard())
    results = []
    for pid, title, exprs in dashboard_spec(live or repo_dashboard()):
        for e in exprs:
            series, err = frames_to_series(ds_query(g, e, a.start, a.end))
            results.append({"panel_id": pid, "title": title, "expr": e, "series": series, "error": err})
    targets = p.get("/api/v1/targets", {"state": "active"})
    e2 = []
    for w in a.e2_window or []:
        s, e = (float(x) for x in w.split(","))
        e2.append({"window": [s, e],
                   "in": frames_to_series(ds_query(g, f"rate({N3_IN}[1m])", s, e))[0],
                   "out": frames_to_series(ds_query(g, f"rate({N3_OUT}[1m])", s, e))[0]})
    with open(a.pods, encoding="utf-8") as f:
        owners = panel1_pods(json.load(f))
    v = evaluate_e4(dash_fails, results, targets, a.suites, e2, owners)
    os.makedirs(a.out_dir, exist_ok=True)
    common.write_json(os.path.join(a.out_dir, "grafana-panels.json"), {
        "window": [a.start, a.end], "targets": [{**r, "series": strip_series(r["series"])} for r in results],
        "e2_window_list": [{"window": w["window"], "in_max_rate": w.get("in_max_rate"),
                        "out_max_rate": w.get("out_max_rate")} for w in e2]})
    common.write_json(os.path.join(a.out_dir, "prom-targets.json"), targets)
    v["provenance"] = common.git_provenance()
    v["window"], v["suites"] = [a.start, a.end], a.suites
    common.write_json(os.path.join(a.out_dir, "e4.json"), v)
    print(f"E4 {v['result']}")
    for f in v["failures"]:
        print("  " + f)
    return 0 if v["result"] == "PASS" else 1


def cmd_series(a):
    p = prom(a.prom)
    t = a.time or time.time()
    out = {"time": t, "dashboard_source": "phase3/manifests/dashboards/neoncore-5g.json", "targets": []}
    for pid, title, exprs in dashboard_spec(repo_dashboard()):
        for i, e in enumerate(exprs):
            r = p.get("/api/v1/query", {"query": e, "time": f"{t:.3f}"})
            res = (r.get("data") or {}).get("result") or []
            out["targets"].append({"panel_id": pid, "index": i, "expr": e, "status": r.get("status"),
                                   "series_count": len(res), "label_sets": [x.get("metric", {}) for x in res]})
    os.makedirs(a.out_dir, exist_ok=True)
    common.write_json(os.path.join(a.out_dir, "prom-series.json"), out)
    common.write_json(os.path.join(a.out_dir, "prom-targets.json"),
                      p.get("/api/v1/targets", {"state": "active"}))
    if a.grafana:
        common.write_json(os.path.join(a.out_dir, "grafana-dashboard.json"),
                          grafana(a.grafana).get(f"/api/dashboards/uid/{DASH_UID}"))
    print(f"series: {len(out['targets'])} targets written")
    return 0


def n3_values(p):
    out = {}
    for k, e in (("in", N3_IN), ("out", N3_OUT)):
        r = p.get("/api/v1/query", {"query": e})
        res = (r.get("data") or {}).get("result") or []
        out[k] = sum(float(x["value"][1]) for x in res)
        out[f"{k}_series"] = len(res)
    out["time"] = time.time()
    return out


def cmd_n3(a):
    print(json.dumps(n3_values(prom(a.prom))))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="E4 / B4 Prometheus and Grafana checks")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("series")
    s.add_argument("--prom", required=True)
    s.add_argument("--grafana")
    s.add_argument("--time", type=float)
    s.add_argument("--out-dir", required=True)
    e = sub.add_parser("e4")
    e.add_argument("--grafana", required=True)
    e.add_argument("--prom", required=True)
    e.add_argument("--start", type=float, required=True)
    e.add_argument("--end", type=float, required=True)
    e.add_argument("--suites", type=int, required=True)
    e.add_argument("--pods", required=True, help="pods_check snapshot at the end of the run window")
    e.add_argument("--e2-window", action="append")
    e.add_argument("--out-dir", required=True)
    n = sub.add_parser("n3")
    n.add_argument("--prom", required=True)
    a = ap.parse_args(argv)
    try:
        return {"series": cmd_series, "e4": cmd_e4, "n3": cmd_n3}[a.cmd](a)
    except FetchError as ex:
        print(f"prom_check: {ex}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
