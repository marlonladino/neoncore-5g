"""Shared scenario orchestrator.

Step order (all three scenarios share this skeleton): provision-or-skip subscriber ->
start scoped capture -> start tailing the relevant NF's logs -> apply the ephemeral
UE pod -> (optionally) fire a post-registration trigger -> wait for the expected log
pattern -> stop/collect capture -> always clean up (pod + subscriber) in `finally`.

Capture and log-tail are started BEFORE the UE pod is applied -- the earliest NGAP/
NAS packets and the initial Registration Request/Complete lines can otherwise race
past before anything is watching.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from . import capture, kubectl_util as ku, provisioning, ue_pod
from .scenarios import ScenarioConfig

TRACES_DIR = "traces/scenario-runs"


@dataclass
class ScenarioResult:
    ok: bool
    slug: str
    imsi: str
    matched_line: str | None = None
    pcap_local_path: str | None = None
    pcap_size_bytes: int = 0
    capture_healthy: bool = False
    capture_detail: str = ""
    detail: str = ""


async def _tail_until(pod: str, needle: str, occurrence: int, identity_marker: str,
                       timeout: float) -> tuple[bool, str | None]:
    """Follow `pod`'s logs (from now, not history) until `needle` appears alongside
    `identity_marker` for the occurrence-th time, or timeout elapses.

    identity_marker should be the MSISDN, not the full concatenated IMSI: AMF logs a
    registered UE as `imsi-<mcc><mnc><msisdn>` but an unresolvable/unprovisioned one
    as `suci-0-<mcc>-<mnc>-0000-0-0-<msisdn>` -- the MSISDN is the only substring
    guaranteed to appear contiguously in both formats.
    """
    proc = await asyncio.create_subprocess_exec(
        "kubectl", "-n", ku.NAMESPACE, "logs", "-f", "--tail=0", pod,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=ku.env(),
        cwd=ku.REPO_ROOT,
    )
    seen = 0
    matched_line = None
    try:
        async def _read():
            nonlocal seen, matched_line
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip("\n")
                if identity_marker in line and needle in line:
                    seen += 1
                    matched_line = line
                    if seen >= occurrence:
                        return
        await asyncio.wait_for(_read(), timeout=timeout)
        return True, matched_line
    except asyncio.TimeoutError:
        return False, matched_line
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


async def run_scenario(cfg: ScenarioConfig, result_out: dict | None = None) -> AsyncIterator[str]:
    """Runs the scenario, yielding progress lines. If result_out is given, the final
    ScenarioResult is stored at result_out['result'] once the generator is exhausted
    (async generators can't return a value directly)."""
    imsi = cfg.imsi
    slug = cfg.slug
    pod_name = ue_pod.pod_name(slug)
    result = ScenarioResult(ok=False, slug=slug, imsi=imsi)

    yield f"=== scenario: {slug}  imsi={imsi} ==="

    tracer_pod = await ku.find_pod("tracer")
    nf_pod = await ku.find_pod(cfg.expected_pattern_source)
    if not tracer_pod or not nf_pod:
        result.detail = f"missing pod (tracer={tracer_pod}, {cfg.expected_pattern_source}={nf_pod})"
        yield f"[error] {result.detail}"
        return

    cap_name = capture.capture_name(slug, cfg.msisdn)
    tail_task: asyncio.Task | None = None

    try:
        if cfg.provision:
            yield "[provision] provisioning subscriber..."
            r = await provisioning.provision_subscriber(
                imsi, k=cfg.k, opc=cfg.opc, apn=cfg.apn, sst=cfg.sst, sd=cfg.sd,
                qos_index=cfg.qos_index, arp_priority=cfg.arp_priority,
                ambr_downlink_bps=cfg.ambr_downlink_bps, ambr_uplink_bps=cfg.ambr_uplink_bps,
                rau_tau_timer_minutes=cfg.rau_tau_timer_minutes,
            )
            yield f"  {r.output.strip()}"
            if not r.ok:
                result.detail = f"provisioning failed: {r.output}"
                yield f"[error] {result.detail}"
                return
        else:
            yield "[provision] skipped (scenario requires an unprovisioned IMSI)"

        yield f"[capture] starting scoped capture ({cap_name}.pcap)..."
        r = await capture.start(tracer_pod, cap_name)
        if not r.ok:
            yield f"[warn] capture start reported: {r.output.strip()}"

        yield "[watch] tailing logs for expected event..."
        tail_task = asyncio.create_task(
            _tail_until(nf_pod, cfg.expected_pattern, cfg.expected_occurrence, cfg.msisdn, cfg.timeout_s)
        )
        # If we need to fire a post-registration trigger, start that tail now too --
        # not after the pod is applied. Attaching `kubectl logs -f` only sees lines
        # from that moment forward, so starting it late could race past a
        # fast-completing initial registration and time out despite success.
        reg_task: asyncio.Task | None = None
        if cfg.trigger == "deregister":
            reg_task = asyncio.create_task(
                _tail_until(nf_pod, "Registration complete", 1, cfg.msisdn, 30)
            )
        await asyncio.sleep(1.0)  # let both `kubectl logs -f` tails actually attach

        yield f"[ue] applying ephemeral UE pod ({pod_name})..."
        r = await ue_pod.apply(
            ue_pod.build_manifest(
                pod_name, msisdn=cfg.msisdn, k=cfg.k, opc=cfg.opc, apn=cfg.apn,
                sst=cfg.sst, sd=cfg.sd, slug=slug,
            )
        )
        yield f"  {r.output.strip()}"
        if not r.ok:
            result.detail = f"ue pod apply failed: {r.output}"
            yield f"[error] {result.detail}"
            return

        if cfg.trigger == "deregister":
            yield "[trigger] waiting for initial registration before deregistering..."
            registered, _ = await reg_task
            if not registered:
                result.detail = "initial registration never completed; cannot trigger deregister"
                yield f"[error] {result.detail}"
                return
            await asyncio.sleep(cfg.trigger_delay_s)
            yield "[trigger] deregister normal..."
            r = await ue_pod.exec_deregister(pod_name, imsi)
            yield f"  {r.output.strip()}"

        yield f"[watch] waiting up to {cfg.timeout_s:.0f}s for '{cfg.expected_pattern}' " \
              f"(occurrence {cfg.expected_occurrence})..."
        ok, matched_line = await tail_task
        result.ok = ok
        result.matched_line = matched_line
        result.detail = "PASS" if ok else f"timed out waiting for '{cfg.expected_pattern}'"
        yield f"[result] {'PASS' if ok else 'FAIL'}: {matched_line or result.detail}"

    finally:
        if tail_task and not tail_task.done():
            tail_task.cancel()

        yield "[capture] checking capture health..."
        healthy, detail = await capture.is_healthy(tracer_pod, cap_name, settle_s=2.0)
        result.capture_healthy = healthy
        result.capture_detail = detail
        yield f"  capture_healthy={healthy} ({detail})"

        await capture.stop(tracer_pod, cap_name)
        local_path, size = await capture.collect(tracer_pod, cap_name, TRACES_DIR)
        result.pcap_local_path = local_path
        result.pcap_size_bytes = size
        yield f"[capture] collected {local_path} ({size} bytes)"

        yield "[cleanup] deleting ephemeral UE pod..."
        await ue_pod.delete(pod_name)

        if cfg.deprovision_after:
            yield "[cleanup] deprovisioning subscriber..."
            r = await provisioning.deprovision_subscriber(imsi)
            yield f"  {r.output.strip()}"

        if result_out is not None:
            result_out["result"] = result
