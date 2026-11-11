#!/usr/bin/env python3
"""E7 LAN exposure: parse nmap XML, the NAD list and the nft ruleset (plan section 8, E7).

  scan_parse.py scan --mode nonallow|allow [--d7 a|b] --label K --out-dir DIR NMAP_XML...
        nonallow: zero TCP ports open across 1-65535 and zero UDP/SCTP ports open
                  (open|filtered accepted and reported). Needs the full TCP scan, the
                  UDP list 53,123,2152,4789,8472,8805,51820,51821 and SCTP 38412,9999.
        allow:    the set of open TCP ports equals {22,6443,30030,30090} (D7 a) or {22} (D7 b),
                  from a full TCP scan. UDP results, if given, are reported (S-A7).
        -> DIR/scan-<mode>-<K>.txt (+ .json). Scanned and scanner addresses never appear:
           the target is written as <vm>, the scanner as <scanner>.
  scan_parse.py nad --lan-nic IFACE --out FILE NAD_JSON
        no NetworkAttachmentDefinition may put a pod on the VM's LAN NIC.
  scan_parse.py nft --out FILE RULESET_TXT
        table inet neoncore_guard present, prerouting hook at priority -150, a final
        drop with a counter (presence evidence; R3 requires the table after reboot).

Exit codes: 0 PASS, 1 FAIL, 2 usage or parse error.
"""
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import common  # noqa: E402

UDP_LIST = {53, 123, 2152, 4789, 8472, 8805, 51820, 51821}
SCTP_LIST = {38412, 9999}
ALLOW_TCP = {"a": {22, 6443, 30030, 30090}, "b": {22}}


class ParseError(Exception):
    pass


def parse_ports_spec(spec):
    out = set()
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def parse_nmap_xml(text):
    # stdlib expat does not fetch external entities; entity declarations and internal
    # DTD subsets are refused outright (billion-laughs style input). nmap writes only
    # a bare <!DOCTYPE nmaprun>.
    if re.search(r"<!ENTITY", text, re.I) or re.search(r"<!DOCTYPE[^>]*\[", text, re.I):
        raise ParseError("XML with entity declarations or an internal DTD subset refused")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ParseError(f"not valid nmap XML ({e.code})") from None
    if root.tag != "nmaprun":
        raise ParseError("root element is not nmaprun")
    scaninfo = [{"type": s.get("type"), "protocol": s.get("protocol"),
                 "ports": parse_ports_spec(s.get("services"))} for s in root.findall("scaninfo")]
    hosts = root.findall("host")
    ports, host_up = [], False
    for h in hosts:
        st = h.find("status")
        host_up |= st is not None and st.get("state") == "up"
        for p in h.findall("ports/port"):
            s = p.find("state")
            ports.append({"proto": p.get("protocol"), "port": int(p.get("portid")),
                          "state": s.get("state") if s is not None else "unknown",
                          "reason": s.get("reason") if s is not None else None})
        for ex in h.findall("ports/extraports"):
            # extraports summarise many ports in one state (e.g. 65532 filtered)
            ports.append({"proto": None, "extraports": int(ex.get("count", 0)),
                          "state": ex.get("state")})
    return {"scaninfo": scaninfo, "hosts": len(hosts), "host_up": host_up, "ports": ports,
            "nmap_version": root.get("version"), "args_present": bool(root.get("args"))}


def evaluate_scan(parsed, mode, d7="a"):
    fails, report = [], {"open": {}, "open|filtered": {}, "coverage": {}}
    scanned = {"tcp": set(), "udp": set(), "sctp": set()}
    for p in parsed:
        for si in p["scaninfo"]:
            if si["protocol"] in scanned:
                scanned[si["protocol"]] |= si["ports"]
        if p["hosts"] == 0:
            fails.append("a scan has no host element (inconclusive)")
    for proto in scanned:
        report["coverage"][proto] = len(scanned[proto])
    opened = {"tcp": set(), "udp": set(), "sctp": set()}
    of = {"tcp": set(), "udp": set(), "sctp": set()}
    for p in parsed:
        for port in p["ports"]:
            if port.get("proto") not in opened:
                continue
            if port["state"] == "open":
                opened[port["proto"]].add(port["port"])
            elif port["state"] == "open|filtered":
                of[port["proto"]].add(port["port"])
    for proto in opened:
        report["open"][proto] = sorted(opened[proto])
        report["open|filtered"][proto] = sorted(of[proto])
    full_tcp = set(range(1, 65536))
    if not full_tcp <= scanned["tcp"]:
        fails.append(f"TCP scan does not cover 1-65535 ({len(scanned['tcp'])} ports)")
    if mode == "nonallow":
        if not UDP_LIST <= scanned["udp"]:
            fails.append(f"UDP list not fully scanned (missing {sorted(UDP_LIST - scanned['udp'])})")
        if not SCTP_LIST <= scanned["sctp"]:
            fails.append(f"SCTP list not fully scanned (missing {sorted(SCTP_LIST - scanned['sctp'])})")
        for proto in ("tcp", "udp", "sctp"):
            if opened[proto]:
                fails.append(f"{proto.upper()} open from a non-allowlisted host: {sorted(opened[proto])}")
    else:
        want = ALLOW_TCP[d7]
        if opened["tcp"] != want:
            fails.append(f"allowlisted TCP open set {sorted(opened['tcp'])} != {sorted(want)} (D7 {d7})")
    return {"result": "FAIL" if fails else "PASS", "failures": fails, **report}


