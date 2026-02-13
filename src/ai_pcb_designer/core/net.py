"""Net and net class definitions for electrical connectivity."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NetClass:
    """Design rules for a group of nets."""
    name: str
    trace_width: float = 0.25  # mm
    clearance: float = 0.2  # mm
    via_diameter: float = 0.8  # mm
    via_drill: float = 0.4  # mm
    description: str = ""


@dataclass
class Net:
    """An electrical net connecting multiple pads."""
    id: int
    name: str
    net_class: NetClass | None = None
    pad_refs: list[tuple[str, str]] = field(default_factory=list)  # (component_ref, pad_number)

    def add_pad(self, component_ref: str, pad_number: str) -> None:
        self.pad_refs.append((component_ref, pad_number))

    @property
    def is_power(self) -> bool:
        name_upper = self.name.upper()
        return any(kw in name_upper for kw in ("VCC", "VDD", "3V3", "5V", "VBUS", "+"))

    @property
    def is_ground(self) -> bool:
        name_upper = self.name.upper()
        return any(kw in name_upper for kw in ("GND", "VSS", "AGND", "DGND", "PGND"))
