"""Tandemonium Hardware Mesh & Substrate Contract Bridge.

Enforces execution horizons and capability contracts for low-level device interaction
(WebHID, SDL3, gamepads, serial telemetry) without cloud network exposure.
"""

from __future__ import annotations

import platform
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional
from .ledger import EvidenceLedger


class SubstrateType(str, Enum):
    WORKSTATION = "workstation_intel_core_ultra"
    MOBILE_EDGE = "mobile_edge_termux_arm64"
    EMBEDDED_HID = "embedded_hid_controller"


@dataclass
class HardwareProfile:
    substrate: SubstrateType
    max_execution_horizon_sec: float
    thermal_ceiling_celsius: float
    hardware_acceleration: str


@dataclass
class DeviceEvent:
    device_id: str
    event_type: str  # e.g., "PEDAL_CADENCE", "STEERING_DELTA", "HAPTIC_IMPULSE"
    raw_value: float
    timestamp: float


class TandemoniumSubstrateBridge:
    """Manages low-latency hardware execution contracts for Tandemonium."""

    def __init__(self, ledger: EvidenceLedger):
        self.ledger = ledger
        self.profile = self.detect_host_substrate()

    @staticmethod
    def detect_host_substrate() -> HardwareProfile:
        arch = platform.machine().lower()
        system = platform.system().lower()
        if "arm" in arch or "aarch" in arch:
            return HardwareProfile(
                substrate=SubstrateType.MOBILE_EDGE,
                max_execution_horizon_sec=300.0,
                thermal_ceiling_celsius=42.0,
                hardware_acceleration="NEON SIMD",
            )
        return HardwareProfile(
            substrate=SubstrateType.WORKSTATION,
            max_execution_horizon_sec=1800.0,
            thermal_ceiling_celsius=85.0,
            hardware_acceleration="AVX2 / AVX-VNNI",
        )

    def dispatch_device_event(self, event: DeviceEvent) -> Dict[str, Any]:
        """Dispatches and audits a hardware interaction event."""
        # Enforce range sanitization
        if abs(event.raw_value) > 10000.0:
            raise ValueError(f"Out-of-bounds telemetry spike on device '{event.device_id}'")

        res = {
            "device": event.device_id,
            "event": event.event_type,
            "value": event.raw_value,
            "status": "DISPATCHED_LOCAL_HID",
            "horizon_limit_sec": self.profile.max_execution_horizon_sec,
        }

        self.ledger.append(
            domain="TANDEMONIUM_HID",
            action=f"DEV_{event.event_type}",
            payload_data={"device": event.device_id, "value": event.raw_value},
            metric_data=res,
        )
        return res
