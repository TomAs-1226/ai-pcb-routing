"""Core PCB data model and geometry primitives."""

from .datatypes import (
    Point,
    Rect,
    Layer,
    LayerSide,
    PadShape,
    PadType,
    DrillType,
    ComponentSide,
)
from .board import Board, BoardSettings, DesignRules
from .component import Component, Pad, Footprint
from .net import Net, NetClass
from .trace import Trace, TraceSegment, Via

__all__ = [
    "Point",
    "Rect",
    "Layer",
    "LayerSide",
    "PadShape",
    "PadType",
    "DrillType",
    "ComponentSide",
    "Board",
    "BoardSettings",
    "DesignRules",
    "Component",
    "Pad",
    "Footprint",
    "Net",
    "NetClass",
    "Trace",
    "TraceSegment",
    "Via",
]
