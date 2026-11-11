#!/usr/bin/env python3
"""Valid-pcap checker for L0 (plan section 8, "3. Valid pcap"; used by E3, B3 and E2).

Subcommands
  fields                       T3b: confirm every tshark field, protocol and preference
                               used here exists in the installed tshark (>= 4.2).
  check [opts] PCAP...         V0-V3 per scenario pcap -> pcap-summary.json
      --scenario SLUG --msin N   override (default: parsed from scenario-<slug>-<msin>-<ts>.pcap)
      --baseline FILE            B's pcap-summary.json: [B] items B shows become required
      --copy-to DIR              copy each pcap to DIR/pcaps/ and append SHA256SUMS in DIR
      --out FILE                 summary path (redacted write); default: stdout only
  gtpu --start T --end T [--out FILE] PCAP...
                               count `gtp && icmp` frames in [start, end] (epoch s), E2/B2
  observe [--out FILE] PCAP... report-only observations per pcap (telco TB7(b), TA21);
                               no V0-V3 verdict, never changes pass/fail. `check` also
                               adds the same block under "observations".

Report-only observations (they never change V0-V3 or the exit code):
  other_ue_ngap_ids            0x41s on RAN_UE_NGAP_IDs other than the run UE's, with
                               identity type, 5G-TMSI (nas-5gs.5g_tmsi; 4.2.2 has no
                               nas-5gs.mm.5g_tmsi) and registration type
  run_ue_guti_reregistration   a GUTI-identified 0x41 whose 5G-TMSI is one the run UE got
                               in a Registration accept (0x42)
  5gmm_status_causes           5GMM STATUS (0x64) causes, run UE / other
  auth_failure_causes          Authentication failure (0x59) causes, run UE / other
  ta21                         NEA0 selected in every SMC; no authentication before the
                               reject; PFCP 52/53 tied by header SEID; 0x42 before 0x43

tshark runs unprivileged with a throwaway HOME/XDG config (no personal profiles, Lua
plugins or preferences), with `-o nas-5gs.null_decipher:TRUE`, and with explicit
`-T fields` columns only. The field check runs at every start; a missing name fails.
Parsed pcap values are never passed to a shell.

Exit codes: 0 all valid / check ok, 1 at least one pcap invalid, 2 tool or usage
error (tshark missing or too old, a field or preference missing).
"""
import argparse
import ast
import ipaddress
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import common  # noqa: E402

MIN_TSHARK = (4, 2)
PREFS = ["nas-5gs.null_decipher"]
PROTOCOLS = ["sctp", "ngap", "nas-5gs", "pfcp", "gtp", "icmp"]

# column name -> tshark field. Order is the -T fields column order.
FIELDS = [
    ("num", "frame.number"),
    ("t", "frame.time_epoch"),
    ("protos", "frame.protocols"),
    ("src", "ip.src"),
    ("dst", "ip.dst"),
    ("proto", "ip.proto"),
    ("ipid", "ip.id"),
    ("iplen", "ip.len"),
    ("tsn", "sctp.data_tsn"),
    ("ngap_pc", "ngap.procedureCode"),
    ("ran_id", "ngap.RAN_UE_NGAP_ID"),
    ("mm_type", "nas-5gs.mm.message_type"),
    ("sm_type", "nas-5gs.sm.message_type"),
    ("msin", "nas-5gs.mm.suci.msin"),
    ("mm_cause", "nas-5gs.mm.5gmm_cause"),
    ("sm_cause", "nas-5gs.sm.5gsm_cause"),
    ("switch_off", "nas-5gs.mm.switch_off"),
    ("pdu_addr", "nas-5gs.sm.pdu_addr_inf_ipv4"),
    ("pfcp_type", "pfcp.msg_type"),
    ("pfcp_seq", "pfcp.seqno"),
    ("pfcp_seid", "pfcp.seid"),
    ("pfcp_ueip", "pfcp.ue_ip_addr_ipv4"),
    # report-only observation fields (TB7(b), TA21)
    ("type_id", "nas-5gs.mm.type_id"),
    ("tmsi", "nas-5gs.5g_tmsi"),
    ("reg_type", "nas-5gs.mm.5gs_reg_type"),
    ("enc_algo", "nas-5gs.mm.nas_sec_algo_enc"),
]
GTPU_FIELDS = [("t", "frame.time_epoch"), ("icmp_type", "icmp.type"), ("teid", "gtp.teid")]
ALL_FIELD_NAMES = sorted({f for _, f in FIELDS} | {f for _, f in GTPU_FIELDS})

