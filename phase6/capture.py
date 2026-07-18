"""Scoped per-scenario pcap capture.

Runs a second tcpdump process via kubectl exec into the already-running tracer pod
(phase4/manifests/02-tracer.yaml -- same hostNetwork/privileged visibility it already
has), rather than restarting that pod for a clean file (the pattern used once
manually per DEVLOG.md for the existing traces/rogue-ue-reject.pcap capture). A
second concurrent tcpdump on the same interface doesn't disrupt the continuous
background capture, and avoids repeated-restart churn across a fast scenario/test
loop.
"""

import os
import time

from . import kubectl_util as ku

PCAP_DIR = "/pcaps"
BPF_FILTER = "(sctp) or (udp port 8805) or (udp port 2152) or (tcp port 7777) or icmp"


def capture_name(slug: str, msisdn: str) -> str:
    ts = time.strftime("%Y%m%d-%H%M%S")
    return f"scenario-{slug}-{msisdn}-{ts}"


async def start(tracer_pod: str, name: str) -> ku.CmdResult:
    pcap = f"{PCAP_DIR}/{name}.pcap"
    log = f"{PCAP_DIR}/{name}.log"
    pid = f"{PCAP_DIR}/{name}.pid"
    cmd = (
        f"nohup tcpdump -i any -n -w {pcap} '{BPF_FILTER}' "
        f">{log} 2>&1 & echo $! > {pid}"
    )
    return await ku.run_cmd(
        "kubectl", "-n", ku.NAMESPACE, "exec", tracer_pod, "--", "sh", "-c", cmd,
        timeout=15,
    )


async def _pid_and_size(tracer_pod: str, name: str) -> tuple[bool, int]:
    pid = f"{PCAP_DIR}/{name}.pid"
    pcap = f"{PCAP_DIR}/{name}.pcap"
    res = await ku.run_cmd(
        "kubectl", "-n", ku.NAMESPACE, "exec", tracer_pod, "--", "sh", "-c",
        f"kill -0 $(cat {pid}) 2>/dev/null && stat -c%s {pcap} 2>/dev/null || echo -1",
        timeout=15,
    )
    try:
        size = int(res.output.strip().splitlines()[-1])
    except (ValueError, IndexError):
        size = -1
    return (res.ok and size >= 0), size


async def is_healthy(tracer_pod: str, name: str, settle_s: float = 3.0) -> tuple[bool, str]:
    """Confirm the capture process is alive AND the file is actually growing --
    not just PID liveness (DEVLOG documents a real prior incident where tcpdump
    stayed alive but silently stopped capturing after heavy pod churn)."""
    import asyncio

    alive1, size1 = await _pid_and_size(tracer_pod, name)
    if not alive1:
        return False, "capture process not running"
    await asyncio.sleep(settle_s)
    alive2, size2 = await _pid_and_size(tracer_pod, name)
    if not alive2:
        return False, "capture process died"
    if size2 <= size1:
        return False, f"capture file not growing ({size1} -> {size2} bytes)"
    return True, f"growing ({size1} -> {size2} bytes)"


async def stop(tracer_pod: str, name: str) -> ku.CmdResult:
    pid = f"{PCAP_DIR}/{name}.pid"
    # SIGINT (not TERM/KILL) so tcpdump finalizes the pcap the same way Ctrl-C does.
    return await ku.run_cmd(
        "kubectl", "-n", ku.NAMESPACE, "exec", tracer_pod, "--", "sh", "-c",
        f"kill -INT $(cat {pid}) 2>/dev/null; sleep 1; true",
        timeout=15,
    )


async def collect(tracer_pod: str, name: str, dest_dir: str) -> tuple[str | None, int]:
    os.makedirs(dest_dir, exist_ok=True)
    local_path = os.path.join(dest_dir, f"{name}.pcap")
    res = await ku.run_cmd(
        "kubectl", "cp", f"{ku.NAMESPACE}/{tracer_pod}:{PCAP_DIR}/{name}.pcap", local_path,
        timeout=30,
    )
    if not res.ok or not os.path.exists(local_path):
        return None, 0
    return local_path, os.path.getsize(local_path)
