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
