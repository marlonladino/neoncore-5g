"""ScenarioConfig + the 3 supported 5G signaling scenario factories.

Two commonly-expected scenarios were deliberately dropped after live research showed
UERANSIM doesn't actually implement the underlying procedure:

- Handover: no PathSwitchRequest/Xn or N2-handover signaling at all (upstream issue
  aligungr/UERANSIM#289 is still open, no PR merged, v3.3.0 -- already in use in
  this project -- is the latest release).
- Tracking Area Update (periodic registration update): confirmed live on this
  cluster (2026-07-18) across two full-length waits (120s and ~12min, matching
  AMF's actual configured T3512) that UERANSIM's UE never sends a periodic
  registration update even though its own internal T3512 timer counts down and
  expires. Matches a still-open upstream bug report describing the identical
  symptom: aligungr/UERANSIM#538 ("no periodic registration with open5gs"), open
  since 2022, unresolved through v3.3.0. There is also no nr-cli command to trigger
  one manually.
"""

from dataclasses import dataclass

DEFAULT_K = "465B5CE8B199B49FAA5F0A2EE238A6BC"
DEFAULT_OPC = "E8ED289DEBA952E4283B54E88E6183CA"

VALID_SLUGS = ("initial-registration", "registration-reject", "deregistration")


@dataclass
class ScenarioConfig:
    slug: str
    msisdn: str  # 10 digits; imsi = f"99970{msisdn}"

    # Subscriber / PCF-derived policy knobs
    k: str = DEFAULT_K
    opc: str = DEFAULT_OPC
    apn: str = "internet"
    sst: int = 1
    sd: str = "000001"
    qos_index: int = 9          # 5QI
    arp_priority: int = 8
    ambr_downlink_bps: int = 1_000_000_000
    ambr_uplink_bps: int = 1_000_000_000
    rau_tau_timer_minutes: int = 12

    # Provisioning lifecycle
    provision: bool = True
    deprovision_after: bool = True

    # Post-registration trigger
    trigger: str | None = None       # None | "deregister"
    trigger_delay_s: float = 3.0

    # Success detection
    expected_pattern: str = "Registration complete"
    expected_pattern_source: str = "amf"   # "amf" | "smf"
    expected_occurrence: int = 1
    timeout_s: float = 60.0

    @property
    def imsi(self) -> str:
        return f"99970{self.msisdn}"  # MCC(999) + MNC(70) + MSISDN(10 digits) = 15 digits


def initial_registration(msisdn: str, **policy) -> ScenarioConfig:
    return ScenarioConfig(slug="initial-registration", msisdn=msisdn, **policy)


def registration_reject(msisdn: str, **policy) -> ScenarioConfig:
    """IMSI is deliberately left unprovisioned -- registration must be rejected."""
    policy.pop("provision", None)
    policy.pop("deprovision_after", None)
    return ScenarioConfig(
        slug="registration-reject", msisdn=msisdn,
        provision=False, deprovision_after=False,
        expected_pattern="Registration reject",
        timeout_s=30.0,
        **policy,
    )


def deregistration(msisdn: str, **policy) -> ScenarioConfig:
    policy.pop("trigger", None)
    policy.pop("expected_pattern", None)
    return ScenarioConfig(
        slug="deregistration", msisdn=msisdn,
        trigger="deregister",
        expected_pattern="Deregistration request",
        **policy,
    )


FACTORIES = {
    "initial-registration": initial_registration,
    "registration-reject": registration_reject,
    "deregistration": deregistration,
}
