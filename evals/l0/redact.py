#!/usr/bin/env python3
"""NeonCore L0 redaction filter (plan L0 section 4 "Redaction", security review S-B5).

One fail-closed filter for every write under project/notes/L0.md and
project/reports/L0/**. Owned by the evaluator; builders do not edit it.

Steps
  1. Site values from the process environment (never from the lab env file):
     PVE_ENDPOINT (host and full URL), PVE_API_TOKEN, PVE_TLS_FINGERPRINT, every
     TF_VAR_*, every PROXMOX_VE_* (the mapped copies), LAB_ADMIN_CIDR,
     LAB_SSH_PUBKEY_FILE, LAB_SSH_KEY_FILE, REDACT_EXTRA_VALUES (comma-separated,
     only adds values), plus this machine's own hostname.
  2. Structure: nodeName, hostIP(s), hostname, node / host_ip labels, kube context
     and cluster names, node InternalIP/ExternalIP/Hostname addresses, k3s/flannel
     node annotations, Prometheus discovery meta labels, and `instance` labels whose
     host is not an allowlisted lab address or a cluster-internal name.
  3. Any IPv4 outside the documented lab ranges becomes <ip>; any global or ULA
     IPv6 becomes <ip6>.
  4. Fail closed: after writing, the file is re-scanned for every step-1 value, any
     un-redacted structural value and any non-allowlisted RFC1918 IPv4. On a hit the
     file is deleted and the exit code is 3. Hits are reported by line number and
     category only, never by value.

ANSI escape sequences are removed. Every other control or invisible format character
(NUL included) becomes a newline, so values never run into the next one (S-I2). Tab and
newline are kept.

Secret class (S-I2): the API token (full, bare, USER@REALM!TOKENID, secret, user) and
every TLS fingerprint form (with or without colons) are matched as case-insensitive
plain substrings with no word-boundary check, in redaction and in the scan. A weak part
(shorter than 4 characters, all digits, or a protected project word) stays contextual.

Inputs (S-I2): a path whose realpath is under /proc/, /sys/ or /dev/, or that is not a
regular file, is refused with exit 2 (checked again on the opened descriptor). Stdin
`-` stays allowed. The path is never echoed.

Run as a file, not as a module: `python3 -I evals/l0/redact.py ...` (under `-I` the
current directory is not on sys.path, so `-m evals.l0.redact` does not import).

CLI
  redact.py -o OUT [IN|-]           redact IN (default stdin) into OUT, then verify
  redact.py --append -o OUT [IN|-]  append the redacted text to OUT, then verify
  redact.py --stdout [IN|-]         redact to stdout (for piping into other tools;
                                    no file is written, so no post-write scan)
  redact.py --scan FILE...          scan only; exit 0 if clean, 3 on any hit
  redact.py --describe              count of loaded values per variable and match mode
                                    (plain, context, secret); never prints a value

  --format auto|json|text   (default auto: JSON if the whole input parses as JSON)
  --allow-no-site-values    proceed when no step-1 site variable is set in the
                            environment (the default refuses, exit 4)

Exit codes: 0 ok, 2 usage/IO error, 3 sensitive value found after redaction (output
deleted) or scan hit, 4 no site values loaded and --allow-no-site-values not given.
"""
import argparse
import ipaddress
import json
import os
import re
import socket
import stat
import sys
import tempfile

# ------------------------------------------------------------------ allowlists

# Documented lab ranges (plan section 4, Redaction step 3): K3s default pod and
# service CIDRs, the UE pool, and the addresses already in the phase manifests.
LAB_ALLOW_NETS = [ipaddress.ip_network(n) for n in (
    "10.42.0.0/16",      # K3s pod CIDR (default, unchanged flags)
    "10.43.0.0/16",      # K3s service CIDR (default)
    "10.45.0.0/16",      # UE pool (phase2/manifests/01-configmaps.yaml)
    "192.168.200.0/24",  # phase1/test-macvlan-nad.yaml (never applied)
    "8.8.8.8/32", "8.8.4.4/32",  # UE DNS / ping target (manifests)
    "0.0.0.0/32",        # bind-any (phase0 compose)
    "127.0.0.0/8",       # loopback
)]
RFC1918 = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]