AGG = "|"
DUP_WINDOW_S = 0.05
POD_NETS = [ipaddress.ip_network(n) for n in ("10.42.0.0/16", "10.43.0.0/16", "10.45.0.0/16")]

SCEN_RE = re.compile(r"^scenario-(initial-registration|registration-reject|deregistration)-"
                     r"([0-9]{9,10})-\d{8}-\d{6}\.pcap$")
EXPECTED_REJECT_CAUSE = 7

# Item names used in summaries and by compare_baseline (C2).
REQUIRED = {
    "initial-registration": ["5gmm:0x41", "5gmm:0x42", "5gmm:0x43"],
    "registration-reject": ["5gmm:0x41", "5gmm:0x44"],
    "deregistration": ["5gmm:0x41", "5gmm:0x42", "5gmm:0x43", "5gmm:0x45", "5gmm:0x46"],
}
B_ITEMS = {
    "initial-registration": ["5gsm:0xc1", "5gsm:0xc2", "pfcp:50", "pfcp:51"],
    "registration-reject": [],
    "deregistration": ["ngap:41", "pfcp:54", "pfcp:55"],
}


class ToolError(Exception):
    pass


# ----------------------------------------------------------------- tshark env

def clean_env(tmp):
    cfg = os.path.join(tmp, "config")
    os.makedirs(cfg, exist_ok=True)
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": tmp,
        "XDG_CONFIG_HOME": cfg,
        "XDG_DATA_HOME": os.path.join(tmp, "data"),
        "XDG_CACHE_HOME": os.path.join(tmp, "cache"),
        "WIRESHARK_CONFIG_DIR": cfg,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }


