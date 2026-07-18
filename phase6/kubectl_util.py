"""Standalone async kubectl subprocess helpers for phase6.

Deliberately not imported from phase5/neoncore_cli/k8s.py (and vice versa) -- each
phaseN directory stays self-contained/runnable on its own, matching the rest of this
project's structure. Mirrors k8s.py's _env/_run_cmd/_stream_cmd almost verbatim, plus
a stdin-piping variant for `kubectl apply -f -`.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

REPO_ROOT = os.path.expanduser("~/neoncore-5g")
KUBECONFIG = os.path.expanduser("~/.kube/config")
NAMESPACE = "neoncore"


@dataclass
class CmdResult:
    ok: bool
    output: str


def env() -> dict:
    e = dict(os.environ)
    e["KUBECONFIG"] = KUBECONFIG
    return e


async def run_cmd(*args: str, timeout: float = 30) -> CmdResult:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env(),
            cwd=REPO_ROOT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        text = out.decode(errors="replace")
        return CmdResult(ok=(proc.returncode == 0), output=text)
    except asyncio.TimeoutError:
        return CmdResult(ok=False, output=f"timed out after {timeout}s")
    except FileNotFoundError as e:
        return CmdResult(ok=False, output=str(e))


async def run_cmd_stdin(*args: str, input_text: str, timeout: float = 30) -> CmdResult:
    """Like run_cmd, but pipes input_text to the process's stdin (for `kubectl apply -f -`)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env(),
            cwd=REPO_ROOT,
        )
        out, _ = await asyncio.wait_for(
            proc.communicate(input=input_text.encode()), timeout=timeout
        )
        text = out.decode(errors="replace")
        return CmdResult(ok=(proc.returncode == 0), output=text)
    except asyncio.TimeoutError:
        return CmdResult(ok=False, output=f"timed out after {timeout}s")
    except FileNotFoundError as e:
        return CmdResult(ok=False, output=str(e))


async def stream_cmd(*args: str) -> AsyncIterator[str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env(),
        cwd=REPO_ROOT,
    )
    assert proc.stdout is not None
    async for raw_line in proc.stdout:
        yield raw_line.decode(errors="replace").rstrip("\n")
    await proc.wait()


async def find_pod(app_label: str, namespace: str = NAMESPACE) -> str | None:
    res = await run_cmd(
        "kubectl", "-n", namespace, "get", "pods", "-l", f"app={app_label}",
        "-o", "jsonpath={.items[0].metadata.name}", timeout=10,
    )
    name = res.output.strip()
    return name if (res.ok and name) else None
