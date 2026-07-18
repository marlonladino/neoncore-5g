"""Thin async wrappers around kubectl for the NeonCore 5G control center.

Deliberately shells out to kubectl (via asyncio subprocesses) rather than using the
Kubernetes Python client -- keeps the dependency footprint small and reuses the exact
manifests already validated in phase2/phase3/phase4, instead of re-encoding them as
API objects.
"""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

REPO_ROOT = os.path.expanduser("~/neoncore-5g")
KUBECONFIG = os.path.expanduser("~/.kube/config")

# Ordered: namespaces/configmaps before workloads, mongo before things that need it.
DEPLOY_MANIFESTS = [
    "phase2/manifests/00-namespace.yaml",
    "phase2/manifests/01-configmaps.yaml",
    "phase2/manifests/02-mongo.yaml",
    "phase2/manifests/03-nfs.yaml",
    "phase2/manifests/04-dbctl-job.yaml",
    "phase2/manifests/05-ueransim.yaml",
    "phase3/manifests/00-namespace.yaml",
    "phase3/manifests/01-prometheus-rbac.yaml",
    "phase3/manifests/02-prometheus-config.yaml",
    "phase3/manifests/03-prometheus.yaml",
    "phase3/manifests/04-kube-state-metrics.yaml",
    "phase3/manifests/05a-grafana-datasource-cm.yaml",
    "phase3/manifests/05b-grafana-dashboard-provider-cm.yaml",
    "phase3/manifests/05c-grafana-dashboard-json-cm.yaml",
    "phase3/manifests/06-grafana.yaml",
    "phase4/manifests/00-pvc.yaml",
    "phase4/manifests/01-tracer-configmap.yaml",
    "phase4/manifests/02-tracer.yaml",
]

TEARDOWN_NAMESPACES = ["neoncore", "monitoring"]


@dataclass
class PodInfo:
    namespace: str
    name: str
    phase: str
    ready: str
    restarts: int
    age_seconds: float
    node: str = ""


@dataclass
class CmdResult:
    ok: bool
    output: str


def _env():
    env = dict(os.environ)
    env["KUBECONFIG"] = KUBECONFIG
    return env


