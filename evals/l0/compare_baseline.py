#!/usr/bin/env python3
"""C1-C4: compare a Proxmox run with the baseline B (plan section 8, "How Proxmox
results are compared with B"). Writes compare.json into the run folder.

  compare_baseline.py --baseline project/reports/L0/eval/baseline --run project/reports/L0/eval/run-1-x
                      [--netshoot-pinned]

Inputs (each optional; a missing input makes that check "not tested"):
  workloads.json      (pods_check.py workloads)         -> C1
  pcap-summary.json   (pcap_check.py check)             -> C2
  prom-series.json    (prom_check.py series)            -> C3
  versions.txt        (capture_baseline.sh versions)    -> C4
  timing.json         informational durations / RTT

Reading notes (recorded in compare.json):
  * C2: B's item set for a scenario is the union over B's pcaps of that scenario that
    passed V0 and V1; every Proxmox pcap of that scenario must contain it. PFCP items
    count only when tied (pcap_check never lists untied PFCP items).
  * C3: labels dropped before matching: instance, uid, any label whose value is an
    IP address or a redaction placeholder, and the pod-hash suffix of `pod` values.
    `uid` is dropped because it is a per-pod identity like the hash.

Exit codes: 0 all tested checks PASS, 1 any FAIL, 2 usage error.
"""
import argparse
import ipaddress
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import common  # noqa: E402

try:
    from pcap_check import B_ITEMS, REQUIRED, EXPECTED_REJECT_CAUSE  # noqa: E402
except ImportError:  # pragma: no cover
    raise

NOT_TESTED = "not tested: no baseline"
UPF_IMAGE_PREFIX = "neoncore-upf:"
NETSHOOT = "nicolaka/netshoot"


