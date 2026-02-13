"""Code-to-PCB DSL (Domain Specific Language).

This module provides a clean Python API for describing PCB designs.
The AI generates Python code using this DSL, which is then executed
to produce a Board object. This is similar to how OpenSCAD works
for 3D printing - AI is much better at generating structured code
than manipulating objects directly.

Usage:
    pcb = PCBDesign("My Board", width=70, height=55)

    # Add components with explicit positions
    u1 = pcb.place("U1", "ESP32-WROOM-32", value="ESP32-WROOM-32",
                    pos=(35, 28), description="Main MCU")
    r1 = pcb.place("R1", "R_0603", value="10k", pos=(20, 15))

    # Wire nets
    pcb.net("3V3", [(u1, "2"), (r1, "1")])
    pcb.net("GND", [(u1, "1"), (u1, "39")])

    # Build the board
    board = pcb.build()
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.board import Board, BoardSettings, DesignRules
from ..core.component import Component
from ..core.datatypes import Point
from ..core.net import Net, NetClass
from ..components.footprints import get_footprint, list_footprints


@dataclass
class PlacedComponent:
    """A component placed via the DSL. Stores reference for net wiring."""
    reference: str
    footprint_name: str
    value: str
    position: tuple[float, float]
    rotation: float = 0.0
    manufacturer: str = ""
    mpn: str = ""
    description: str = ""
    side: str = "front"  # "front" or "back"

    def pin(self, number: str) -> tuple[str, str]:
        """Shorthand to reference a pin on this component."""
        return (self.reference, str(number))


@dataclass
class NetDef:
    """A net definition with pad references."""
    name: str
    pads: list[tuple[str, str]]
    net_class: str = "Default"


class PCBDesign:
    """Code-to-PCB design builder.

    Provides a clean API for building PCB designs programmatically.
    Components are placed at explicit positions and nets are wired
    by referencing component pins.
    """

    def __init__(
        self,
        name: str,
        width: float = 50.0,
        height: float = 50.0,
        description: str = "",
        layers: int = 2,
    ) -> None:
        self.name = name
        self.width = width
        self.height = height
        self.description = description
        self.layers = layers
        self._components: list[PlacedComponent] = []
        self._nets: list[NetDef] = []
        self._net_classes: dict[str, dict] = {
            "Default": {"trace_width": 0.25, "clearance": 0.2},
            "Power": {"trace_width": 0.5, "clearance": 0.25},
        }

    def place(
        self,
        reference: str,
        footprint: str,
        value: str = "",
        pos: tuple[float, float] = (0, 0),
        rotation: float = 0.0,
        manufacturer: str = "",
        mpn: str = "",
        description: str = "",
        side: str = "front",
    ) -> PlacedComponent:
        """Place a component on the board at a specific position.

        Args:
            reference: Reference designator (e.g., "U1", "R1", "C1")
            footprint: Footprint name from the library
            value: Component value (e.g., "10k", "100nF", "ESP32-WROOM-32")
            pos: (x, y) position in mm from the board origin (top-left)
            rotation: Rotation in degrees
            manufacturer: Manufacturer name
            mpn: Manufacturer part number
            description: Component description
            side: "front" or "back"

        Returns:
            PlacedComponent that can be used in net() calls
        """
        comp = PlacedComponent(
            reference=reference,
            footprint_name=footprint,
            value=value or footprint,
            position=pos,
            rotation=rotation,
            manufacturer=manufacturer,
            mpn=mpn,
            description=description,
            side=side,
        )
        self._components.append(comp)
        return comp

    def net(
        self,
        name: str,
        pads: list[tuple[str, str] | tuple],
        net_class: str = "Default",
    ) -> None:
        """Define a net connecting component pins.

        Args:
            name: Net name (e.g., "GND", "3V3", "IO0")
            pads: List of (component_ref, pad_number) tuples.
                  Can also use PlacedComponent.pin() shorthand.
            net_class: "Default" or "Power"
        """
        pad_refs = []
        for pad in pads:
            if isinstance(pad, tuple) and len(pad) == 2:
                comp_ref = pad[0] if isinstance(pad[0], str) else pad[0].reference
                pad_refs.append((comp_ref, str(pad[1])))
        self._nets.append(NetDef(name=name, pads=pad_refs, net_class=net_class))

    def power_net(self, name: str, pads: list[tuple[str, str] | tuple]) -> None:
        """Define a power net (wider traces)."""
        self.net(name, pads, net_class="Power")

    def gpio_bus(
        self,
        ic: PlacedComponent | str,
        header: PlacedComponent | str,
        pin_map: dict[str, str],
        net_prefix: str = "",
    ) -> None:
        """Wire a group of GPIO pins from an IC to a header.

        Args:
            ic: The IC component (or reference string)
            header: The header component (or reference string)
            pin_map: Dict mapping IC pin number -> header pin number
            net_prefix: Optional prefix for auto-generated net names
        """
        ic_ref = ic.reference if isinstance(ic, PlacedComponent) else ic
        hdr_ref = header.reference if isinstance(header, PlacedComponent) else header

        for ic_pin, hdr_pin in pin_map.items():
            net_name = f"{net_prefix}{ic_ref}_P{ic_pin}"
            self._nets.append(NetDef(
                name=net_name,
                pads=[(ic_ref, str(ic_pin)), (hdr_ref, str(hdr_pin))],
            ))

    def set_net_class(self, name: str, trace_width: float, clearance: float) -> None:
        """Define or update a net class."""
        self._net_classes[name] = {
            "trace_width": trace_width,
            "clearance": clearance,
        }

    def build(self) -> Board:
        """Build a Board object from the DSL description.

        This converts all the placed components and net definitions
        into a proper Board with components, nets, and pad assignments.
        """
        board = Board(
            name=self.name,
            description=self.description,
            settings=BoardSettings(
                width=self.width,
                height=self.height,
                num_copper_layers=self.layers,
            ),
        )

        # Create net classes
        nc_map: dict[str, NetClass] = {}
        for nc_name, nc_params in self._net_classes.items():
            nc = NetClass(name=nc_name, **nc_params)
            board.net_classes.append(nc)
            nc_map[nc_name] = nc

        # Create components with explicit positions
        for pc in self._components:
            fp = get_footprint(pc.footprint_name)
            if fp is None:
                available = ", ".join(list_footprints())
                raise ValueError(
                    f"Unknown footprint '{pc.footprint_name}'. "
                    f"Available: {available}"
                )
            comp = Component(
                reference=pc.reference,
                value=pc.value,
                footprint=fp,
                position=Point(pc.position[0], pc.position[1]),
                rotation=pc.rotation,
                manufacturer=pc.manufacturer,
                mpn=pc.mpn,
                description=pc.description,
            )
            board.add_component(comp)

        # Create nets and link pads
        for net_def in self._nets:
            nc = nc_map.get(net_def.net_class, nc_map.get("Default"))

            # Check if this net already exists (for multiple gpio_bus calls etc.)
            existing = board.get_net(net_def.name)
            if existing:
                net = existing
            else:
                net = board.add_net(net_def.name, nc)

            for comp_ref, pad_num in net_def.pads:
                net.add_pad(comp_ref, pad_num)

                # Set net on the pad itself
                comp = board.get_component(comp_ref)
                if comp:
                    pad = comp.footprint.get_pad(pad_num)
                    if pad:
                        pad.net_id = net.id
                        pad.net_name = net.name

        return board

    def validate(self) -> list[str]:
        """Validate the design before building.

        Returns list of error/warning messages.
        """
        errors = []

        # Check all footprints exist
        for pc in self._components:
            if get_footprint(pc.footprint_name) is None:
                errors.append(f"Unknown footprint '{pc.footprint_name}' for {pc.reference}")

        # Check for duplicate references
        refs = [pc.reference for pc in self._components]
        dupes = set(r for r in refs if refs.count(r) > 1)
        if dupes:
            errors.append(f"Duplicate references: {', '.join(dupes)}")

        # Check components fit on board
        for pc in self._components:
            x, y = pc.position
            if x < 0 or y < 0 or x > self.width or y > self.height:
                errors.append(
                    f"{pc.reference} at ({x}, {y}) is outside board "
                    f"({self.width}x{self.height}mm)"
                )

        # Check nets reference valid components
        valid_refs = {pc.reference for pc in self._components}
        for net_def in self._nets:
            for comp_ref, pad_num in net_def.pads:
                if comp_ref not in valid_refs:
                    errors.append(
                        f"Net '{net_def.name}' references unknown component '{comp_ref}'"
                    )

        return errors