async def _stream_cmd(*args: str) -> AsyncIterator[str]:
    """Run a command, yielding stdout/stderr lines as they arrive."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=_env(),
        cwd=REPO_ROOT,
    )
    assert proc.stdout is not None
    async for raw_line in proc.stdout:
        yield raw_line.decode(errors="replace").rstrip("\n")
    await proc.wait()


async def _run_cmd(*args: str, timeout: float = 30) -> CmdResult:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=_env(),
            cwd=REPO_ROOT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        text = out.decode(errors="replace")
        return CmdResult(ok=(proc.returncode == 0), output=text)
    except asyncio.TimeoutError:
        return CmdResult(ok=False, output=f"timed out after {timeout}s")
    except FileNotFoundError as e:
        return CmdResult(ok=False, output=str(e))


async def deploy() -> AsyncIterator[str]:
    """Apply every manifest in order, yielding progress lines live."""
    for rel_path in DEPLOY_MANIFESTS:
        full_path = os.path.join(REPO_ROOT, rel_path)
        if not os.path.exists(full_path):
            yield f"[skip] {rel_path} (not found)"
            continue
        yield f"[apply] {rel_path}"
        async for line in _stream_cmd("kubectl", "apply", "-f", full_path):
            yield f"  {line}"
        if rel_path.endswith("02-mongo.yaml"):
            yield "  waiting for mongo to be ready..."
            res = await _run_cmd(
                "kubectl", "-n", "neoncore", "wait", "--for=condition=Ready",
                "pod", "-l", "app=mongo", "--timeout=90s", timeout=95,
            )
            yield f"  {res.output.strip()}"
    yield "Deploy complete."


async def teardown() -> AsyncIterator[str]:
    """Delete the neoncore + monitoring namespaces (removes all workloads, incl. PVCs)."""
    for ns in TEARDOWN_NAMESPACES:
        yield f"[delete namespace] {ns}"
        async for line in _stream_cmd("kubectl", "delete", "namespace", ns, "--ignore-not-found"):
            yield f"  {line}"
    yield "Teardown complete."


async def get_pods(namespaces: list[str] = ("neoncore", "monitoring")) -> list[PodInfo]:
    pods: list[PodInfo] = []
    for ns in namespaces:
        res = await _run_cmd("kubectl", "-n", ns, "get", "pods", "-o", "json", timeout=15)
        if not res.ok:
            continue
        try:
            data = json.loads(res.output)
        except json.JSONDecodeError:
            continue
        for item in data.get("items", []):
            meta = item.get("metadata", {})
            status = item.get("status", {})
            containers = status.get("containerStatuses", []) or []
            ready_count = sum(1 for c in containers if c.get("ready"))
            restarts = sum(c.get("restartCount", 0) for c in containers)
            phase = status.get("phase", "Unknown")
            # Surface waiting-reason (CrashLoopBackOff, ImagePullBackOff, etc.) if present.
            for c in containers:
                waiting = c.get("state", {}).get("waiting")
                if waiting and waiting.get("reason"):
                    phase = waiting["reason"]
            start_time = meta.get("creationTimestamp")
            pods.append(PodInfo(
                namespace=ns,
                name=meta.get("name", "?"),
                phase=phase,
                ready=f"{ready_count}/{len(containers)}",
                restarts=restarts,
                age_seconds=_age_seconds(start_time),
                node=status.get("hostIP", ""),
            ))
    return pods


def _age_seconds(creation_ts: str | None) -> float:
    if not creation_ts:
        return 0.0
    import datetime
    try:
        t = datetime.datetime.strptime(creation_ts, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc
        )
        return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds()
    except ValueError:
        return 0.0


def format_age(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h{(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d"


async def find_pod(app_label: str, namespace: str = "neoncore") -> str | None:
    res = await _run_cmd(
        "kubectl", "-n", namespace, "get", "pods", "-l", f"app={app_label}",
        "-o", "jsonpath={.items[0].metadata.name}", timeout=10,
    )
    name = res.output.strip()
    return name if (res.ok and name) else None


async def ue_ping_test(host: str = "8.8.8.8", count: int = 4) -> AsyncIterator[str]:
    pod = await find_pod("ue")
    if not pod:
        yield "No 'ue' pod found -- is the infrastructure deployed?"
        return
    yield f"Running ping from UE pod ({pod}) via uesimtun0 -> {host} ..."
    async for line in _stream_cmd(
        "kubectl", "-n", "neoncore", "exec", pod, "--",
        "ping", "-I", "uesimtun0", "-c", str(count), "-W", "2", host,
    ):
        yield line


async def latest_traces(limit: int = 10) -> AsyncIterator[str]:
    pod = await find_pod("tracer")
    if not pod:
        yield "No 'tracer' pod found -- is the infrastructure deployed?"
        return
    # Sort by the timestamp embedded in the filename, not mtime: gzip touches a
    # rotated file's mtime at compression time, which can make an old capture look
    # newer than one still being actively written.
    res = await _run_cmd(
        "kubectl", "-n", "neoncore", "exec", pod, "--",
        "sh", "-c", "ls -1 /pcaps/*.pcap* 2>/dev/null | sort -r | head -n " + str(limit),
        timeout=15,
    )
    files = [f for f in res.output.strip().splitlines() if f]
    if not files:
        yield "No capture files yet."
        return
    yield f"Most recent {len(files)} capture file(s):"
    for f in files:
        size_res = await _run_cmd(
            "kubectl", "-n", "neoncore", "exec", pod, "--",
            "sh", "-c", f"ls -la {f} 2>/dev/null", timeout=10,
        )
        yield f"  {size_res.output.strip()}"
    yield ""
    yield f"Protocol summary of most recent file ({files[0]}):"
    summary = await _run_cmd(
        "kubectl", "-n", "neoncore", "exec", pod, "--",
        "sh", "-c", f"tcpdump -r {files[0]} -nn 2>/dev/null | tail -n 15",
        timeout=15,
    )
    for line in summary.output.strip().splitlines():
        yield f"  {line}"


# Scenarios a user can pick in the TUI, and the CLI flags each needs (msisdn is always
# required and prompted separately). Keep in sync with phase6/scenarios.py's VALID_SLUGS.
SCENARIOS = ["initial-registration", "registration-reject", "deregistration"]


async def run_scenario(slug: str, msisdn: str, **params) -> AsyncIterator[str]:
    """Runs one phase6 signaling scenario, shelling out to `python3 -m phase6.cli`
    as a subprocess -- same "shell out, don't import" approach as the rest of this
    file, which keeps phase6/ standalone/dependency-free with no cross-phase Python
    package coupling. Must be invoked as a module (-m), not a bare script path:
    phase6/cli.py uses relative imports, which only resolve when Python knows its
    parent package -- running it as a plain script file breaks that."""
    args = ["python3", "-m", "phase6.cli", "--scenario", slug, "--msisdn", msisdn]
    for key, value in params.items():
        if value is None or value == "":
            continue
        args += [f"--{key.replace('_', '-')}", str(value)]
    async for line in _stream_cmd(*args):
        yield line


# Manual, user-controlled packet capture -- separate from the tracer pod's own
# continuous rotating capture (phase4) and from phase6's scenario-scoped captures.
# Same mechanism as phase6/capture.py (a second tcpdump via kubectl exec on the
# already-running tracer pod, PID-file tracked) and the same BPF filter as
# phase4/manifests/capture.sh, just started/stopped on demand instead of on a timer
# or tied to a scenario run.
MANUAL_CAPTURE_DIR = "traces/manual"
CAPTURE_BPF_FILTER = "(sctp) or (udp port 8805) or (udp port 2152) or (tcp port 7777) or icmp"


@dataclass
class CaptureHandle:
    name: str
    ok: bool
    message: str


def _manual_capture_name() -> str:
    import time
    return f"manual-{time.strftime('%Y%m%d-%H%M%S')}"


async def _pcap_size(pod: str, pcap_path: str) -> int:
    res = await _run_cmd(
        "kubectl", "-n", "neoncore", "exec", pod, "--", "sh", "-c",
        f"stat -c%s {pcap_path} 2>/dev/null || echo -1",
        timeout=10,
    )
    try:
        return int(res.output.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return -1


async def start_manual_capture() -> CaptureHandle:
    pod = await find_pod("tracer")
    if not pod:
        return CaptureHandle(name="", ok=False,
                              message="No 'tracer' pod found -- is the infrastructure deployed?")
    name = _manual_capture_name()
    pcap, log, pid = f"/pcaps/{name}.pcap", f"/pcaps/{name}.log", f"/pcaps/{name}.pid"
    cmd = f"nohup tcpdump -i any -n -w {pcap} '{CAPTURE_BPF_FILTER}' >{log} 2>&1 & echo $! > {pid}"
    res = await _run_cmd("kubectl", "-n", "neoncore", "exec", pod, "--", "sh", "-c", cmd, timeout=15)
    if res.ok:
        return CaptureHandle(name=name, ok=True, message=f"Capture started: {name}.pcap")
    return CaptureHandle(name="", ok=False, message=f"Failed to start capture: {res.output.strip()}")


async def stop_manual_capture(name: str) -> AsyncIterator[str]:
    pod = await find_pod("tracer")
    if not pod:
        yield "No 'tracer' pod found -- is the infrastructure deployed?"
        return
    pcap, pid = f"/pcaps/{name}.pcap", f"/pcaps/{name}.pid"

    size1 = await _pcap_size(pod, pcap)
    await asyncio.sleep(1.5)
    size2 = await _pcap_size(pod, pcap)
    yield f"Capture health: {'growing' if size2 > size1 else 'not growing'} ({size1} -> {size2} bytes)"

    await _run_cmd(
        "kubectl", "-n", "neoncore", "exec", pod, "--", "sh", "-c",
        f"kill -INT $(cat {pid}) 2>/dev/null; sleep 1; true",
        timeout=15,
    )

    local_dir = os.path.join(REPO_ROOT, MANUAL_CAPTURE_DIR)
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.join(local_dir, f"{name}.pcap")
    res = await _run_cmd("kubectl", "cp", f"neoncore/{pod}:{pcap}", local_path, timeout=30)
    if res.ok and os.path.exists(local_path):
        size = os.path.getsize(local_path)
        yield f"Capture stopped and collected: {MANUAL_CAPTURE_DIR}/{name}.pcap ({size} bytes)"
    else:
        yield f"Failed to collect capture: {res.output.strip()}"
