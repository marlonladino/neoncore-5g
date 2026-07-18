"""Ephemeral scenario-UE Pod: apply/wait/delete/deregister.

Mirrors phase2/manifests/05-ueransim.yaml's UE container spec (same image,
NET_ADMIN capability, /dev/net/tun hostPath mount) but built as a Python dict so it
can carry per-scenario identity/policy env vars. Uses label app=scenario-ue (never
app=ue) so it can never be confused with the long-lived Deployment-managed UE pod
that the phase5 CLI's ping-test/health checks key off of.
"""

import json
import time

from . import kubectl_util as ku

IMAGE = "gradiant/ueransim:3.3.0"


def build_manifest(name: str, *, msisdn: str, k: str, opc: str, apn: str, sst: int, sd: str,
                    slug: str, gnb_hostname: str = "gnb") -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": ku.NAMESPACE,
            "labels": {"app": "scenario-ue", "neoncore.dev/scenario": slug},
        },
        "spec": {
            "restartPolicy": "Never",
            "containers": [
                {
                    "name": "ue",
                    "image": IMAGE,
                    "args": ["ue"],
                    "securityContext": {"capabilities": {"add": ["NET_ADMIN"]}},
                    "env": [
                        {"name": "GNB_HOSTNAME", "value": gnb_hostname},
                        {"name": "MCC", "value": "999"},
                        {"name": "MNC", "value": "70"},
                        {"name": "MSISDN", "value": msisdn},
                        {"name": "KEY", "value": k},
                        {"name": "OP", "value": opc},
                        {"name": "OP_TYPE", "value": "OPC"},
                        {"name": "APN", "value": apn},
                        {"name": "SST", "value": str(sst)},
                        {"name": "SD", "value": sd},
                    ],
                    "resources": {"requests": {"cpu": "20m", "memory": "32Mi"}},
                    "volumeMounts": [{"name": "dev-tun", "mountPath": "/dev/net/tun"}],
                }
            ],
            "volumes": [
                {"name": "dev-tun", "hostPath": {"path": "/dev/net/tun", "type": "CharDevice"}}
            ],
        },
    }


def pod_name(slug: str) -> str:
    return f"scenario-ue-{slug}-{int(time.time())}"


async def apply(manifest: dict) -> ku.CmdResult:
    return await ku.run_cmd_stdin(
        "kubectl", "apply", "-f", "-", input_text=json.dumps(manifest), timeout=20
    )


async def delete(name: str) -> ku.CmdResult:
    return await ku.run_cmd(
        "kubectl", "-n", ku.NAMESPACE, "delete", "pod", name,
        "--ignore-not-found", "--wait=true", "--timeout=30s",
        timeout=35,
    )


async def exec_deregister(pod: str, imsi: str) -> ku.CmdResult:
    return await ku.run_cmd(
        "kubectl", "-n", ku.NAMESPACE, "exec", pod, "--",
        "nr-cli", f"imsi-{imsi}", "--exec", "deregister normal",
        timeout=20,
    )


async def sweep_leftovers() -> ku.CmdResult:
    """Delete any scenario-ue pods left behind by a crashed prior run."""
    return await ku.run_cmd(
        "kubectl", "-n", ku.NAMESPACE, "delete", "pod", "-l", "app=scenario-ue",
        "--ignore-not-found", timeout=30,
    )
