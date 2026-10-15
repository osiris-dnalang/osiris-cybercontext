"""Tandemonium substrate profile and device-event contract (mock).

No device I/O happens in this module. detect_host_substrate() reports what the
standard library can see about the host: the OS, the CPU architecture and, on
Linux, SIMD feature flags read from /proc/cpuinfo. dispatch_device_event()
range-checks a DeviceEvent and records it in the evidence ledger; it does not
talk to WebHID, SDL3 or any driver.

The execution horizon and thermal ceiling in a HardwareProfile are configured
default values. This module neither measures temperature nor enforces the
horizon.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List
from .ledger import EvidenceLedger


class SubstrateType(str, Enum):
    WORKSTATION = "x86_64_host"              # any x86-64 machine
    ARM_HOST = "arm_host"                    # ARM outside Termux (e.g. Apple Silicon, Linux on ARM)
    MOBILE_EDGE = "mobile_edge_termux"       # Termux on Android
    EMBEDDED_HID = "embedded_hid_controller"  # reserved; never auto-detected
    UNKNOWN = "unknown_host"


@dataclass
class HardwareProfile:
    substrate: SubstrateType
    max_execution_horizon_sec: float  # configured default; not enforced here
    thermal_ceiling_celsius: float    # configured default; temperature is not measured
    hardware_acceleration: str        # SIMD flags found in /proc/cpuinfo, or "not detected"
    system: str = ""
    machine: str = ""


@dataclass
class DeviceEvent:
    device_id: str
    event_type: str  # e.g., "PEDAL_CADENCE", "STEERING_DELTA", "HAPTIC_IMPULSE"
    raw_value: float
    timestamp: float


# /proc/cpuinfo flag -> display label, in display order
_SIMD_FLAGS = (
    ("avx2", "AVX2"),
    ("avx_vnni", "AVX-VNNI"),
    ("avx512f", "AVX-512F"),
    ("asimd", "NEON"),
    ("neon", "NEON"),
)


def parse_cpu_features(cpuinfo_text: str) -> List[str]:
    """Return the SIMD features named on 'flags' / 'Features' lines of /proc/cpuinfo."""
    flags = set()
    for line in cpuinfo_text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip().lower() in ("flags", "features"):
            flags.update(value.split())
    labels: List[str] = []
    for flag, label in _SIMD_FLAGS:
        if flag in flags and label not in labels:
            labels.append(label)
    return labels


def _read_cpu_features() -> List[str]:
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            return parse_cpu_features(f.read())
    except OSError:
        return []


class TandemoniumSubstrateBridge:
    """Host profile plus a validate-and-log contract for Tandemonium device events."""

    def __init__(self, ledger: EvidenceLedger):
        self.ledger = ledger
        self.profile = self.detect_host_substrate()

    @staticmethod
    def detect_host_substrate() -> HardwareProfile:
        system = platform.system()
        machine = platform.machine()
        arch = machine.lower()
        features = _read_cpu_features() if system == "Linux" else []
        acceleration = " / ".join(features) if features else "not detected"

        if arch in ("x86_64", "amd64"):
            substrate, horizon, thermal = SubstrateType.WORKSTATION, 1800.0, 85.0
        elif arch.startswith(("arm", "aarch")):
            if "com.termux" in os.environ.get("PREFIX", ""):
                substrate, horizon, thermal = SubstrateType.MOBILE_EDGE, 300.0, 42.0
            else:
                substrate, horizon, thermal = SubstrateType.ARM_HOST, 1800.0, 85.0
        else:
            substrate, horizon, thermal = SubstrateType.UNKNOWN, 300.0, 42.0

        return HardwareProfile(
            substrate=substrate,
            max_execution_horizon_sec=horizon,
            thermal_ceiling_celsius=thermal,
            hardware_acceleration=acceleration,
            system=system,
            machine=machine,
        )

    def dispatch_device_event(self, event: DeviceEvent) -> Dict[str, Any]:
        """Range-checks a device event and records it in the ledger (no device I/O)."""
        # Enforce range sanitization
        if abs(event.raw_value) > 10000.0:
            raise ValueError(f"Out-of-bounds telemetry spike on device '{event.device_id}'")

        res = {
            "device": event.device_id,
            "event": event.event_type,
            "value": event.raw_value,
            "status": "RECORDED_NO_DEVICE_IO",
            "horizon_limit_sec": self.profile.max_execution_horizon_sec,
        }

        self.ledger.append(
            domain="TANDEMONIUM_HID",
            action=f"DEV_{event.event_type}",
            payload_data={"device": event.device_id, "value": event.raw_value},
            metric_data=res,
        )
        return res
