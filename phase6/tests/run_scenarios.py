#!/usr/bin/env python3
"""Dependency-free asyncio integration suite for the 3 signaling scenarios.

Not pytest: these are live-cluster runs against a real Open5GS/UERANSIM stack, not
unit tests -- pytest's fixtures/parametrization/parallel workers add little here,
and parallel workers would actively violate the "never run scenarios concurrently"
requirement (they share mongo/amf/smf/upf/tracer state). Matches the plain-asyncio-
script precedent already set by phase5/smoke_test.py for "needs a live cluster"
testing in this project.

(A 4th scenario, Tracking Area Update, isn't here: UERANSIM never actually sends a
periodic registration update even though its own T3512 timer expires -- confirmed
live and matches a still-open upstream bug, aligungr/UERANSIM#538. See
phase6/scenarios.py's module docstring.)

Usage:
  python3 -m phase6.tests.run_scenarios
  python3 -m phase6.tests.run_scenarios --only initial-registration,registration-reject
"""

import argparse
import asyncio
import sys

from .. import scenarios as sc
from .. import ue_pod
from ..provisioning import deprovision_subscriber
from ..runner import run_scenario

# Reserved MSISDN range for this suite's own runs -- distinct from the real default
# subscriber (...0000000001) and from any manual one-off scenario runs.
SUITE_MSISDNS = {
    "initial-registration": "0000009901",
    "registration-reject": "0000009902",
    "deregistration": "0000009904",
}


def parse_args():
    p = argparse.ArgumentParser(description="Run the phase6 scenario integration suite.")
    p.add_argument(
        "--only", default=None,
        help="comma-separated subset of: " + ",".join(sc.VALID_SLUGS),
    )
    p.add_argument("--quiet", action="store_true", help="only print PASS/FAIL summary lines")
    return p.parse_args()


def build_scenarios(only: list[str] | None) -> list[sc.ScenarioConfig]:
    slugs = only or list(sc.VALID_SLUGS)
    return [sc.FACTORIES[slug](SUITE_MSISDNS[slug]) for slug in slugs]


async def cleanup_leftovers() -> None:
    print("[suite] sweeping leftover scenario-ue pods and test subscribers...")
    await ue_pod.sweep_leftovers()
    for msisdn in SUITE_MSISDNS.values():
        await deprovision_subscriber(f"99970{msisdn}")


async def run_one(cfg: sc.ScenarioConfig, quiet: bool):
    result_out: dict = {}
    async for line in run_scenario(cfg, result_out=result_out):
        if not quiet:
            print(line)
    return result_out.get("result")


async def main_async() -> int:
    args = parse_args()
    only = args.only.split(",") if args.only else None
    if only:
        bad = [s for s in only if s not in sc.VALID_SLUGS]
        if bad:
            print(f"[suite] unknown scenario(s): {bad}", file=sys.stderr)
            return 2

    await cleanup_leftovers()

    configs = build_scenarios(only)
    results = []
    for cfg in configs:
        print(f"\n[suite] --- running {cfg.slug} ---")
        result = await run_one(cfg, args.quiet)
        results.append(result)
        status = "PASS" if (result and result.ok) else "FAIL"
        detail = result.detail if result else "runner produced no result"
        print(f"[suite] {status}  {cfg.slug}  {detail}")

    print("\n[suite] === summary ===")
    failed = []
    for cfg, result in zip(configs, results):
        ok = bool(result and result.ok)
        pcap = result.pcap_local_path if result else None
        size = result.pcap_size_bytes if result else 0
        print(f"  {'PASS' if ok else 'FAIL'}  {cfg.slug:22s}  pcap={pcap} ({size} bytes)")
        if not ok:
            failed.append(cfg.slug)

    if failed:
        print(f"\n[suite] FAILED: {failed}")
        return 1
    print("\n[suite] all scenarios passed")
    return 0


def main() -> None:
    sys.exit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
