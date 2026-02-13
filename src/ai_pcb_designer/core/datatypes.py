"""Fundamental data types and enumerations for PCB design."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Iterator


class Layer(Enum):
    """PCB layer identifiers."""
    F_CU = "F.Cu"
    B_CU = "B.Cu"
    F_MASK = "F.Mask"
    B_MASK = "B.Mask"
    F_SILK = "F.SilkS"
    B_SILK = "B.SilkS"
    F_PASTE = "F.Paste"
    B_PASTE = "B.Paste"
    F_COURTYARD = "F.CrtYd"
    B_COURTYARD = "B.CrtYd"
    F_FAB = "F.Fab"
    B_FAB = "B.Fab"
    EDGE_CUTS = "Edge.Cuts"


class LayerSide(Enum):
    """Which side of the board."""
    TOP = auto()
    BOTTOM = auto()
    BOTH = auto()


class PadShape(Enum):
    """Pad shape types."""
    CIRCLE = "circle"
    RECT = "rect"
    OVAL = "oval"
    ROUNDRECT = "roundrect"


class PadType(Enum):
    """Pad electrical types."""
    SMD = "smd"
    THT = "thru_hole"
    NPTH = "np_thru_hole"
    CONNECT = "connect"


class DrillType(Enum):
    """Drill hole types."""
    CIRCULAR = auto()
    OVAL = auto()


class ComponentSide(Enum):
    """Which side a component is placed on."""
    TOP = auto()
    BOTTOM = auto()


@dataclass(frozen=True, slots=True)
class Point:
    """2D point in millimeters."""
    x: float
    y: float

    def __add__(self, other: Point) -> Point:
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Point) -> Point:
        return Point(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Point:
        return Point(self.x * scalar, self.y * scalar)

    def distance_to(self, other: Point) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def rotate(self, angle_deg: float, center: Point | None = None) -> Point:
        """Rotate this point around a center by angle_deg degrees."""
        cx, cy = (center.x, center.y) if center else (0.0, 0.0)
        rad = math.radians(angle_deg)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        dx, dy = self.x - cx, self.y - cy
        return Point(cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a)

    def to_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)


@dataclass(frozen=True, slots=True)
class Rect:
    """Axis-aligned rectangle in millimeters."""
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)

    @property
    def left(self) -> float:
        return self.x

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def top(self) -> float:
        return self.y

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def contains(self, point: Point) -> bool:
        return self.left <= point.x <= self.right and self.top <= point.y <= self.bottom

    def overlaps(self, other: Rect) -> bool:
        return not (
            self.right < other.left
            or self.left > other.right
            or self.bottom < other.top
            or self.top > other.bottom
        )

    def expanded(self, margin: float) -> Rect:
        return Rect(
            self.x - margin,
            self.y - margin,
            self.width + 2 * margin,
            self.height + 2 * margin,
        )

    def corners(self) -> list[Point]:
        return [
            Point(self.x, self.y),
            Point(self.x + self.width, self.y),
            Point(self.x + self.width, self.y + self.height),
            Point(self.x, self.y + self.height),
        ]