PLACEHOLDER_RE = re.compile(r"^<[^<>\s]*>")

# Values that are also ordinary project words. A site value equal to one of these
# (or shorter than 4 chars, or all digits) is only replaced in key/value context.
PROTECTED_WORDS = {
    "neoncore", "neoncore-lab", "monitoring", "kube-system", "default", "local",
    "local-lvm", "localhost", "ubuntu", "root", "admin", "true", "false", "none",
    "null", "yes", "no", "lab", "node", "pve", "data", "test", "user", "k3s",
}

# Keyword context for contextual matching, by variable name.
CONTEXT_KEYWORDS = {
    "TF_VAR_vm_id": ["vmid", "vm_id", "vm-id", "qemu", "lxc", "vm", "id"],
    "TF_VAR_template_vm_id": ["vmid", "vm_id", "template", "template_vm_id", "clone", "qemu", "vm"],
    "TF_VAR_vlan_id": ["vlan", "vlan_id", "vlan-id", "tag"],
    "TF_VAR_pool_id": ["pool", "pools", "pool_id", "poolid"],
    "TF_VAR_datastore_id": ["storage", "datastore", "datastore_id", "storage_id"],
    "TF_VAR_image_datastore_id": ["storage", "datastore", "datastore_id", "image_datastore_id"],
    "TF_VAR_bridge": ["bridge", "bridges", "vmbr"],
    "TF_VAR_vm_user": ["user", "username", "ciuser", "allowusers", "vm_user", "login"],
    "TF_VAR_node_name": ["node", "nodes", "node_name", "nodename"],
}

PLACEHOLDERS = {
    "PVE_ENDPOINT": "<pve-endpoint>",
    "PVE_ENDPOINT#host": "<pve-host>",
    "PVE_API_TOKEN": "<token>",
    "PVE_TLS_FINGERPRINT": "<fingerprint>",
    "LAB_ADMIN_CIDR": "<admin-cidr>",
    "LAB_ADMIN_CIDR#ip": "<admin-ip>",
    "TF_VAR_ipv4_cidr": "<vm-cidr>",
    "TF_VAR_ipv4_cidr#ip": "<vm>",
    "HOSTNAME#self": "<hostname>",
}

SITE_VAR_RE = re.compile(r"^(TF_VAR_\w+|PROXMOX_VE_\w+|PVE_ENDPOINT|PVE_API_TOKEN|"
                         r"PVE_TLS_FINGERPRINT|LAB_ADMIN_CIDR|LAB_SSH_PUBKEY_FILE|"
                         r"LAB_SSH_KEY_FILE)$")
# Secret class (S-I2): the API token (and PROXMOX_VE_API_TOKEN, mapped to it) with each
# part, and every TLS fingerprint form. Matched as case-insensitive plain substrings with
# no word-boundary check, in redaction and scan. A part that is weak (shorter than 4
# characters, all digits, or a protected project word such as a token id "neoncore")
# stays contextual, because substring-replacing it would mangle unrelated text; the
# secret itself and the full token are never weak.
SECRET_CLASS = {"PVE_API_TOKEN", "PVE_TLS_FINGERPRINT"}
# Never treated as a value source even if set (not site data, or booleans).
SITE_VAR_SKIP = {"PROXMOX_VE_INSECURE"}

# --------------------------------------------------------------- step 0: control

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u0080-\u009f​-‏‪-‮⁦-⁩]")