def load(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        if path.endswith(".json"):
            return json.load(f)
        return f.read()


# ------------------------------------------------------------------- C1

def c1(b, r, netshoot_pinned=False):
    if b is None:
        return {"result": NOT_TESTED}
    if r is None:
        return {"result": "FAIL", "failures": ["run workloads.json missing"]}
    key = lambda w: (w["ns"], w["kind"], w["name"], w["container"], w["image"])  # noqa: E731
    bs, rs = {key(w) for w in b["workloads"]}, {key(w) for w in r["workloads"]}
    fails, notes = [], []
    if netshoot_pinned:
        # D9: the Proxmox ref is netshoot@sha256:..., B ran :latest. Compare the digest
        # with B's imageID and treat the two refs as the same workload.
        bdig = {x.get("imageID", "").split("@")[-1] for x in b.get("image_ids", [])
                if NETSHOOT in (x.get("image") or "") or NETSHOOT in (x.get("imageID") or "")}
        rpin = {k for k in rs if NETSHOOT in k[4] and "@sha256:" in k[4]}
        if not rpin:
            fails.append("D9 pin expected but the tracer image ref has no @sha256 digest")
        for k in rpin:
            dig = k[4].split("@")[-1]
            if dig not in bdig:
                fails.append("netshoot digest differs from B's imageID")
            rs.discard(k)
            rs.add(k[:4] + (next((x[4] for x in bs if x[:4] == k[:4]), k[4]),))
    missing, extra = sorted(bs - rs), sorted(rs - bs)
    for m in missing:
        fails.append(f"missing on Proxmox: {'/'.join(m)}")
    for e in extra:
        fails.append(f"extra on Proxmox: {'/'.join(e)}")
    notes.append("allowed differences: pod hash suffixes, IPs, node name, UPF imageID (tag must match)")
    return {"result": "FAIL" if fails else "PASS", "failures": fails, "notes": notes,
            "baseline_count": len(bs), "run_count": len(rs)}


# ------------------------------------------------------------------- C2

def _listed(scn):
    return set(REQUIRED.get(scn, [])) | set(B_ITEMS.get(scn, []))


def c2(b, r):
    if b is None:
        return {"result": NOT_TESTED, "note": "registration-reject cause 7 is still checked by pcap_check (absolute)"}
    if r is None:
        return {"result": "FAIL", "failures": ["run pcap-summary.json missing"]}
    bset, bcause, fails, info = {}, {}, [], {}
    for p in b.get("pcaps", []):
        s = p.get("scenario")
        if p.get("V0") and p.get("V1") and s:
            bset.setdefault(s, set()).update(set(p.get("items", [])) & _listed(s))
            bcause.setdefault(s, set()).update(c for c in p.get("reject_5gmm_causes", []) if c is not None)
    degraded = []
    if bcause.get("registration-reject") and bcause["registration-reject"] != {EXPECTED_REJECT_CAUSE}:
        degraded.append(f"B registration-reject cause(s) {sorted(bcause['registration-reject'])} != 7")
    for p in r.get("pcaps", []):
        s = p.get("scenario")
        need = bset.get(s, set())
        have = set(p.get("items", []))
        miss = sorted(need - have)
        if miss:
            fails.append(f"{p.get('file')}: missing B items {miss}")
        extra = sorted((have & _listed(s)) - need)
        if extra:
            info.setdefault(p.get("file"), {})["extra_items"] = extra
        if s == "registration-reject":
            causes = {c for c in p.get("reject_5gmm_causes", []) if c is not None}
            if causes != {EXPECTED_REJECT_CAUSE}:
                fails.append(f"{p.get('file')}: reject cause(s) {sorted(causes)} != 7")
            elif bcause.get(s) and bcause[s] != causes and not degraded:
                fails.append(f"{p.get('file')}: reject cause differs from B")
    scen_b = set(bset)
    scen_r = {p.get("scenario") for p in r.get("pcaps", [])}
    for s in sorted(scen_b - scen_r):
        fails.append(f"no Proxmox pcap for scenario {s}")
    return {"result": "FAIL" if fails else "PASS", "failures": fails,
            "baseline_items": {k: sorted(v) for k, v in bset.items()},
            "baseline_degraded": degraded, "extra_items_reported": info}


# ------------------------------------------------------------------- C3

POD_HASH_RE = [re.compile(r"^(.+)-[a-z0-9]{8,10}-[a-z0-9]{5}$"),  # Deployment
               re.compile(r"^(.+)-[a-z0-9]{5}$")]                  # DaemonSet / Job


def _is_ip(v):
    try:
        ipaddress.ip_address(v.split(":")[0] if v.count(":") == 1 else v)
        return True
    except ValueError:
        return False


def norm_labels(lbl):
    out = {}
    for k, v in (lbl or {}).items():
        if k in ("instance", "uid"):
            continue
        if not isinstance(v, str):
            out[k] = v
            continue
        if _is_ip(v) or re.fullmatch(r"<[^<>]*>", v):
            continue
        if k == "pod":
            for rx in POD_HASH_RE:
                m = rx.match(v)
                if m:
                    v = m.group(1)
                    break
        out[k] = v
    return tuple(sorted(out.items()))


def c3(b, r):
    if b is None:
        return {"result": NOT_TESTED}
    if r is None:
        return {"result": "FAIL", "failures": ["run prom-series.json missing"]}
    idx = {(t["panel_id"], t["index"], t["expr"]): {norm_labels(x) for x in t.get("label_sets", [])}
           for t in r.get("targets", [])}
    fails, per = [], []
    for t in b.get("targets", []):
        k = (t["panel_id"], t["index"], t["expr"])
        bl = {norm_labels(x) for x in t.get("label_sets", [])}
        rl = idx.get(k)
        if rl is None:
            fails.append(f"target missing on Proxmox: panel {k[0]} `{k[2]}`")
            continue
        miss = sorted(bl - rl)
        per.append({"panel_id": k[0], "expr": k[2], "baseline_series": len(bl), "missing": len(miss)})
        for m in miss:
            fails.append(f"panel {k[0]} `{k[2]}`: series {dict(m)} missing")
    return {"result": "FAIL" if fails else "PASS", "failures": fails, "per_target": per}


# ------------------------------------------------------------------- C4

def parse_versions(text):
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+):\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def c4(btxt, rtxt, bw=None, rw=None):
    if rtxt is None:
        return {"result": "FAIL" if btxt is not None else NOT_TESTED, "failures": ["run versions.txt missing"]}
    rv = parse_versions(rtxt)
    fails = []
    if "2.8.0" not in rv.get("open5gs_upfd", ""):
        fails.append("open5gs-upfd does not report 2.8.0")
    if "3.3.0" not in rv.get("ueransim", ""):
        fails.append("UERANSIM does not report 3.3.0")
    if btxt is None:
        return {"result": "FAIL" if fails else "PASS (absolute part only; " + NOT_TESTED + ")",
                "failures": fails}
    bv = parse_versions(btxt)
    if not bv.get("kubernetes_server") or bv.get("kubernetes_server") != rv.get("kubernetes_server"):
        fails.append("K3s version differs from B (kubernetes_server)")
    if bw is not None and rw is not None:
        tags = lambda w: {(x["ns"], x["kind"], x["name"], x["container"], x["image"].split("@")[0])  # noqa: E731
                          for x in w["workloads"]}
        if tags(bw) != tags(rw):
            fails.append("image tags differ from B (see C1)")
    return {"result": "FAIL" if fails else "PASS", "failures": fails}


# ------------------------------------------------------------------- informational

def informational(bt, rt):
    out = {}
    for name, t in (("baseline", bt), ("run", rt)):
        if not t:
            continue
        out[name] = {k: t.get(k) for k in ("scenario_duration_p50_s", "scenario_duration_p95_s",
                                           "ping_rtt_p50_ms", "ping_rtt_p95_ms")}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="C1-C4 baseline comparison")
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--netshoot-pinned", action="store_true", help="D9 = yes")
    a = ap.parse_args(argv)
    bdir = a.baseline if os.path.isdir(a.baseline) else None
    bp = (lambda f: load(os.path.join(bdir, f))) if bdir else (lambda f: None)
    rp = lambda f: load(os.path.join(a.run, f))  # noqa: E731
    bw, rw = bp("workloads.json"), rp("workloads.json")
    out = {"C1": c1(bw, rw, a.netshoot_pinned), "C2": c2(bp("pcap-summary.json"), rp("pcap-summary.json")),
           "C3": c3(bp("prom-series.json"), rp("prom-series.json")),
           "C4": c4(bp("versions.txt"), rp("versions.txt"), bw, rw),
           "informational": informational(bp("timing.json"), rp("timing.json")),
           "reading_notes": __doc__.split("Reading notes (recorded in compare.json):")[1].split("Exit codes")[0].strip(),
           "provenance": common.git_provenance()}
    common.write_json(os.path.join(a.run, "compare.json"), out)
    bad = False
    for c in ("C1", "C2", "C3", "C4"):
        print(f"{c} {out[c]['result']}")
        for f in out[c].get("failures", [])[:20]:
            print("  " + f)
        bad |= out[c]["result"] == "FAIL"
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
