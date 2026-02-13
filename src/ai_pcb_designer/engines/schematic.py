"""Schematic generation engine.

Builds a logical schematic (netlist) from a natural language description
or from a template. This is the first step in the PCB design pipeline.
The schematic defines WHAT components exist and HOW they connect,
without caring about physical placement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.board import Board, BoardSettings, DesignRules
from ..core.component import Component
from ..core.datatypes import Point
from ..core.net import Net, NetClass
from ..components.footprints import get_footprint


@dataclass
class SchematicSymbol:
    """A component in the schematic (logical representation)."""
    reference: str
    value: str
    footprint_name: str
    pins: dict[str, str] = field(default_factory=dict)  # pin_number -> net_name
    manufacturer: str = ""
    mpn: str = ""
    description: str = ""


@dataclass
class SchematicSheet:
    """A schematic sheet containing symbols and connections."""
    title: str = "Main Sheet"
    symbols: list[SchematicSymbol] = field(default_factory=list)
    net_names: set[str] = field(default_factory=set)


class SchematicEngine:
    """Generates a board netlist from schematic definitions.

    The AI agent provides a list of components and their connections,
    and this engine builds the Board data structure with components
    and nets properly linked.
    """

    def __init__(self) -> None:
        self.sheets: list[SchematicSheet] = []
        self._ref_counters: dict[str, int] = {}

    def new_sheet(self, title: str = "Main Sheet") -> SchematicSheet:
        sheet = SchematicSheet(title=title)
        self.sheets.append(sheet)
        return sheet

    def auto_reference(self, prefix: str) -> str:
        """Generate next available reference designator (R1, R2, C1, etc.)."""
        count = self._ref_counters.get(prefix, 0) + 1
        self._ref_counters[prefix] = count
        return f"{prefix}{count}"

    def add_component(
        self,
        sheet: SchematicSheet,
        reference: str,
        value: str,
        footprint_name: str,
        pin_nets: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> SchematicSymbol:
        """Add a component to the schematic."""
        sym = SchematicSymbol(
            reference=reference,
            value=value,
            footprint_name=footprint_name,
            pins=pin_nets or {},
            **kwargs,
        )
        sheet.symbols.append(sym)

        for net_name in sym.pins.values():
            if net_name:
                sheet.net_names.add(net_name)

        return sym

    def build_board(
        self,
        name: str = "Untitled",
        description: str = "",
        width: float = 50.0,
        height: float = 50.0,
        design_rules: DesignRules | None = None,
    ) -> Board:
        """Convert all schematic sheets into a Board with components and nets.

        This is the key transformation: schematic -> board netlist.
        """
        board = Board(
            name=name,
            description=description,
            settings=BoardSettings(
                width=width,
                height=height,
                design_rules=design_rules or DesignRules(),
            ),
        )

        # Create net classes
        power_nc = NetClass(name="Power", trace_width=0.5, clearance=0.2)
        default_nc = NetClass(name="Default", trace_width=0.25, clearance=0.2)
        board.net_classes.extend([default_nc, power_nc])

        # Collect all unique net names across sheets
        all_net_names: set[str] = set()
        for sheet in self.sheets:
            all_net_names.update(sheet.net_names)

        # Create nets
        net_map: dict[str, Net] = {}
        for net_name in sorted(all_net_names):
            nc = power_nc if any(
                kw in net_name.upper()
                for kw in ("VCC", "VDD", "3V3", "5V", "GND", "VBUS")
            ) else default_nc
            net = board.add_net(net_name, nc)
            net_map[net_name] = net

        # Create components and link pads to nets
        for sheet in self.sheets:
            for sym in sheet.symbols:
                fp = get_footprint(sym.footprint_name)
                if fp is None:
                    raise ValueError(
                        f"Unknown footprint '{sym.footprint_name}' for {sym.reference}"
                    )

                comp = Component(
                    reference=sym.reference,
                    value=sym.value,
                    footprint=fp,
                    manufacturer=sym.manufacturer,
                    mpn=sym.mpn,
                    description=sym.description,
                )
                board.add_component(comp)

                # Link pins to nets
                for pin_num, net_name in sym.pins.items():
                    if net_name and net_name in net_map:
                        net = net_map[net_name]
                        net.add_pad(sym.reference, pin_num)
                        # Set net on pad
                        pad = fp.get_pad(pin_num)
                        if pad:
                            pad.net_id = net.id
                            pad.net_name = net.name

        return board

    def generate_from_spec(self, spec: dict[str, Any]) -> Board:
        """Generate a board from a structured specification dict.

        This is what the AI agent calls with its design decisions.

        Expected spec format:
        {
            "name": "Board Name",
            "description": "...",
            "width": 50.0,
            "height": 40.0,
            "components": [
                {
                    "reference": "U1",
                    "value": "ESP32-WROOM-32",
                    "footprint": "ESP32-WROOM-32",
                    "pins": {"1": "GND", "2": "3V3", ...},
                    "manufacturer": "...",
                    "mpn": "...",
                },
                ...
            ],
        }
        """
        sheet = self.new_sheet(spec.get("name", "Main"))

        for comp_spec in spec.get("components", []):
            self.add_component(
                sheet,
                reference=comp_spec["reference"],
                value=comp_spec.get("value", ""),
                footprint_name=comp_spec["footprint"],
                pin_nets=comp_spec.get("pins", {}),
                manufacturer=comp_spec.get("manufacturer", ""),
                mpn=comp_spec.get("mpn", ""),
                description=comp_spec.get("description", ""),
            )

        return self.build_board(
            name=spec.get("name", "Untitled"),
            description=spec.get("description", ""),
            width=spec.get("width", 50.0),
            height=spec.get("height", 50.0),
        )