class Tshark:
    def __init__(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise ToolError("refusing to run tshark as root (run unprivileged)")
        self.bin = shutil.which("tshark")
        self.capinfos = shutil.which("capinfos")
        if not self.bin:
            raise ToolError("tshark not installed (T0)")
        if not self.capinfos:
            raise ToolError("capinfos not installed (T0)")
        self.tmp = tempfile.mkdtemp(prefix="tshark-clean-")
        self.env = clean_env(self.tmp)
        self.version = self._version()
        if self.version < MIN_TSHARK:
            raise ToolError(f"tshark {'.'.join(map(str, self.version))} < 4.2")

    def run(self, args, timeout=300):
        return common.run([self.bin] + args, timeout=timeout, env=self.env)

    def _version(self):
        r = self.run(["--version"], timeout=30)
        m = re.search(r"\b(\d+)\.(\d+)\.(\d+)", r.stdout)
        if r.returncode != 0 or not m:
            raise ToolError("cannot read tshark version")
        self.version_str = m.group(0)
        return tuple(int(x) for x in m.groups()[:2])

    def field_check(self):
        """Return dict with missing fields/protocols/prefs."""
        r = self.run(["-G", "fields"], timeout=120)
        if r.returncode != 0:
            raise ToolError("tshark -G fields failed")
        fields, protos = set(), set()
        for line in r.stdout.splitlines():
            cols = line.split("\t")
            if len(cols) >= 3 and cols[0] == "F":
                fields.add(cols[2])
            elif len(cols) >= 3 and cols[0] == "P":
                protos.add(cols[2])
        r2 = self.run(["-G", "defaultprefs"], timeout=120)
        if r2.returncode != 0:
            raise ToolError("tshark -G defaultprefs failed")
        prefs = set()
        for line in r2.stdout.splitlines():
            m = re.match(r"^#?\s*([A-Za-z0-9_.\-]+)\s*:", line)
            if m:
                prefs.add(m.group(1))
        return {
            "tshark_version": self.version_str,
            "fields_checked": ALL_FIELD_NAMES,
            "missing_fields": [f for f in ALL_FIELD_NAMES if f not in fields],
            "protocols_checked": PROTOCOLS,
            "missing_protocols": [p for p in PROTOCOLS if p not in protos],
            "prefs_checked": PREFS,
            "missing_prefs": [p for p in PREFS if p not in prefs],
        }

    def require_fields(self):
        fc = self.field_check()
        if fc["missing_fields"] or fc["missing_protocols"] or fc["missing_prefs"]:
            raise ToolError("tshark is missing names used by pcap_check: "
                            f"fields={fc['missing_fields']} protocols={fc['missing_protocols']} "
                            f"prefs={fc['missing_prefs']}")
        return fc

    def capinfos_count(self, path):
        r = common.run([self.capinfos, "-c", "-M", path], timeout=120, env=self.env)
        m = re.search(r"Number of packets:\s*(\d+)", r.stdout)
        return (int(m.group(1)) if (r.returncode == 0 and m) else None), r.returncode

    def fields(self, path, fieldspec, display_filter=None):
        args = ["-n", "-r", path, "-o", "nas-5gs.null_decipher:TRUE", "-T", "fields",
                "-E", "header=n", "-E", "separator=/t", "-E", "occurrence=a",
                "-E", f"aggregator={AGG}", "-E", "quote=n"]
        if display_filter:
            args += ["-Y", display_filter]
        for _, f in fieldspec:
            args += ["-e", f]
        r = self.run(args)
        return r.returncode, r.stdout, r.stderr


# ---------------------------------------------------------------- parsing

def parse_rows(stdout, fieldspec):
    rows = []
    names = [n for n, _ in fieldspec]
    for line in stdout.splitlines():
        cols = line.split("\t")
        cols += [""] * (len(names) - len(cols))
        rows.append({n: ([v for v in c.split(AGG) if v != ""] if c else []) for n, c in zip(names, cols)})
    return rows


def to_int(v):
    try:
        return int(v, 0)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None


def to_bool_int(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "0x1", "0x01"):
        return 1
    if s in ("0", "false", "no", "0x0", "0x00"):
        return 0
    return to_int(s)


def dedup(rows):
    """Drop the second copy of a frame seen on two interfaces (veth + cni0; telco TA4).
    Match: same IP src/dst/proto/ID/total length and same SCTP TSN list and PFCP
    sequence number, within DUP_WINDOW_S of the first copy."""
    seen = {}
    out, dropped = [], 0
    for r in rows:
        if not r["src"] or not r["ipid"]:
            out.append(r)
            continue
        key = (tuple(r["src"]), tuple(r["dst"]), tuple(r["proto"]), tuple(r["ipid"]),
               tuple(r["iplen"]), tuple(r["tsn"]), tuple(r["pfcp_seq"]))
        try:
            t = float(r["t"][0])
        except (IndexError, ValueError):
            t = None
        prev = seen.get(key)
        if prev is not None and t is not None and abs(t - prev) <= DUP_WINDOW_S:
            dropped += 1
            continue
        seen[key] = t
        out.append(r)
    return out, dropped


def _t(r):
    try:
        return float(r["t"][0])
    except (IndexError, ValueError):
        return 0.0


def analyze(rows, scenario, msin):
    """Pure function: V1/V2 analysis on parsed, de-duplicated rows."""
    res = {"protocol_frames": {}, "items": [], "reasons": [], "ambiguous_frames": 0,
           "reject_5gmm_causes": [], "pdu_reject_5gsm_causes": [], "switch_off": [],
           "pfcp_tie": "n/a", "run_ran_ue_ngap_ids": [], "non_pod_src_frames": 0}
    for p in PROTOCOLS:
        res["protocol_frames"][p] = sum(1 for r in rows if p in (r["protos"][0].split(":") if r["protos"] else []))
    for r in rows:
        if r["src"]:
            try:
                ip = ipaddress.ip_address(r["src"][0])  # outer header
                if not any(ip in n for n in POD_NETS):
                    res["non_pod_src_frames"] += 1
            except ValueError:
                pass
    v1 = res["protocol_frames"]["ngap"] >= 1 and res["protocol_frames"]["nas-5gs"] >= 1
    res["V1"] = v1
    if not v1:
        res["reasons"].append("V1: no ngap and/or nas-5gs frame")

    # Run UE: RAN_UE_NGAP_IDs of Registration requests whose SUCI MSIN is the run's.
    run_ids = set()
    for r in rows:
        mm = [to_int(x) for x in r["mm_type"]]
        if 0x41 in mm and msin in r["msin"] and r["ran_id"]:
            run_ids.update(r["ran_id"])
    res["run_ran_ue_ngap_ids"] = sorted(run_ids, key=lambda x: to_int(x) or 0)
    if not run_ids:
        res["reasons"].append("V2: no Registration request (0x41) with the run's SUCI MSIN")

    items = {}  # item -> first time
    pdu_addrs = set()
    seids = set()
    for r in rows:
        ids = set(r["ran_id"])
        if not ids or not (ids & run_ids):
            continue
        if len(ids) > 1:
            res["ambiguous_frames"] += 1
            continue
        t = _t(r)
        for x in r["mm_type"]:
            v = to_int(x)
            if v is not None:
                items.setdefault(f"5gmm:{v:#04x}", t)
        for x in r["sm_type"]:
            v = to_int(x)
            if v is not None:
                items.setdefault(f"5gsm:{v:#04x}", t)
        for x in r["ngap_pc"]:
            v = to_int(x)
            if v is not None:
                items.setdefault(f"ngap:{v}", t)
        mm = [to_int(x) for x in r["mm_type"]]
        sm = [to_int(x) for x in r["sm_type"]]
        if 0x44 in mm:
            res["reject_5gmm_causes"] += [to_int(c) for c in r["mm_cause"]]
        if 0xc3 in sm:
            res["pdu_reject_5gsm_causes"] += [to_int(c) for c in r["sm_cause"]]
        if 0x45 in mm:
            res["switch_off"] += [to_bool_int(s) for s in r["switch_off"]]
        if 0xc2 in sm:
            pdu_addrs.update(r["pdu_addr"])

    # PFCP tie rule (telco TB4).
    pfcp_items = {}
    if pdu_addrs:
        est_seq = set()
        for r in rows:
            types = [to_int(x) for x in r["pfcp_type"]]
            if 50 in types and set(r["pfcp_ueip"]) & pdu_addrs:
                pfcp_items.setdefault("pfcp:50", _t(r))
                est_seq.update(r["pfcp_seq"])
                seids.update(s for s in r["pfcp_seid"] if to_int(s))
        for r in rows:
            types = [to_int(x) for x in r["pfcp_type"]]
            if 51 in types and set(r["pfcp_seq"]) & est_seq:
                pfcp_items.setdefault("pfcp:51", _t(r))
                seids.update(s for s in r["pfcp_seid"] if to_int(s))
        for r in rows:
            types = [to_int(x) for x in r["pfcp_type"]]
            hdr = r["pfcp_seid"][0] if r["pfcp_seid"] else None
            for code in (54, 55):
                if code in types and hdr is not None and hdr in seids:
                    pfcp_items.setdefault(f"pfcp:{code}", _t(r))
        items.update(pfcp_items)
    any_pfcp = any(r["pfcp_type"] for r in rows)
    if pfcp_items:
        res["pfcp_tie"] = "tied"
    elif not any_pfcp:
        res["pfcp_tie"] = "no-pfcp"
    elif pdu_addrs:
        res["pfcp_tie"] = "no-match"      # PDU address known, no PFCP message carries it
    else:
        res["pfcp_tie"] = "untied"        # PDU address unreadable: not counted (TB4)

    res["items"] = sorted(items)
    res["_item_times"] = items
    res["observations"] = observe(rows, scenario, run_ids, items, seids)
    return res


# ------------------------------------------------- report-only observations

IDENTITY_TYPES = {0: "no identity", 1: "SUCI", 2: "5G-GUTI", 3: "IMEI", 4: "5G-S-TMSI",
                  5: "IMEISV", 6: "MAC address", 7: "EUI-64"}
NEA0 = 0


def _hex32(v):
    i = to_int(v)
    return f"{i:#010x}" if i is not None else None


def observe(rows, scenario, run_ids, items, seids):
    """Report-only facts on de-duplicated rows (telco TB7(b), TA21). Pure; never used by
    verdict(). Frame numbers are raw tshark frame numbers (first copy)."""
    obs = {"report_only": True}
    run_tmsis = set()
    for r in rows:
        if set(r["ran_id"]) & run_ids and 0x42 in [to_int(x) for x in r["mm_type"]]:
            run_tmsis.update(t for t in (_hex32(x) for x in r["tmsi"]) if t)
    obs["run_ue_assigned_5g_tmsi"] = sorted(run_tmsis)

    others = {}
    status = {"run_ue": [], "other": []}
    authf = {"run_ue": [], "other": []}
    smc_algos = {"run_ue": [], "other": []}
    for r in rows:
        mm = [to_int(x) for x in r["mm_type"]]
        ids = set(r["ran_id"])
        who = "run_ue" if ids & run_ids else "other"
        if 0x41 in mm and ids and not (ids & run_ids):
            for rid in sorted(ids, key=lambda x: to_int(x) or 0):
                if rid in others:
                    continue
                tid = [to_int(x) for x in r["type_id"]]
                tid = tid[0] if tid else None
                others[rid] = {"ran_ue_ngap_id": rid, "first_frame": to_int(r["num"][0]) if r["num"] else None,
                               "identity_type": IDENTITY_TYPES.get(tid, tid),
                               "5g_tmsi": [t for t in (_hex32(x) for x in r["tmsi"]) if t],
                               "registration_type": [to_int(x) for x in r["reg_type"]],
                               "suci_msin_present": bool(r["msin"])}
        if 0x64 in mm:
            status[who] += [to_int(c) for c in r["mm_cause"]]
        if 0x59 in mm:
            authf[who] += [to_int(c) for c in r["mm_cause"]]
        if 0x5d in mm:
            smc_algos[who] += [to_int(a) for a in r["enc_algo"]]
    other_list = sorted(others.values(), key=lambda o: to_int(o["ran_ue_ngap_id"]) or 0)
    rereg = [o["ran_ue_ngap_id"] for o in other_list
             if o["identity_type"] == "5G-GUTI" and set(o["5g_tmsi"]) & run_tmsis]
    obs["other_ue_ngap_ids"] = other_list
    obs["run_ue_guti_reregistration"] = bool(rereg)
    obs["run_ue_guti_reregistration_ran_ids"] = rereg
    obs["5gmm_status_causes"] = status
    obs["auth_failure_causes"] = authf

    ta = {}
    all_algos = smc_algos["run_ue"] + smc_algos["other"]
    ta["smc_ciphering_algorithms"] = smc_algos
    ta["nea0_selected_in_every_smc"] = (all(a == NEA0 for a in all_algos) if all_algos else "n/a: no SMC")
    if scenario == "registration-reject":
        t_rej = items.get("5gmm:0x44")
        if t_rej is None:
            ta["auth_absent_before_reject"] = "n/a: no 0x44"
        else:
            auth = [k for k in ("5gmm:0x56", "5gmm:0x57", "5gmm:0x59") if k in items and items[k] <= t_rej]
            ta["auth_absent_before_reject"] = not auth
    else:
        ta["auth_absent_before_reject"] = "n/a: not a reject scenario"
    tied = {}
    if seids:
        for r in rows:
            types = [to_int(x) for x in r["pfcp_type"]]
            hdr = r["pfcp_seid"][0] if r["pfcp_seid"] else None
            for code in (52, 53):
                if code in types and hdr is not None and hdr in seids:
                    tied.setdefault(code, to_int(r["num"][0]) if r["num"] else None)
        ta["pfcp_52_53"] = {"52": 52 in tied, "53": 53 in tied}
    else:
        ta["pfcp_52_53"] = "n/a: no PFCP session tied to the run UE"
    if "5gmm:0x42" in items and "5gmm:0x43" in items:
        ta["accept_before_complete"] = items["5gmm:0x42"] < items["5gmm:0x43"]
    else:
        ta["accept_before_complete"] = "n/a: 0x42 and 0x43 not both present"
    obs["ta21"] = ta
    return obs


def verdict(res, scenario, b_required):
    """Apply V2 scenario rules and [B] requirements. Mutates and returns res."""
    items = res["_item_times"]
    reasons = res["reasons"]
    for it in REQUIRED[scenario]:
        if it not in items:
            reasons.append(f"V2: missing required {it}")
    if scenario == "initial-registration":
        if "5gsm:0xc3" in items:
            reasons.append(f"V2: PDU session establishment reject (0xc3), 5GSM cause "
                           f"{res['pdu_reject_5gsm_causes']}")
    elif scenario == "registration-reject":
        if "5gmm:0x42" in items:
            reasons.append("V2: Registration accept present for the rejected UE")
        causes = [c for c in res["reject_5gmm_causes"] if c is not None]
        if "5gmm:0x44" in items and (not causes or any(c != EXPECTED_REJECT_CAUSE for c in causes)):
            reasons.append(f"V2: 5GMM cause {causes}, expected {EXPECTED_REJECT_CAUSE}")
    elif scenario == "deregistration":
        so = res["switch_off"]
        if "5gmm:0x45" in items:
            if any(s == 1 for s in so):
                reasons.append("V2: Deregistration request with switch_off=1")
            elif not so or any(s != 0 for s in so):
                reasons.append(f"V2: switch_off not 0 ({so})")
        if "5gmm:0x46" in items and "5gmm:0x45" in items and items["5gmm:0x46"] < items["5gmm:0x45"]:
            reasons.append("V2: Deregistration accept precedes the request")
    b_items = B_ITEMS[scenario]
    res["b_items_present"] = [i for i in b_items if i in items]
    res["b_items_required"] = sorted(set(b_required or []) & set(b_items))
    for it in res["b_items_required"]:
        if it not in items:
            reasons.append(f"V3/[B]: B shows {it}, missing here")
    res["V2"] = not any(x.startswith(("V2", "V3")) for x in reasons)
    res["valid"] = res.get("V0", False) and res["V1"] and res["V2"]
    res.pop("_item_times", None)
    return res


# ---------------------------------------------------------------- driver

def suite_msisdns():
    """Read SUITE_MSISDNS from phase6/tests/run_scenarios.py without executing it."""
    path = os.path.join(common.REPO, "phase6", "tests", "run_scenarios.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "SUITE_MSISDNS" for t in node.targets):
            d = ast.literal_eval(node.value)
            return {k: v for k, v in d.items() if common.valid_msin(v)}
    raise ToolError("SUITE_MSISDNS not found")


def baseline_required(path):
    """[B] items B shows: any B pcap of the scenario (V0 and V1 ok) that has the item tied."""
    import json
    with open(path, encoding="utf-8") as f:
        b = json.load(f)
    req = {}
    for p in b.get("pcaps", []):
        if p.get("V0") and p.get("V1") and p.get("scenario") in B_ITEMS:
            req.setdefault(p["scenario"], set()).update(set(p.get("items", [])) & set(B_ITEMS[p["scenario"]]))
    return {k: sorted(v) for k, v in req.items()}


def v0(ts, path):
    out = {"file": os.path.basename(path), "V0": False, "reasons": []}
    if not os.path.isfile(path):
        out["reasons"].append("V0: file missing")
        return out
    out["size"] = os.path.getsize(path)
    out["sha256"] = common.sha256_file(path)
    if out["size"] <= 24:
        out["reasons"].append("V0: size <= 24 bytes")
        return out
    n, rc = ts.capinfos_count(path)
    out["capinfos_packets"] = n
    if not n or n < 1:
        out["reasons"].append("V0: capinfos reports no packets")
        return out
    out["V0"] = True
    return out


def check_one(ts, path, scenario, msin, b_req):
    out = v0(ts, path)
    out["scenario"], out["msin"] = scenario, msin
    if not out["V0"]:
        out.update({"V1": False, "V2": False, "valid": False})
        return out
    rc, stdout, stderr = ts.fields(path, FIELDS)
    if rc != 0 or re.search(r"cut short|appears to be damaged|corrupt", stderr, re.I):
        out["V0"] = False
        out["reasons"].append(f"V0: tshark exit {rc} or damage warning")
        out.update({"V1": False, "V2": False, "valid": False})
        return out
    rows = parse_rows(stdout, FIELDS)
    out["frames_raw"] = len(rows)
    rows, dropped = dedup(rows)
    out["frames_dedup"], out["duplicates_removed"] = len(rows), dropped
    res = analyze(rows, scenario, msin)
    res["reasons"] = out["reasons"] + res["reasons"]
    out.update(res)
    return verdict(out, scenario, b_req.get(scenario, []))


def cmd_fields(a):
    ts = Tshark()
    fc = ts.field_check()
    ok = not (fc["missing_fields"] or fc["missing_protocols"] or fc["missing_prefs"])
    fc["result"] = "PASS" if ok else "FAIL"
    import json
    text = json.dumps(fc, indent=2) + "\n"
    if a.out:
        common.write_text(a.out, text)
    print(text, end="")
    return 0 if ok else 2


def cmd_check(a):
    ts = Tshark()
    fc = ts.require_fields()
    b_req = baseline_required(a.baseline) if a.baseline else {}
    suite = suite_msisdns()
    pcaps = []
    for path in a.pcaps:
        name = os.path.basename(path)
        scenario, msin, why = a.scenario, a.msin, []
        m = SCEN_RE.match(name)
        if not scenario:
            if not m:
                why.append("file name is not scenario-<slug>-<msin>-<ts>.pcap and no --scenario")
            else:
                scenario = m.group(1)
        if not msin:
            if m:
                msin = m.group(2)
                if suite.get(scenario) != msin:
                    why.append("MSIN in file name is not the suite MSISDN for this scenario")
        if msin is not None and not common.valid_msin(msin):
            why.append("MSIN fails ^[0-9]{9,10}$")
            msin = None
        if scenario not in REQUIRED:
            why.append("unknown scenario")
        if why or not msin:
            pcaps.append({"file": name, "scenario": scenario, "valid": False, "V0": False,
                          "V1": False, "V2": False, "reasons": why or ["no MSIN"]})
            continue
        pcaps.append(check_one(ts, path, scenario, msin, b_req))
    if a.copy_to:
        dst = os.path.join(a.copy_to, "pcaps")
        os.makedirs(dst, exist_ok=True)
        copied = []
        for path in a.pcaps:
            if os.path.isfile(path):
                d = os.path.join(dst, os.path.basename(path))
                shutil.copy2(path, d)
                copied.append(d)
        common.append_sha256sums(a.copy_to, copied)
    summary = {"tool": {"tshark": fc["tshark_version"], "null_decipher": True,
                        "dup_window_s": DUP_WINDOW_S},
               "provenance": common.git_provenance(),
               "baseline_required": b_req, "pcaps": pcaps,
               "valid_count": sum(1 for p in pcaps if p.get("valid")), "total": len(pcaps)}
    import json
    text = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if a.out:
        common.write_text(a.out, text)
    for p in pcaps:
        print(f"{'VALID' if p.get('valid') else 'INVALID'}  {p['file']}  "
              + ("; ".join(p.get("reasons", [])) or "ok"))
    return 0 if summary["valid_count"] == summary["total"] and pcaps else 1


def cmd_observe(a):
    """Report-only: observations per pcap, no verdict. Scenario/MSIN from the file name."""
    ts = Tshark()
    fc = ts.require_fields()
    suite = suite_msisdns()
    out = []
    for path in a.pcaps:
        name = os.path.basename(path)
        m = SCEN_RE.match(name)
        if not m or suite.get(m.group(1)) != m.group(2):
            out.append({"file": name, "status": "not tested: file name not a suite scenario pcap"})
            continue
        scenario, msin = m.group(1), m.group(2)
        rc, stdout, stderr = ts.fields(path, FIELDS)
        if rc != 0:
            out.append({"file": name, "status": f"not tested: tshark exit {rc}"})
            continue
        rows, _ = dedup(parse_rows(stdout, FIELDS))
        res = analyze(rows, scenario, msin)
        out.append({"file": name, "sha256": common.sha256_file(path), "scenario": scenario,
                    "run_ran_ue_ngap_ids": res["run_ran_ue_ngap_ids"], **res["observations"]})
    tested = [o for o in out if "status" not in o]
    agg = {
        "pcaps": len(out), "observed": len(tested),
        "other_ue_registrations": sum(len(o["other_ue_ngap_ids"]) for o in tested),
        "other_ue_identity_types": sorted({str(x["identity_type"]) for o in tested for x in o["other_ue_ngap_ids"]}),
        "pcaps_with_run_ue_guti_reregistration": sum(1 for o in tested if o["run_ue_guti_reregistration"]),
        "5gmm_status_causes": sorted(c for o in tested for k in ("run_ue", "other") for c in o["5gmm_status_causes"][k] if c is not None),
        "auth_failure_causes_run_ue": sorted(c for o in tested for c in o["auth_failure_causes"]["run_ue"] if c is not None),
        "auth_failure_causes_other": sorted(c for o in tested for c in o["auth_failure_causes"]["other"] if c is not None),
        "smc_count": sum(len(o["ta21"]["smc_ciphering_algorithms"][k]) for o in tested for k in ("run_ue", "other")),
        "nea0_selected_in_every_smc": all(o["ta21"]["nea0_selected_in_every_smc"] in (True, "n/a: no SMC") for o in tested),
    }
    import json
    summary = {"report_only": True,
               "note": "Report-only observations (telco TB7(b), TA21). They do not change V0-V3; "
                       "the pass/fail evidence is pcap-summary*.json.",
               "tool": {"tshark": fc["tshark_version"], "null_decipher": True, "dup_window_s": DUP_WINDOW_S},
               "provenance": common.git_provenance(), "aggregate": agg, "pcaps": out}
    text = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if a.out:
        common.write_text(a.out, text)
    print(text, end="")
    return 0


def cmd_gtpu(a):
    ts = Tshark()
    fc = ts.require_fields()
    files, frames, req, rep = [], 0, 0, 0
    for path in a.pcaps:
        rc, stdout, stderr = ts.fields(path, GTPU_FIELDS, display_filter="gtp && icmp")
        files.append({"file": os.path.basename(path), "sha256": common.sha256_file(path),
                      "tshark_rc": rc})
        for r in parse_rows(stdout, GTPU_FIELDS):
            t = _t(r)
            if a.start <= t <= a.end:
                frames += 1
                last = to_int(r["icmp_type"][-1]) if r["icmp_type"] else None
                req += last == 8
                rep += last == 0
    out = {"tshark": fc["tshark_version"], "window": [a.start, a.end], "files": files,
           "gtp_icmp_frames": frames, "echo_request_frames": req, "echo_reply_frames": rep,
           "note": "frames are not de-duplicated here (counts only, threshold is > 0)"}
    import json
    text = json.dumps(out, indent=2) + "\n"
    if a.out:
        common.write_text(a.out, text)
    print(text, end="")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fields")
    f.add_argument("--out")
    c = sub.add_parser("check")
    c.add_argument("--scenario", choices=sorted(REQUIRED))
    c.add_argument("--msin")
    c.add_argument("--baseline")
    c.add_argument("--copy-to")
    c.add_argument("--out")
    c.add_argument("pcaps", nargs="+")
    o = sub.add_parser("observe")
    o.add_argument("--out")
    o.add_argument("pcaps", nargs="+")
    g = sub.add_parser("gtpu")
    g.add_argument("--start", type=float, required=True)
    g.add_argument("--end", type=float, required=True)
    g.add_argument("--out")
    g.add_argument("pcaps", nargs="+")
    a = ap.parse_args(argv)
    try:
        return {"fields": cmd_fields, "check": cmd_check, "gtpu": cmd_gtpu,
                "observe": cmd_observe}[a.cmd](a)
    except ToolError as e:
        print(f"pcap_check: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
