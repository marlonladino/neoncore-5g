"""Parametric Open5GS subscriber provisioning/deprovisioning for scenario automation.

Generalizes phase0/scripts/add-subscriber.js's schema (previously hardcoded to one
IMSI) into a function of arbitrary IMSI + policy fields. Builds a mongosh --eval
script by embedding a Python dict as JSON (valid JS syntax -- safe quoting for free,
no manual string interpolation/injection risk) and runs it via `kubectl exec` against
the mongo pod directly, no Job/ConfigMap round-trip needed per call.
"""

import json
import re

from . import kubectl_util as ku

MSISDN_RE = re.compile(r"^\d{10}$")
HEX32_RE = re.compile(r"^[0-9A-Fa-f]{32}$")
SD_RE = re.compile(r"^[0-9A-Fa-f]{6}$")


class ValidationError(ValueError):
    pass


def build_imsi(msisdn: str, mcc: str = "999", mnc: str = "70") -> str:
    if not MSISDN_RE.match(msisdn):
        raise ValidationError(f"msisdn must be exactly 10 digits, got {msisdn!r}")
    return f"{mcc}{mnc}{msisdn}"


def _validate(k: str, opc: str, sd: str, qos_index: int, arp_priority: int) -> None:
    if not HEX32_RE.match(k):
        raise ValidationError(f"k must be a 32-hex-char string, got {k!r}")
    if not HEX32_RE.match(opc):
        raise ValidationError(f"opc must be a 32-hex-char string, got {opc!r}")
    if not SD_RE.match(sd):
        raise ValidationError(f"sd must be a 6-hex-char string, got {sd!r}")
    if not (1 <= qos_index <= 255):
        raise ValidationError(f"qos_index (5QI) out of range: {qos_index}")
    if not (1 <= arp_priority <= 15):
        raise ValidationError(f"arp_priority out of range: {arp_priority}")


def build_provision_script(
    imsi: str,
    *,
    k: str,
    opc: str,
    apn: str = "internet",
    sst: int = 1,
    sd: str = "000001",
    qos_index: int = 9,
    arp_priority: int = 8,
    ambr_downlink_bps: int = 1_000_000_000,
    ambr_uplink_bps: int = 1_000_000_000,
    rau_tau_timer_minutes: int = 12,
) -> str:
    _validate(k, opc, sd, qos_index, arp_priority)
    ambr = {
        "downlink": {"value": ambr_downlink_bps, "unit": 0},
        "uplink": {"value": ambr_uplink_bps, "unit": 0},
    }
    doc = {
        "schema_version": 1,
        "imsi": imsi,
        "msisdn": [],
        "imeisv": [],
        "mme_host": [],
        "mme_realm": [],
        "purge_flag": [],
        "slice": [
            {
                "sst": sst,
                "sd": sd,
                "default_indicator": True,
                "session": [
                    {
                        "name": apn,
                        "type": 3,
                        "qos": {
                            "index": qos_index,
                            "arp": {
                                "priority_level": arp_priority,
                                "pre_emption_capability": 1,
                                "pre_emption_vulnerability": 2,
                            },
                        },
                        "ambr": ambr,
                        "pcc_rule": [],
                    }
                ],
            }
        ],
        "security": {"k": k, "op": None, "opc": opc, "amf": "8000"},
        "ambr": ambr,
        "access_restriction_data": 32,
        "network_access_mode": 0,
        "subscriber_status": 0,
        "operator_determined_barring": 0,
        "subscribed_rau_tau_timer": rau_tau_timer_minutes,
        "__v": 0,
    }
    return (
        "db = db.getSiblingDB('open5gs'); "
        f"db.subscribers.deleteMany({{ imsi: {json.dumps(imsi)} }}); "
        f"db.subscribers.insertOne({json.dumps(doc)}); "
        f"print('provisioned {imsi}');"
    )


def build_deprovision_script(imsi: str) -> str:
    return (
        "db = db.getSiblingDB('open5gs'); "
        f"print(db.subscribers.deleteMany({{ imsi: {json.dumps(imsi)} }}).deletedCount "
        "+ ' subscriber(s) removed');"
    )


async def provision_subscriber(imsi: str, **policy) -> ku.CmdResult:
    script = build_provision_script(imsi, **policy)
    mongo_pod = await ku.find_pod("mongo")
    if not mongo_pod:
        return ku.CmdResult(ok=False, output="no 'mongo' pod found")
    return await ku.run_cmd(
        "kubectl", "-n", ku.NAMESPACE, "exec", mongo_pod, "--",
        "mongosh", "--host", "mongo", "--quiet", "--eval", script,
        timeout=20,
    )


async def deprovision_subscriber(imsi: str) -> ku.CmdResult:
    script = build_deprovision_script(imsi)
    mongo_pod = await ku.find_pod("mongo")
    if not mongo_pod:
        return ku.CmdResult(ok=False, output="no 'mongo' pod found")
    return await ku.run_cmd(
        "kubectl", "-n", ku.NAMESPACE, "exec", mongo_pod, "--",
        "mongosh", "--host", "mongo", "--quiet", "--eval", script,
        timeout=20,
    )