def strip_control(s: str) -> str:
    """ANSI escape sequences are removed (so `key:<ESC>[1m value` stays a key/value
    line). Every other control or invisible format character, NUL included, becomes a
    newline. Deleting them would join a value to whatever follows it (for example the
    NUL-separated /proc/<pid>/environ), so a boundary-checked value would be missed
    (security review S-I2)."""
    s = ANSI_RE.sub("", s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return CTRL_RE.sub("\n", s)


# --------------------------------------------------------------- step 1: values

class SiteValue:
    """A value to replace. mode 'plain' = boundary match anywhere; 'context' = only
    after one of its keywords."""

    def __init__(self, name, value, placeholder, mode="plain", keywords=None, icase=False):
        self.name = name
        self.value = value
        self.placeholder = placeholder
        self.mode = mode
        self.keywords = keywords or []
        v = re.escape(value)
        flags = re.IGNORECASE if icase else 0
        if mode == "secret":
            # Secret class (S-I2): plain substring, no lookaround, any case. A token or
            # fingerprint directly followed by a letter or digit is still replaced.
            self.rx = re.compile(v, re.IGNORECASE)
        elif mode == "plain":
            self.rx = re.compile(r"(?<![\w-])" + v + r"(?![\w-])" if value[:1].isalnum() and value[-1:].isalnum()
                                 else v, flags)
        else:
            kw = "|".join(re.escape(k) for k in sorted(self.keywords, key=len, reverse=True))
            self.rx = re.compile(r"(?i:(?<![\w])(?:" + kw + r"))(?:[\"']?\s*[:=/]\s*[\"']?|\s+[\"']?|[-_#])(?P<v>"
                                 + v + r")(?![\w-])", flags)

    def sub(self, text):
        if self.mode in ("plain", "secret"):
            return self.rx.sub(self.placeholder, text)
        return self.rx.sub(lambda m: m.group(0)[: m.start("v") - m.start(0)] + self.placeholder, text)

    def find(self, text):
        return [m.start() for m in self.rx.finditer(text)]


def _split_list(v):
    return [p for p in re.split(r"[,\s\[\]\"';]+", v) if p]


def _is_weak(value):
    return len(value) < 4 or value.isdigit() or value.lower() in PROTECTED_WORDS


def _host_of_url(v):
    m = re.match(r"^[a-z][a-z0-9+.-]*://(\[[^\]]+\]|[^/:?#]+)", v, re.I)
    return m.group(1).strip("[]") if m else None


def load_site_values(env=None, include_self_hostname=True):
    """Return (values, n_site_vars_found). Never logs values."""
    env = os.environ if env is None else env
    found = 0
    raw = []  # (name, value, placeholder)
    for name in sorted(env):
        if name in SITE_VAR_SKIP or not SITE_VAR_RE.match(name):
            continue
        val = env.get(name, "")
        if not val or not val.strip():
            continue
        found += 1
        val = val.strip()
        base = name
        if name.startswith("PROXMOX_VE_"):  # mapped copies -> same placeholder family
            base = {"PROXMOX_VE_ENDPOINT": "PVE_ENDPOINT",
                    "PROXMOX_VE_API_TOKEN": "PVE_API_TOKEN"}.get(name, name)
        ph = PLACEHOLDERS.get(base, f"<site:{base}>")
        if base == "PVE_ENDPOINT":
            raw.append((base, val, ph))
            raw.append((base, val.rstrip("/"), ph))
            host = _host_of_url(val) or val
            raw.append((base + "#host", host, PLACEHOLDERS["PVE_ENDPOINT#host"]))
        elif base == "PVE_API_TOKEN":
            # [PVEAPIToken=]USER@REALM!TOKENID=SECRET: the full value, the bare token,
            # USER@REALM!TOKENID, the secret, the user (USER@REALM) and the token id.
            # Names carry the part kind (never the value) for --describe and scan hits.
            raw.append((base + "#full", val, ph))
            bare = re.sub(r"^PVEAPIToken=", "", val)
            raw.append((base + "#full", bare, ph))
            ident, _, secret = bare.partition("=")
            raw.append((base + "#ident", ident, ph))
            if secret:
                raw.append((base + "#secret", secret, ph))
            if "!" in ident:
                user, tokid = ident.split("!", 1)
                raw.append((base + "#user", user, ph))
                raw.append((base + "#tokid", tokid, ph))
        elif base == "PVE_TLS_FINGERPRINT":
            hexonly = re.sub(r"[^0-9A-Fa-f]", "", val)
            raw.append((base, val, ph))
            if hexonly:
                # Every form: with and without colons (case is handled by the matcher).
                raw.append((base, hexonly, ph))
                raw.append((base, ":".join(hexonly[i:i + 2] for i in range(0, len(hexonly), 2)), ph))
        elif base in ("LAB_ADMIN_CIDR", "TF_VAR_ipv4_cidr"):
            raw.append((base, val, ph))
            ip = val.split("/")[0]
            raw.append((base + "#ip", ip, PLACEHOLDERS[base + "#ip"]))
        elif base == "TF_VAR_dns_servers" or base == "TF_VAR_gateway":
            for p in _split_list(val):
                raw.append((base, p, ph))
        elif base in ("LAB_SSH_PUBKEY_FILE", "LAB_SSH_KEY_FILE"):
            raw.append((base, val, ph))
            raw.append((base, os.path.basename(val), ph))
            home = env.get("HOME")
            if home and val.startswith(home):
                raw.append((base, "~" + val[len(home):], ph))
        else:
            raw.append((base, val, ph))
    for v in _split_list(env.get("REDACT_EXTRA_VALUES", "").replace(",", " ")):
        raw.append(("REDACT_EXTRA_VALUES", v, "<site:extra>"))  # host-like: case-insensitive
    if include_self_hostname:
        for hn in {socket.gethostname(), os.uname().nodename, socket.gethostname().split(".")[0]}:
            if hn and hn.lower() not in ("localhost", "neoncore-lab"):
                raw.append(("HOSTNAME#self", hn, PLACEHOLDERS["HOSTNAME#self"]))

    values, seen = [], set()
    for name, val, ph in raw:
        if not val or (name, val) in seen:
            continue
        seen.add((name, val))
        is_hostlike = name in ("PVE_ENDPOINT#host", "HOSTNAME#self", "TF_VAR_node_name",
                              "REDACT_EXTRA_VALUES") \
            or name == "PVE_TLS_FINGERPRINT"
        is_secret = name.split("#")[0] in SECRET_CLASS
        if is_secret and not _is_weak(val):
            values.append(SiteValue(name, val, ph, mode="secret"))
        elif _is_weak(val):
            kws = CONTEXT_KEYWORDS.get(name.split("#")[0])
            if not kws:
                suffix = name.split("#")[0].replace("TF_VAR_", "").replace("PROXMOX_VE_", "").lower()
                kws = [suffix] + [p for p in suffix.split("_") if len(p) > 2]
            values.append(SiteValue(name, val, ph, mode="context", keywords=kws, icase=is_hostlike))
        else:
            values.append(SiteValue(name, val, ph, icase=is_hostlike))
    values.sort(key=lambda sv: len(sv.value), reverse=True)
    return values, found


def apply_values(text, values):
    for sv in values:
        text = sv.sub(text)
    return text


# ------------------------------------------------------------- step 2: structure

STRUCT_KEY_RE = re.compile(
    r"^(?:nodeName|node_name|nodename|hostIP|hostIPs|host_ip|hostIp|hostname|hostName|"
    r"host_name|node|current-context|currentContext|cluster|context|"
    r"kubernetes\.io/hostname|k3s\.io/hostname|k3s\.io/internal-ip|k3s\.io/external-ip|"
    r"k3s\.io/node-args|k3s\.io/node-config-hash|"
    r"flannel\.alpha\.coreos\.com/public-ip|flannel\.alpha\.coreos\.com/public-ip-overwrite|"
    r"alpha\.kubernetes\.io/provided-node-ip|kubernetes_io_hostname|"
    r"__meta_kubernetes_\w*(?:node_name|host_ip|node_address_\w+|node_label_kubernetes_io_hostname))$")
ADDRESS_TYPES = {"InternalIP", "ExternalIP", "Hostname", "InternalDNS", "ExternalDNS"}


def _ph(key):
    k = key.split("/")[-1].replace(".", "_")
    return f"<{k}>"


def _instance_ok(val):
    """True if an `instance` value is safe to keep (lab-internal)."""
    if not isinstance(val, str):
        return True
    if PLACEHOLDER_RE.match(val):
        return True
    host = val
    m = re.match(r"^\[([^\]]+)\](?::\d+)?$", val)
    if m:
        host = m.group(1)
    elif val.count(":") == 1:
        host = val.split(":")[0]
    if host in ("localhost",) or host.endswith(".svc.cluster.local") or host.endswith(".svc") \
            or host.endswith(".cluster.local"):
        return True
    try:
        return _ip_allowed(ipaddress.ip_address(host))
    except ValueError:
        return False


def redact_struct_obj(obj):
    """Walk parsed JSON; return a redacted copy."""
    if isinstance(obj, dict):
        out = {}
        is_addr = obj.get("type") in ADDRESS_TYPES and "address" in obj
        for k, v in obj.items():
            if is_addr and k == "address":
                out[k] = "<node-address>"
            elif isinstance(k, str) and STRUCT_KEY_RE.match(k) and v not in (None, "", [], {}):
                if isinstance(v, (dict, list)) and k in ("cluster", "context"):
                    out[k] = redact_struct_obj(v)  # kubeconfig blocks: recurse
                elif isinstance(v, list):
                    out[k] = [_ph(k) if not isinstance(x, dict) else
                              {kk: (_ph(k) if kk in ("ip", "address") else redact_struct_obj(vv))
                               for kk, vv in x.items()} for x in v]
                elif isinstance(v, str) and PLACEHOLDER_RE.match(v):
                    out[k] = v
                elif isinstance(v, (bool, int, float)) and k in ("node", "cluster", "context"):
                    out[k] = v
                else:
                    out[k] = _ph(k)
            elif k == "instance" and not _instance_ok(v):
                out[k] = "<instance>"
            else:
                out[k] = redact_struct_obj(v)
        # kubeconfig: contexts/clusters entries carry their name in "name"
        return out
    if isinstance(obj, list):
        return [redact_struct_obj(x) for x in obj]
    return obj


def _redact_kubeconfig_names(obj):
    if isinstance(obj, dict) and obj.get("kind") == "Config" and "clusters" in obj:
        for sect in ("clusters", "contexts", "users"):
            for e in obj.get(sect) or []:
                if isinstance(e, dict) and "name" in e:
                    e["name"] = f"<{sect[:-1]}-name>"
    return obj


TEXT_KEYS = (r"nodeName|node_name|nodename|hostIPs?|host_ip|hostIp|hostname|hostName|host_name|"
             r"node|current-context|currentContext|cluster|context|"
             r"kubernetes\.io/hostname|k3s\.io/hostname|k3s\.io/internal-ip|k3s\.io/external-ip|"
             r"flannel\.alpha\.coreos\.com/public-ip(?:-overwrite)?|"
             r"alpha\.kubernetes\.io/provided-node-ip|kubernetes_io_hostname|"
             r"__meta_kubernetes_\w*(?:node_name|host_ip|node_address_\w+|node_label_kubernetes_io_hostname)|"
             r"InternalIP|ExternalIP|Hostname|InternalDNS|ExternalDNS|Node")
TEXT_KV_RE = re.compile(
    r"(?P<pre>(?<![\w.\-/])[\"']?(?P<key>" + TEXT_KEYS + r")[\"']?[ \t]*(?:[:=])[ \t]*[\"']?)"
    r"(?P<val>[^\s\"',;{}\[\]\(\)]+)")
INSTANCE_RE = re.compile(r"(?P<pre>(?<![\w])[\"']?instance[\"']?[ \t]*[:=][ \t]*[\"']?)(?P<val>[^\s\"',;{}\[\]\(\)]+)")
# kubectl describe node: "  InternalIP:  x" handled above; kubeconfig "- name: x" under
# contexts/clusters is not structural in text mode (no section tracking).


GENERIC_TEXT_KEYS = {"node", "Node", "cluster", "context", "hostname", "Hostname", "nodename"}


def _kv_context_ok(m):
    """Generic words (node, cluster, ...) count as keys only in key/value syntax:
    at line start (after indent, '-', '{', ',', '('), quoted, or with '='. This keeps
    prose such as 'a live node: that' from being treated as structure."""
    if m.group("key") not in GENERIC_TEXT_KEYS:
        return True
    pre = m.group("pre")
    if pre[:1] in "\"'" or "=" in pre:
        return True
    s = m.string
    ls = s.rfind("\n", 0, m.start()) + 1
    before = s[ls:m.start()].rstrip()
    return before == "" or before[-1] in "-{,(" or before.endswith("- ")


# A Terraform reference such as `node_name = var.node_name` names an input variable;
# it is not a value. Only `var.`/`local.` followed by one HCL identifier (no dots or
# hyphens) is exempt, so a dotted or hyphenated host name is still redacted. A literal
# (`node_name = "pve1"`) and every JSON value stay redacted; the real site value is
# caught by step 1 wherever it appears.
TF_REF_RE = re.compile(r"(?:var|local)\.[A-Za-z_][A-Za-z0-9_]*")


def _text_kv_sub(m):
    key, val = m.group("key"), m.group("val")
    if PLACEHOLDER_RE.match(val) or not _kv_context_ok(m):
        return m.group(0)
    if TF_REF_RE.fullmatch(val) and not m.group("pre").rstrip().endswith(("\"", "'")):
        return m.group(0)
    if key in ("node", "Node", "cluster", "context") and re.fullmatch(r"\d+|true|false|null|ok|none|-", val, re.I):
        return m.group(0)
    if key == "Node" and val.startswith("<"):
        return m.group(0)
    return m.group("pre") + _ph(key)


def redact_struct_text(text):
    text = TEXT_KV_RE.sub(_text_kv_sub, text)
    text = INSTANCE_RE.sub(lambda m: m.group(0) if _instance_ok(m.group("val"))
                           else m.group("pre") + "<instance>", text)
    return text


# ---------------------------------------------------------------- step 3: IPs

IPV4_RE = re.compile(r"(?<![\w.])((?:\d{1,3}\.){3}\d{1,3})(/\d{1,2})?(?![\w]|\.\d)")
IPV6_RE = re.compile(r"(?<![\w:.])((?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4})(/\d{1,3})?(?![\w:])")


# Spec clause numbers look like dotted quads (TS 24.008 §10.5.6.3). scan() skips a match
# only when the text right before it on the same line is a clause context: "§", "clause",
# "subclause"/"sub-clause", a TS/TR number ("TS 24.008 10.5.6.3"), or a clause-prefixed
# dotted number joined by "," "/" "and" "or" "to" ("clauses 9.11.4.6 and 10.5.6.3"). Every
# component must be < 100, so 172.16/12 and 192.168/16 are never exempt. Redaction itself
# does not use this exemption (fail-closed: a clause may come out as <ip>).
_CLAUSE_WORD = r"(?:§|clauses?|sub-?clauses?|T[SR]\s+\d{2}\.\d{3}(?:-\d+)?(?:\s+(?:§|clauses?|sub-?clauses?))?)"
CLAUSE_CTX_RE = re.compile(
    r"(?:" + _CLAUSE_WORD + r"\s*"
    r"|" + _CLAUSE_WORD + r"\s*\d+(?:\.\d+)+[a-z]?\s*(?:[,/;]|\band\b|\bor\b|\bto\b|–|-)\s*(?:and\s+|or\s+)?"
    r")$", re.I)


def _clause_context(text, start, dotted):
    if any(int(p) >= 100 for p in dotted.split(".")):
        return False
    line_start = text.rfind("\n", 0, start) + 1
    before = text[max(line_start, start - 80):start]
    return CLAUSE_CTX_RE.search(before) is not None


def _ip_allowed(ip):
    if ip.version == 4:
        return any(ip in n for n in LAB_ALLOW_NETS)
    return ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast


def _sub_ipv4(m):
    try:
        ip = ipaddress.IPv4Address(m.group(1))
    except ValueError:
        return m.group(0)
    if _ip_allowed(ip):
        return m.group(0)
    return "<ip>" + (m.group(2) or "")


def _sub_ipv6(m):
    cand = m.group(1)
    if cand.count(":") < 2:
        return m.group(0)
    try:
        ip = ipaddress.IPv6Address(cand)
    except ValueError:
        return m.group(0)
    if _ip_allowed(ip) or not (ip.is_global or ip.is_private):
        return m.group(0)
    return "<ip6>" + (m.group(2) or "")


def redact_ips(text):
    text = IPV4_RE.sub(_sub_ipv4, text)
    return IPV6_RE.sub(_sub_ipv6, text)


# --------------------------------------------------------------- pipeline

def redact(text, values, fmt="auto"):
    text = strip_control(text)
    text = apply_values(text, values)
    obj = None
    if fmt in ("auto", "json"):
        try:
            obj = json.loads(text)
        except ValueError:
            if fmt == "json":
                raise
    if obj is not None and isinstance(obj, (dict, list)):
        obj = _redact_kubeconfig_names(redact_struct_obj(obj))
        text = json.dumps(obj, indent=2, sort_keys=False, ensure_ascii=False) + "\n"
    text = redact_struct_text(text)
    text = redact_ips(text)
    text = apply_values(text, values)  # values could reappear after re-serialisation
    return text


def redact_obj(obj, values):
    """Convenience for scripts: redact a Python object, return the redacted object."""
    return json.loads(redact(json.dumps(obj), values, fmt="json"))


# ---------------------------------------------------------------- step 4: scan

def scan(text, values):
    """Return a list of (line_no, category). Never includes the matched value."""
    hits = []

    def line_of(pos):
        return text.count("\n", 0, pos) + 1

    for sv in values:
        for pos in sv.find(text):
            hits.append((line_of(pos), f"site value {sv.name}"))
    for m in IPV4_RE.finditer(text):
        try:
            ip = ipaddress.IPv4Address(m.group(1))
        except ValueError:
            continue
        if any(ip in n for n in RFC1918) and not _ip_allowed(ip) \
                and not (m.group(2) is None and _clause_context(text, m.start(), m.group(1))):
            hits.append((line_of(m.start()), "non-allowlisted RFC1918 IPv4"))
    for m in IPV6_RE.finditer(text):
        try:
            ip = ipaddress.IPv6Address(m.group(1))
        except ValueError:
            continue
        if not _ip_allowed(ip) and (ip.is_global or ip.is_private) and m.group(1).count(":") >= 2:
            hits.append((line_of(m.start()), "global/ULA IPv6"))
    for m in TEXT_KV_RE.finditer(text):
        if _text_kv_sub(m) != m.group(0):
            hits.append((line_of(m.start()), f"structural key {m.group('key')}"))
    for m in INSTANCE_RE.finditer(text):
        if not _instance_ok(m.group("val")):
            hits.append((line_of(m.start()), "instance label with node address"))
    if ANSI_RE.search(text):
        hits.append((line_of(ANSI_RE.search(text).start()), "ANSI escape"))
    return sorted(set(hits))


def _report_hits(path, hits, stream=sys.stderr):
    print(f"redact: {len(hits)} sensitive hit(s) in {os.path.basename(path)}", file=stream)
    for ln, cat in hits[:50]:
        print(f"  line {ln}: {cat}", file=stream)


def write_redacted(path, text, values, append=False, fmt="auto"):
    """Redact `text`, write (or append) to `path`, re-scan, delete on hit.
    Returns 0 or 3. Raises OSError on IO problems."""
    red = redact(text, values, fmt=fmt)
    old = ""
    if append and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
        if old and not old.endswith("\n"):
            old += "\n"
    new = old + red
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    # Pre-check on a temp file in the same dir; the original stays untouched on a hit.
    fd, tmp = tempfile.mkstemp(prefix=".redact-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new)
        with open(tmp, encoding="utf-8") as f:
            hits = scan(f.read(), values)
        if hits:
            _report_hits(path, hits)
            os.unlink(tmp)
            return 3
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    # Post-write re-scan of the file as it now exists on disk.
    with open(path, encoding="utf-8") as f:
        hits = scan(f.read(), values)
    if hits:
        _report_hits(path, hits)
        os.unlink(path)
        return 3
    return 0


REFUSED_INPUT_PREFIXES = ("/proc/", "/sys/", "/dev/")


class InputRefused(Exception):
    pass


def read_input(path):
    """Read an input file for redaction or scanning (S-I2). Refuses a path whose
    realpath is under /proc/, /sys/ or /dev/ (for example /proc/self/environ, which
    holds the lab env of a wrapper child) and anything that is not a regular file
    (FIFO, device, socket, directory). /proc files report as regular in stat, so the
    prefix check is needed as well; the type is checked on the opened descriptor.
    Messages never include the path."""
    def refused(real):
        return real.startswith(REFUSED_INPUT_PREFIXES) or real in ("/proc", "/sys", "/dev")

    if refused(os.path.realpath(path)):
        raise InputRefused("input under /proc, /sys or /dev refused")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise InputRefused("input is not a regular file")
        # Re-check what was actually opened (a symlink swapped after the first check).
        fdlink = f"/proc/self/fd/{fd}"
        if os.path.islink(fdlink) and refused(os.path.realpath(fdlink)):
            raise InputRefused("input under /proc, /sys or /dev refused")
        with os.fdopen(fd, encoding="utf-8", errors="replace") as f:
            fd = None
            return f.read()
    finally:
        if fd is not None:
            os.close(fd)


def scan_files(paths, values):
    rc = 0
    for p in paths:
        try:
            hits = scan(read_input(p), values)
        except InputRefused as e:
            print(f"redact: refused input: {e}", file=sys.stderr)
            rc = max(rc, 2)
            continue
        except OSError as e:
            print(f"redact: cannot read {os.path.basename(p)}: {e.strerror}", file=sys.stderr)
            rc = max(rc, 2)
            continue
        if hits:
            _report_hits(p, hits, stream=sys.stdout)
            rc = 3
        else:
            print(f"redact: 0 hits in {os.path.basename(p)}")
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(description="NeonCore L0 fail-closed redaction filter (S-B5)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("-o", "--output", help="output file (redacted, re-scanned after writing)")
    g.add_argument("--stdout", action="store_true", help="write redacted text to stdout")
    g.add_argument("--scan", action="store_true", help="scan the given files only")
    g.add_argument("--describe", action="store_true",
                   help="print how many values are loaded per variable and match mode (no values)")
    ap.add_argument("--append", action="store_true", help="append to --output instead of replacing")
    ap.add_argument("--format", choices=("auto", "json", "text"), default="auto")
    ap.add_argument("--allow-no-site-values", action="store_true",
                    help="proceed when no site variable is set in the environment")
    ap.add_argument("inputs", nargs="*", help="input file (default stdin); files to scan with --scan")
    a = ap.parse_args(argv)

    values, found = load_site_values()
    if found == 0 and not a.allow_no_site_values:
        print("redact: no site variables in the environment (run under scripts/labenv, or pass "
              "--allow-no-site-values where no site value can occur)", file=sys.stderr)
        return 4

    if a.describe:
        counts = {}
        for sv in values:
            key = (sv.name, sv.mode)
            counts[key] = counts.get(key, 0) + 1
        print(f"site variables found: {found}")
        for (name, mode), n in sorted(counts.items()):
            print(f"  {name}: {n} {mode}")
        return 0

    if a.scan:
        if not a.inputs:
            ap.error("--scan needs at least one file")
        return scan_files(a.inputs, values)

    if len(a.inputs) > 1:
        ap.error("one input only")
    src = a.inputs[0] if a.inputs else "-"
    try:
        if src == "-":
            text = sys.stdin.read()
        else:
            text = read_input(src)
    except InputRefused as e:
        print(f"redact: refused input: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"redact: cannot read input: {e.strerror}", file=sys.stderr)
        return 2
    try:
        if a.stdout:
            red = redact(text, values, fmt=a.format)
            hits = scan(red, values)
            if hits:
                _report_hits("<stdout>", hits)
                return 3
            sys.stdout.write(red)
            return 0
        return write_redacted(a.output, text, values, append=a.append, fmt=a.format)
    except ValueError:
        print("redact: input is not valid JSON (--format json)", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"redact: write failed: {e.strerror}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
