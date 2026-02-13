"""Component, footprint, and pad definitions."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .datatypes import (
    ComponentSide,
    DrillType,
    Layer,
    PadShape,
    PadType,
    Point,
    Rect,
)


@dataclass
class Pad:
    """A single pad within a footprint."""
    number: str
    pad_type: PadType
    shape: PadShape
    position: Point  # relative to footprint origin
    size_x: float  # mm
    size_y: float  # mm
    drill_size: float = 0.0  # mm, 0 for SMD
    drill_type: DrillType = DrillType.CIRCULAR
    layers: list[Layer] = field(default_factory=list)
    net_id: int | None = None
    net_name: str = ""

    @property
    def is_smd(self) -> bool:
        return self.pad_type == PadType.SMD

    @property
    def is_through_hole(self) -> bool:
        return self.pad_type == PadType.THT

    def absolute_position(self, comp_pos: Point, comp_rotation: float) -> Point:
        """Get pad position in board coordinates given component placement."""
        rotated = self.position.rotate(comp_rotation)
        return rotated + comp_pos

    def bounding_rect(self) -> Rect:
        """Bounding rectangle centered on pad position."""
        return Rect(
            self.position.x - self.size_x / 2,
            self.position.y - self.size_y / 2,
            self.size_x,
            self.size_y,
        )


@dataclass
class SilkLine:
    """A line segment in the silkscreen layer."""
    start: Point
    end: Point
    width: float = 0.12  # mm


@dataclass
class SilkRect:
    """A rectangle outline in the silkscreen layer."""
    rect: Rect
    width: float = 0.12  # mm


@dataclass
class SilkCircle:
    """A circle in the silkscreen layer."""
    center: Point
    radius: float
    width: float = 0.12  # mm


@dataclass
class CourtyardRect:
    """Courtyard area for component spacing."""
    rect: Rect
    layer: Layer = Layer.F_COURTYARD


@dataclass
class Footprint:
    """A component footprint (physical package definition)."""
    name: str
    description: str = ""
    pads: list[Pad] = field(default_factory=list)
    silk_lines: list[SilkLine] = field(default_factory=list)
    silk_rects: list[SilkRect] = field(default_factory=list)
    silk_circles: list[SilkCircle] = field(default_factory=list)
    courtyard: CourtyardRect | None = None

    def bounding_rect(self) -> Rect:
        """Compute bounding rectangle enclosing all pads and silk."""
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")

        for pad in self.pads:
            pr = pad.bounding_rect()
            min_x = min(min_x, pr.left)
            min_y = min(min_y, pr.top)
            max_x = max(max_x, pr.right)
            max_y = max(max_y, pr.bottom)

        for line in self.silk_lines:
            for pt in (line.start, line.end):
                min_x = min(min_x, pt.x)
                min_y = min(min_y, pt.y)
                max_x = max(max_x, pt.x)
                max_y = max(max_y, pt.y)

        if min_x == float("inf"):
            return Rect(0, 0, 0, 0)

        margin = 0.25  # small courtyard margin
        return Rect(min_x - margin, min_y - margin,
                     max_x - min_x + 2 * margin, max_y - min_y + 2 * margin)

    def get_pad(self, number: str) -> Pad | None:
        for pad in self.pads:
            if pad.number == number:
                return pad
        return None


@dataclass
class Component:
    """A placed component on the board."""
    reference: str  # e.g. "U1", "R1", "C3"
    value: str  # e.g. "ESP32-WROOM-32", "10k", "100nF"
    footprint: Footprint
    position: Point = field(default_factory=lambda: Point(0.0, 0.0))
    rotation: float = 0.0  # degrees
    side: ComponentSide = ComponentSide.TOP
    manufacturer: str = ""
    mpn: str = ""  # Manufacturer Part Number
    description: str = ""
    datasheet: str = ""

    def get_pad_absolute_position(self, pad_number: str) -> Point | None:
        pad = self.footprint.get_pad(pad_number)
        if pad is None:
            return None
        return pad.absolute_position(self.position, self.rotation)

    def bounding_rect(self) -> Rect:
        """Bounding rectangle in board coordinates."""
        fp_rect = self.footprint.bounding_rect()
        # Rotate corners and find new bounds
        corners = fp_rect.corners()
        rotated = [c.rotate(self.rotation) + self.position for c in corners]

        min_x = min(p.x for p in rotated)
        min_y = min(p.y for p in rotated)
        max_x = max(p.x for p in rotated)
        max_y = max(p.y for p in rotated)
        return Rect(min_x, min_y, max_x - min_x, max_y - min_y)
