"""Board-level container and design rules."""

from __future__ import annotations

from dataclasses import dataclass, field

from .component import Component, SilkText
from .datatypes import Layer, Point, Rect
from .net import Net, NetClass
from .trace import CopperZone, Trace, TraceSegment, Via


@dataclass
class DesignRules:
    """Manufacturing design rules (DRC constraints)."""
    min_trace_width: float = 0.15  # mm
    min_clearance: float = 0.15  # mm
    min_drill_size: float = 0.3  # mm
    min_annular_ring: float = 0.13  # mm
    min_via_diameter: float = 0.6  # mm
    min_via_drill: float = 0.3  # mm
    solder_mask_expansion: float = 0.05  # mm
    paste_mask_shrink: float = 0.0  # mm
    silk_to_pad_clearance: float = 0.2  # mm
    edge_clearance: float = 0.3  # mm
    board_thickness: float = 1.6  # mm (standard)
    copper_weight: float = 1.0  # oz


@dataclass
class BoardSettings:
    """Board-level configuration."""
    width: float = 50.0  # mm
    height: float = 50.0  # mm
    num_copper_layers: int = 2
    design_rules: DesignRules = field(default_factory=DesignRules)
    grid_size: float = 0.25  # mm placement/routing grid

    @property
    def outline(self) -> Rect:
        return Rect(0, 0, self.width, self.height)

    @property
    def layers(self) -> list[Layer]:
        """Active copper layers based on board configuration."""
        if self.num_copper_layers >= 4:
            return [Layer.F_CU, Layer.IN1_CU, Layer.IN2_CU, Layer.B_CU]
        return [Layer.F_CU, Layer.B_CU]


@dataclass
class Board:
    """Top-level PCB board container.

    This is the main data structure that holds everything about a PCB design:
    components, nets, traces, zones, and design rules.
    """
    name: str = "Untitled Board"
    description: str = ""
    settings: BoardSettings = field(default_factory=BoardSettings)
    components: list[Component] = field(default_factory=list)
    nets: list[Net] = field(default_factory=list)
    traces: list[Trace] = field(default_factory=list)
    zones: list[CopperZone] = field(default_factory=list)
    silk_texts: list[SilkText] = field(default_factory=list)
    net_classes: list[NetClass] = field(default_factory=list)
    _next_net_id: int = field(default=1, repr=False)

    def add_component(self, component: Component) -> None:
        """Add a component to the board."""
        self.components.append(component)

    def remove_component(self, reference: str) -> None:
        """Remove a component by reference designator."""
        self.components = [c for c in self.components if c.reference != reference]

    def get_component(self, reference: str) -> Component | None:
        """Find a component by reference designator."""
        for comp in self.components:
            if comp.reference == reference:
                return comp
        return None

    def add_net(self, name: str, net_class: NetClass | None = None) -> Net:
        """Create and add a new net."""
        net = Net(id=self._next_net_id, name=name, net_class=net_class)
        self._next_net_id += 1
        self.nets.append(net)
        return net

    def get_net(self, name: str) -> Net | None:
        """Find a net by name."""
        for net in self.nets:
            if net.name == name:
                return net
        return None

    def get_net_by_id(self, net_id: int) -> Net | None:
        for net in self.nets:
            if net.id == net_id:
                return net
        return None

    def add_trace(self, trace: Trace) -> None:
        self.traces.append(trace)

    def add_zone(self, zone: CopperZone) -> None:
        self.zones.append(zone)

    def get_all_segments(self) -> list[TraceSegment]:
        """Flat list of all trace segments."""
        segments = []
        for trace in self.traces:
            segments.extend(trace.segments)
        return segments

    def get_all_vias(self) -> list[Via]:
        """Flat list of all vias."""
        vias = []
        for trace in self.traces:
            vias.extend(trace.vias)
        return vias

    def get_unrouted_nets(self) -> list[Net]:
        """Get nets that have no traces yet."""
        routed_net_ids = {t.net_id for t in self.traces}
        return [n for n in self.nets if n.id not in routed_net_ids and len(n.pad_refs) >= 2]

    def board_outline_points(self) -> list[Point]:
        """Get the board outline as corner points."""
        s = self.settings
        return [
            Point(0, 0),
            Point(s.width, 0),
            Point(s.width, s.height),
            Point(0, s.height),
        ]

    def clear_routing(self) -> None:
        """Remove all traces, vias, and copper zones."""
        self.traces.clear()
        self.zones.clear()

    def summary(self) -> dict:
        """Board summary statistics."""
        return {
            "name": self.name,
            "size_mm": f"{self.settings.width} x {self.settings.height}",
            "components": len(self.components),
            "nets": len(self.nets),
            "traces": len(self.traces),
            "segments": sum(len(t.segments) for t in self.traces),
            "vias": sum(len(t.vias) for t in self.traces),
            "unrouted": len(self.get_unrouted_nets()),
        }
