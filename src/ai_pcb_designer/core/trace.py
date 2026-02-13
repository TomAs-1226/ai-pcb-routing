"""Trace, via, and routing primitives."""

from __future__ import annotations

from dataclasses import dataclass, field

from .datatypes import Layer, Point


@dataclass
class TraceSegment:
    """A single routed copper segment."""
    start: Point
    end: Point
    width: float  # mm
    layer: Layer
    net_id: int = 0

    @property
    def length(self) -> float:
        return self.start.distance_to(self.end)


@dataclass
class Via:
    """A plated through-hole connecting layers."""
    position: Point
    diameter: float = 0.8  # mm
    drill: float = 0.4  # mm
    layers: tuple[Layer, Layer] = (Layer.F_CU, Layer.B_CU)
    net_id: int = 0


@dataclass
class Trace:
    """A complete routed connection (net route) made of segments and vias."""
    net_id: int
    segments: list[TraceSegment] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)

    @property
    def total_length(self) -> float:
        return sum(seg.length for seg in self.segments)

    def add_segment(self, start: Point, end: Point, width: float, layer: Layer) -> None:
        self.segments.append(TraceSegment(start, end, width, layer, self.net_id))

    def add_via(self, position: Point, diameter: float = 0.8, drill: float = 0.4) -> None:
        self.vias.append(Via(position, diameter, drill, net_id=self.net_id))


@dataclass
class CopperZone:
    """A copper fill zone (e.g., ground plane)."""
    net_id: int
    layer: Layer
    outline: list[Point] = field(default_factory=list)  # polygon vertices
    clearance: float = 0.3  # mm clearance to other nets
    min_thickness: float = 0.25  # mm
    priority: int = 0
