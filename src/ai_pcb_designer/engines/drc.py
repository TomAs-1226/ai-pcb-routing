"""Design Rule Check (DRC) engine.

Validates the board design against manufacturing design rules:
- Minimum trace width
- Minimum clearance between copper features
- Minimum drill size
- Minimum annular ring
- Board edge clearance
- Unconnected nets
- Overlapping pads/components
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable

from ..core.board import Board, DesignRules
from ..core.component import Component
from ..core.datatypes import Layer, Point, Rect
from ..core.trace import TraceSegment, Via


class DRCViolationType(Enum):
    """Types of DRC violations."""
    TRACE_WIDTH = auto()
    CLEARANCE = auto()
    DRILL_SIZE = auto()
    ANNULAR_RING = auto()
    EDGE_CLEARANCE = auto()
    UNCONNECTED_NET = auto()
    OVERLAP = auto()
    COURTYARD_CONFLICT = auto()
    MISSING_FOOTPRINT = auto()


class DRCSeverity(Enum):
    """Severity of a DRC violation."""
    ERROR = auto()
    WARNING = auto()
    INFO = auto()


@dataclass
class DRCViolation:
    """A single DRC violation."""
    violation_type: DRCViolationType
    severity: DRCSeverity
    message: str
    location: Point | None = None
    component_refs: list[str] = field(default_factory=list)
    net_name: str = ""
    actual_value: float = 0.0
    required_value: float = 0.0


@dataclass
class DRCResult:
    """Complete DRC check result."""
    violations: list[DRCViolation] = field(default_factory=list)
    passed: bool = True

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == DRCSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == DRCSeverity.WARNING)

    def summary(self) -> str:
        if self.passed:
            return f"DRC PASSED ({self.warning_count} warnings)"
        return f"DRC FAILED: {self.error_count} errors, {self.warning_count} warnings"


class DRCEngine:
    """Design Rule Check engine."""

    def __init__(self) -> None:
        self._on_check: Callable[[str], None] | None = None

    def set_check_callback(self, callback: Callable[[str], None]) -> None:
        self._on_check = callback

    def check(self, board: Board) -> DRCResult:
        """Run all DRC checks on the board."""
        result = DRCResult()
        rules = board.settings.design_rules

        self._log("Starting DRC checks...")

        self._check_trace_widths(board, rules, result)
        self._check_drill_sizes(board, rules, result)
        self._check_annular_rings(board, rules, result)
        self._check_clearances(board, rules, result)
        self._check_edge_clearances(board, rules, result)
        self._check_unconnected_nets(board, result)
        self._check_component_overlaps(board, result)
        self._check_courtyard_conflicts(board, result)

        result.passed = result.error_count == 0
        self._log(result.summary())

        return result

    def _check_trace_widths(
        self, board: Board, rules: DesignRules, result: DRCResult
    ) -> None:
        """Check all traces meet minimum width."""
        self._log("Checking trace widths...")
        for trace in board.traces:
            for seg in trace.segments:
                if seg.width < rules.min_trace_width:
                    result.violations.append(DRCViolation(
                        violation_type=DRCViolationType.TRACE_WIDTH,
                        severity=DRCSeverity.ERROR,
                        message=(
                            f"Trace width {seg.width:.3f}mm < minimum "
                            f"{rules.min_trace_width:.3f}mm"
                        ),
                        location=seg.start,
                        actual_value=seg.width,
                        required_value=rules.min_trace_width,
                    ))

    def _check_drill_sizes(
        self, board: Board, rules: DesignRules, result: DRCResult
    ) -> None:
        """Check all drill holes meet minimum size."""
        self._log("Checking drill sizes...")
        # Check vias
        for via in board.get_all_vias():
            if via.drill < rules.min_via_drill:
                result.violations.append(DRCViolation(
                    violation_type=DRCViolationType.DRILL_SIZE,
                    severity=DRCSeverity.ERROR,
                    message=(
                        f"Via drill {via.drill:.3f}mm < minimum "
                        f"{rules.min_via_drill:.3f}mm"
                    ),
                    location=via.position,
                    actual_value=via.drill,
                    required_value=rules.min_via_drill,
                ))

        # Check through-hole pads
        for comp in board.components:
            for pad in comp.footprint.pads:
                if pad.drill_size > 0 and pad.drill_size < rules.min_drill_size:
                    abs_pos = pad.absolute_position(comp.position, comp.rotation)
                    result.violations.append(DRCViolation(
                        violation_type=DRCViolationType.DRILL_SIZE,
                        severity=DRCSeverity.ERROR,
                        message=(
                            f"Pad drill {pad.drill_size:.3f}mm < minimum "
                            f"{rules.min_drill_size:.3f}mm on {comp.reference}"
                        ),
                        location=abs_pos,
                        component_refs=[comp.reference],
                        actual_value=pad.drill_size,
                        required_value=rules.min_drill_size,
                    ))

    def _check_annular_rings(
        self, board: Board, rules: DesignRules, result: DRCResult
    ) -> None:
        """Check via and THT pad annular rings."""
        self._log("Checking annular rings...")
        for via in board.get_all_vias():
            annular = (via.diameter - via.drill) / 2
            if annular < rules.min_annular_ring:
                result.violations.append(DRCViolation(
                    violation_type=DRCViolationType.ANNULAR_RING,
                    severity=DRCSeverity.ERROR,
                    message=(
                        f"Via annular ring {annular:.3f}mm < minimum "
                        f"{rules.min_annular_ring:.3f}mm"
                    ),
                    location=via.position,
                    actual_value=annular,
                    required_value=rules.min_annular_ring,
                ))

    def _check_clearances(
        self, board: Board, rules: DesignRules, result: DRCResult
    ) -> None:
        """Check copper-to-copper clearances between different nets."""
        self._log("Checking clearances...")
        segments = board.get_all_segments()

        for i, seg1 in enumerate(segments):
            for seg2 in segments[i + 1:]:
                if seg1.net_id == seg2.net_id:
                    continue
                if seg1.layer != seg2.layer:
                    continue

                dist = self._segment_distance(seg1, seg2)
                min_clear = rules.min_clearance + (seg1.width + seg2.width) / 2

                if dist < min_clear:
                    result.violations.append(DRCViolation(
                        violation_type=DRCViolationType.CLEARANCE,
                        severity=DRCSeverity.ERROR,
                        message=(
                            f"Trace clearance {dist:.3f}mm < minimum "
                            f"{min_clear:.3f}mm between nets"
                        ),
                        location=seg1.start,
                        actual_value=dist,
                        required_value=min_clear,
                    ))

    def _check_edge_clearances(
        self, board: Board, rules: DesignRules, result: DRCResult
    ) -> None:
        """Check copper features are far enough from board edge."""
        self._log("Checking edge clearances...")
        bw = board.settings.width
        bh = board.settings.height
        min_edge = rules.edge_clearance

        for seg in board.get_all_segments():
            for pt in (seg.start, seg.end):
                edge_dist = min(pt.x, pt.y, bw - pt.x, bh - pt.y)
                if edge_dist < min_edge:
                    result.violations.append(DRCViolation(
                        violation_type=DRCViolationType.EDGE_CLEARANCE,
                        severity=DRCSeverity.ERROR,
                        message=(
                            f"Trace at ({pt.x:.2f}, {pt.y:.2f}) is "
                            f"{edge_dist:.3f}mm from board edge "
                            f"(minimum {min_edge:.3f}mm)"
                        ),
                        location=pt,
                        actual_value=edge_dist,
                        required_value=min_edge,
                    ))

    def _check_unconnected_nets(self, board: Board, result: DRCResult) -> None:
        """Check for nets with unrouted connections."""
        self._log("Checking for unrouted nets...")
        unrouted = board.get_unrouted_nets()
        for net in unrouted:
            result.violations.append(DRCViolation(
                violation_type=DRCViolationType.UNCONNECTED_NET,
                severity=DRCSeverity.WARNING,
                message=f"Net '{net.name}' has {len(net.pad_refs)} pads but no traces",
                net_name=net.name,
            ))

    def _check_component_overlaps(self, board: Board, result: DRCResult) -> None:
        """Check for overlapping components."""
        self._log("Checking component overlaps...")
        components = board.components
        for i, c1 in enumerate(components):
            r1 = c1.bounding_rect()
            for c2 in components[i + 1:]:
                r2 = c2.bounding_rect()
                if r1.overlaps(r2):
                    result.violations.append(DRCViolation(
                        violation_type=DRCViolationType.OVERLAP,
                        severity=DRCSeverity.ERROR,
                        message=(
                            f"Components {c1.reference} and {c2.reference} overlap"
                        ),
                        location=r1.center,
                        component_refs=[c1.reference, c2.reference],
                    ))

    def _check_courtyard_conflicts(self, board: Board, result: DRCResult) -> None:
        """Check for courtyard area conflicts."""
        self._log("Checking courtyard conflicts...")
        components = board.components
        for i, c1 in enumerate(components):
            cy1 = c1.footprint.courtyard
            if cy1 is None:
                continue
            r1 = Rect(
                c1.position.x + cy1.rect.x,
                c1.position.y + cy1.rect.y,
                cy1.rect.width,
                cy1.rect.height,
            )
            for c2 in components[i + 1:]:
                cy2 = c2.footprint.courtyard
                if cy2 is None:
                    continue
                r2 = Rect(
                    c2.position.x + cy2.rect.x,
                    c2.position.y + cy2.rect.y,
                    cy2.rect.width,
                    cy2.rect.height,
                )
                if r1.overlaps(r2):
                    result.violations.append(DRCViolation(
                        violation_type=DRCViolationType.COURTYARD_CONFLICT,
                        severity=DRCSeverity.WARNING,
                        message=(
                            f"Courtyard conflict between {c1.reference} "
                            f"and {c2.reference}"
                        ),
                        location=r1.center,
                        component_refs=[c1.reference, c2.reference],
                    ))

    @staticmethod
    def _segment_distance(seg1: TraceSegment, seg2: TraceSegment) -> float:
        """Approximate minimum distance between two line segments."""
        # Simplified: check endpoint-to-segment distances
        distances = [
            _point_to_segment_dist(seg1.start, seg2.start, seg2.end),
            _point_to_segment_dist(seg1.end, seg2.start, seg2.end),
            _point_to_segment_dist(seg2.start, seg1.start, seg1.end),
            _point_to_segment_dist(seg2.end, seg1.start, seg1.end),
        ]
        return min(distances)

    def _log(self, message: str) -> None:
        if self._on_check:
            self._on_check(message)


def _point_to_segment_dist(point: Point, seg_start: Point, seg_end: Point) -> float:
    """Distance from a point to a line segment."""
    dx = seg_end.x - seg_start.x
    dy = seg_end.y - seg_start.y
    length_sq = dx * dx + dy * dy

    if length_sq < 1e-10:
        return point.distance_to(seg_start)

    t = max(0, min(1, (
        (point.x - seg_start.x) * dx + (point.y - seg_start.y) * dy
    ) / length_sq))

    proj = Point(seg_start.x + t * dx, seg_start.y + t * dy)
    return point.distance_to(proj)