def render_scan_txt(mode, label, d7, verdict, parsed):
    lines = [f"# E7 scan, mode={mode}, label={label}, D7={d7}", "target: <vm>   scanner: <scanner>",
             f"nmap versions: {sorted({p['nmap_version'] for p in parsed if p['nmap_version']})}",
             f"result: {verdict['result']}"]
    for f in verdict["failures"]:
        lines.append(f"  FAIL: {f}")
    for proto in ("tcp", "udp", "sctp"):
        lines.append(f"{proto}: scanned {verdict['coverage'].get(proto, 0)} ports; open {verdict['open'][proto]}; "
                     f"open|filtered {verdict['open|filtered'][proto]}")
    extra = [p for x in parsed for p in x["ports"] if "extraports" in p]
    for e in extra:
        lines.append(f"extraports: {e['extraports']} {e['state']}")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ NAD

def evaluate_nad(obj, lan_nic):
    fails, seen = [], []
    for it in obj.get("items", []):
        md = it.get("metadata", {})
        name = f"{md.get('namespace')}/{md.get('name')}"
        raw = (it.get("spec") or {}).get("config") or "{}"
        try:
            cfg = json.loads(raw)
        except ValueError:
            fails.append(f"{name}: config is not JSON (cannot rule out LAN attachment)")
            continue
        plugins = cfg.get("plugins") or [cfg]
        for pl in plugins:
            t = pl.get("type")
            master = pl.get("master") or pl.get("device")
            seen.append({"nad": name, "type": t, "master": master})
            if master == lan_nic:
                fails.append(f"{name}: {t} on the LAN NIC")
            elif t in ("macvlan", "ipvlan") and not master:
                fails.append(f"{name}: {t} without master (defaults to the default-route NIC)")
            elif t == "host-device" and (pl.get("device") == lan_nic or pl.get("hwaddr")):
                fails.append(f"{name}: host-device may move a host NIC into a pod")
    return {"result": "FAIL" if fails else "PASS", "failures": fails, "nads": seen}


# ------------------------------------------------------------------ nft

def evaluate_nft(text):
    m = re.search(r"table inet neoncore_guard \{(.*?)\n\}", text, re.S)
    out = {"table_present": bool(m)}
    body = m.group(1) if m else ""
    # nft prints the standard priority -150 by its name, "mangle".
    out["prerouting_minus150"] = bool(re.search(r"type filter hook prerouting priority (-150|mangle);", body))
    out["ct_invalid_drop"] = "ct state invalid drop" in body
    out["established_accept"] = bool(re.search(r"ct state (established,related|related,established) accept", body))
    out["final_drop_with_counter"] = bool(re.search(r"counter packets \d+ bytes \d+ drop", body))
    out["allow_ports_rule"] = bool(re.search(r"tcp dport \{[^}]*22[^}]*\}", body)) or "tcp dport 22" in body
    out["result"] = "PASS" if all(out[k] for k in ("table_present", "prerouting_minus150", "ct_invalid_drop",
                                                   "final_drop_with_counter")) else "FAIL"
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="E7 parsers")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--mode", choices=("nonallow", "allow"), required=True)
    s.add_argument("--d7", choices=("a", "b"), default="a")
    s.add_argument("--label", required=True)
    s.add_argument("--out-dir", required=True)
    s.add_argument("xml", nargs="+")
    n = sub.add_parser("nad")
    n.add_argument("--lan-nic", required=True)
    n.add_argument("--out", required=True)
    n.add_argument("json")
    f = sub.add_parser("nft")
    f.add_argument("--out", required=True)
    f.add_argument("ruleset")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "scan":
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", a.label):
                ap.error("label: [A-Za-z0-9_-]{1,32}")
            parsed = []
            for x in a.xml:
                with open(x, encoding="utf-8", errors="replace") as fh:
                    parsed.append(parse_nmap_xml(fh.read()))
            v = evaluate_scan(parsed, a.mode, a.d7)
            base = os.path.join(a.out_dir, f"scan-{a.mode}-{a.label}")
            common.write_text(base + ".txt", render_scan_txt(a.mode, a.label, a.d7, v, parsed))
            common.write_json(base + ".json", v)
        elif a.cmd == "nad":
            if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,15}", a.lan_nic):
                ap.error("lan-nic: interface name")
            with open(a.json, encoding="utf-8") as fh:
                v = evaluate_nad(json.load(fh), a.lan_nic)
            common.write_json(a.out, v)
        else:
            with open(a.ruleset, encoding="utf-8", errors="replace") as fh:
                v = evaluate_nft(fh.read())
            common.write_json(a.out, v)
    except (ParseError, ValueError, OSError) as e:
        print(f"scan_parse: {e}", file=sys.stderr)
        return 2
    print(f"{a.cmd}: {v['result']}")
    for f in v.get("failures", []):
        print("  " + f)
    return 0 if v["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
