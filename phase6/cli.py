"""Argparse entrypoint for running one scenario.

Used both for manual one-off runs (`python3 -m phase6.cli --scenario ... --msisdn ...`)
and as the subprocess phase5/neoncore_cli/k8s.py shells out to from the TUI.
"""

import argparse
import asyncio
import sys

from .scenarios import FACTORIES, VALID_SLUGS


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="phase6.cli", description="Run one 5G signaling scenario.")
    p.add_argument("--scenario", required=True, choices=VALID_SLUGS)
    p.add_argument("--msisdn", required=True, help="10-digit MSISDN (IMSI = 99970<msisdn>)")
    p.add_argument("--apn", default="internet")
    p.add_argument("--sst", type=int, default=1)
    p.add_argument("--sd", default="000001")
    p.add_argument("--qos-index", type=int, default=9, help="5QI")
    p.add_argument("--arp-priority", type=int, default=8)
    p.add_argument("--ambr-downlink-bps", type=int, default=1_000_000_000)
    p.add_argument("--ambr-uplink-bps", type=int, default=1_000_000_000)
    p.add_argument("--rau-tau-timer-minutes", type=int, default=12)
    p.add_argument("--k", default=None, help="override the default test subscriber key")
    p.add_argument("--opc", default=None, help="override the default test subscriber OPc")
    return p


def build_config(args: argparse.Namespace):
    factory = FACTORIES[args.scenario]
    policy = {
        "apn": args.apn,
        "sst": args.sst,
        "sd": args.sd,
        "qos_index": args.qos_index,
        "arp_priority": args.arp_priority,
        "ambr_downlink_bps": args.ambr_downlink_bps,
        "ambr_uplink_bps": args.ambr_uplink_bps,
        "rau_tau_timer_minutes": args.rau_tau_timer_minutes,
    }
    if args.k:
        policy["k"] = args.k
    if args.opc:
        policy["opc"] = args.opc

    return factory(args.msisdn, **policy)


async def _main_async(args: argparse.Namespace) -> int:
    from . import runner

    cfg = build_config(args)
    result_out: dict = {}
    async for line in runner.run_scenario(cfg, result_out=result_out):
        print(line, flush=True)
    result = result_out.get("result")
    return 0 if (result and result.ok) else 1


def main() -> None:
    args = build_parser().parse_args()
    sys.exit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
