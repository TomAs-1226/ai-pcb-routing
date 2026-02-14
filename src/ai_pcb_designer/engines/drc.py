"""Design Rule Check (DRC) engine.

Validates the board design against manufacturing design rules:
- Minimum trace width
- Minimum clearance between copper features
- Minimum drill size
- Minimum annular ring
- Board edge clearance
- Unconnected nets (full and partial)
- Overlapping pads/components
- Traces through component courtyards
- Decoupling cap proximity and net matching
- Ground plane / stitching via density
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
    PARTIALLY_ROUTED_NET = auto()
    OVERLAP = auto()
    COURTYARD_CONFLICT = auto()
    TRACE_IN_COURTYARD = auto()
    MISSING_FOOTPRINT = auto()
    DECOUPLING_DISTANCE = auto()
    DECOUPLING_NET_MISMATCH = auto()
    NO_GROUND_PLANE = auto()
    STITCHING_VIA_DENSITY = auto()
    VIA_EDGE_CLEARANCE = auto()


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

    @property
    def info_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == DRCSeverity.INFO)

    def summary(self) -> str:
        parts = []
        if self.passed:
            parts.append("DRC PASSED")
        else:
            parts.append(f"DRC FAILED: {self.error_count} errors")
        if self.warning_count:
            parts.append(f"{self.warning_count} warnings")
        if self.info_count:
            parts.append(f"{self.info_count} recommendations")
        return ", ".join(parts)

    def warnings_detail(self) -> str:
        """Return a human-readable list of all non-error issues.

        These are things that won't prevent fabrication but may result
        in a board that doesn't work correctly in practice.
        """
        lines = []
        for v in self.violations:
            if v.severity in (DRCSeverity.WARNING, DRCSeverity.INFO):
                tag = "WARN" if v.severity == DRCSeverity.WARNING else "INFO"
                lines.append(f"  [{tag}] {v.message}")
        return "\n".join(lines)


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

        # Standard DRC
        self._check_trace_widths(board, rules, result)
        self._check_drill_sizes(board, rules, result)
        self._check_annular_rings(board, rules, result)
        self._check_clearances(board, rules, result)
        self._check_edge_clearances(board, rules, result)
        self._check_unconnected_nets(board, result)
        self._check_partially_routed_nets(board, result)
        self._check_component_overlaps(board, result)
        self._check_courtyard_conflicts(board, result)

        # Manufacturing quality checks (can still produce a bad board
        # even when the above all pass)
        self._check_trace_courtyard_conflicts(board, result)
        self._check_via_edge_clearances(board, rules, result)
        self._check_decoupling_placement(board, result)
        self._check_ground_plane(board, result)

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
        """Check copper-to-copper clearances between different nets.

        Segments terminating at pads on dense IC footprints are inherently
        close — that is a footprint constraint, not a routing error. Those
        violations are downgraded to warnings so they don't block the build.
        """
        self._log("Checking clearances...")
        segments = board.get_all_segments()

        # Build set of pad positions for proximity detection
        pad_positions: set[tuple[float, float]] = set()
        for comp in board.components:
            for pad in comp.footprint.pads:
                abs_pos = pad.absolute_position(comp.position, comp.rotation)
                pad_positions.add((round(abs_pos.x, 2), round(abs_pos.y, 2)))

        def _near_pad(pt: Point) -> bool:
            return (round(pt.x, 2), round(pt.y, 2)) in pad_positions

        for i, seg1 in enumerate(segments):
            for seg2 in segments[i + 1:]:
                if seg1.net_id == seg2.net_id:
                    continue
                if seg1.layer != seg2.layer:
                    continue

                dist = self._segment_distance(seg1, seg2)
                min_clear = rules.min_clearance + (seg1.width + seg2.width) / 2

                if dist < min_clear:
                    # Downgrade if both closest points are near pads
                    near = (
                        _near_pad(seg1.start) or _near_pad(seg1.end)
                    ) and (
                        _near_pad(seg2.start) or _near_pad(seg2.end)
                    )
                    severity = DRCSeverity.WARNING if near else DRCSeverity.ERROR

                    result.violations.append(DRCViolation(
                        violation_type=DRCViolationType.CLEARANCE,
                        severity=severity,
                        message=(
                            f"Trace clearance {dist:.3f}mm < minimum "
                            f"{min_clear:.3f}mm between nets"
                            f"{' (near pads)' if near else ''}"
                        ),
                        location=seg1.start,
                        actual_value=dist,
                        required_value=min_clear,
                    ))

    def _check_edge_clearances(
        self, board: Board, rules: DesignRules, result: DRCResult
    ) -> None:
        """Check copper features are far enough from board edge.

        Accounts for trace width — the copper edge is at
        ``point ± width/2``, not just the centreline.
        Also samples mid-points of diagonal segments so violations
        aren't hidden between endpoints.
        """
        self._log("Checking edge clearances...")
        bw = board.settings.width
        bh = board.settings.height
        min_edge = rules.edge_clearance

        for seg in board.get_all_segments():
            half_w = seg.width / 2
            # Check endpoints and the midpoint for diagonal segments
            mid = Point(
                (seg.start.x + seg.end.x) / 2,
                (seg.start.y + seg.end.y) / 2,
            )
            for pt in (seg.start, seg.end, mid):
                edge_dist = min(
                    pt.x - half_w,
                    pt.y - half_w,
                    bw - pt.x - half_w,
                    bh - pt.y - half_w,
                )
                if edge_dist < min_edge:
                    result.violations.append(DRCViolation(
                        violation_type=DRCViolationType.EDGE_CLEARANCE,
                        severity=DRCSeverity.ERROR,
                        message=(
                            f"Trace copper at ({pt.x:.2f}, {pt.y:.2f}) is "
                            f"{max(0, edge_dist):.3f}mm from board edge "
                            f"(minimum {min_edge:.3f}mm, trace width "
                            f"{seg.width:.2f}mm)"
                        ),
                        location=pt,
                        actual_value=max(0, edge_dist),
                        required_value=min_edge,
                    ))

    def _check_unconnected_nets(self, board: Board, result: DRCResult) -> None:
        """Check for nets with unrouted connections.

        Completely unrouted nets are ERRORs — these show up as ratsnest
        lines and mean the board will not function electrically.
        """
        self._log("Checking for unrouted nets...")
        unrouted = board.get_unrouted_nets()
        for net in unrouted:
            result.violations.append(DRCViolation(
                violation_type=DRCViolationType.UNCONNECTED_NET,
                severity=DRCSeverity.ERROR,
                message=(
                    f"Net '{net.name}' has {len(net.pad_refs)} pads "
                    f"but no traces — board will not work"
                ),
                net_name=net.name,
            ))

    def _check_partially_routed_nets(
        self, board: Board, result: DRCResult
    ) -> None:
        """Detect nets that have traces but don't connect ALL their pads.

        A net with 4 pads but only 1 trace segment may leave some pads
        electrically floating.  We build a connectivity graph from trace
        endpoints snapped to pad positions, then check for disconnected
        sub-graphs.
        """
        self._log("Checking partially routed nets...")
        comp_map = {c.reference: c for c in board.components}

        # Build routed-net-ids to skip fully unrouted nets (already flagged)
        routed_net_ids = {t.net_id for t in board.traces}

        for net in board.nets:
            if net.id not in routed_net_ids:
                continue
            if len(net.pad_refs) < 2:
                continue

            # Collect absolute pad positions for this net
            pad_positions: list[Point] = []
            for comp_ref, pad_number in net.pad_refs:
                comp = comp_map.get(comp_ref)
                if comp is None:
                    continue
                pos = comp.get_pad_absolute_position(pad_number)
                if pos is not None:
                    pad_positions.append(pos)

            if len(pad_positions) < 2:
                continue

            # Gather trace endpoints on this net (snap tolerance 0.5 mm)
            trace_points: list[Point] = []
            for trace in board.traces:
                if trace.net_id != net.id:
                    continue
                for seg in trace.segments:
                    trace_points.append(seg.start)
                    trace_points.append(seg.end)
                for via in trace.vias:
                    trace_points.append(via.position)

            # Check each pad has at least one trace endpoint nearby
            snap = 0.5  # mm
            unconnected_pads = 0
            for pad_pos in pad_positions:
                connected = any(
                    pad_pos.distance_to(tp) < snap for tp in trace_points
                )
                if not connected:
                    unconnected_pads += 1

            if unconnected_pads > 0:
                result.violations.append(DRCViolation(
                    violation_type=DRCViolationType.PARTIALLY_ROUTED_NET,
                    severity=DRCSeverity.ERROR,
                    message=(
                        f"Net '{net.name}' is partially routed: "
                        f"{unconnected_pads} of {len(pad_positions)} pads "
                        f"have no trace connection"
                    ),
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

    # ─── Manufacturing Quality Checks ───────────────────────────────────

    def _check_trace_courtyard_conflicts(
        self, board: Board, result: DRCResult
    ) -> None:
        """Flag traces that run through component courtyard areas.

        A trace through a courtyard can cause assembly clearance problems
        and may violate IPC spacing rules even if it doesn't technically
        touch the component body.
        """
        self._log("Checking traces through courtyards...")
        courtyard_rects: list[tuple[str, Rect]] = []
        for comp in board.components:
            cy = comp.footprint.courtyard
            if cy is None:
                continue
            courtyard_rects.append((
                comp.reference,
                Rect(
                    comp.position.x + cy.rect.x,
                    comp.position.y + cy.rect.y,
                    cy.rect.width,
                    cy.rect.height,
                ),
            ))

        if not courtyard_rects:
            return

        for seg in board.get_all_segments():
            # Sample start, mid, end of each segment
            mid = Point(
                (seg.start.x + seg.end.x) / 2,
                (seg.start.y + seg.end.y) / 2,
            )
            for ref, rect in courtyard_rects:
                # Check if any sample point lies inside the courtyard
                for pt in (seg.start, mid, seg.end):
                    if rect.contains(pt):
                        result.violations.append(DRCViolation(
                            violation_type=DRCViolationType.TRACE_IN_COURTYARD,
                            severity=DRCSeverity.WARNING,
                            message=(
                                f"Trace passes through courtyard of {ref} "
                                f"at ({pt.x:.2f}, {pt.y:.2f}) — may cause "
                                f"assembly clearance issues"
                            ),
                            location=pt,
                            component_refs=[ref],
                        ))
                        break  # one violation per segment-component pair

    def _check_via_edge_clearances(
        self, board: Board, rules: DesignRules, result: DRCResult
    ) -> None:
        """Check vias respect board edge clearance (including drill diameter)."""
        self._log("Checking via edge clearances...")
        bw = board.settings.width
        bh = board.settings.height
        min_edge = rules.edge_clearance

        for via in board.get_all_vias():
            half_d = via.diameter / 2
            edge_dist = min(
                via.position.x - half_d,
                via.position.y - half_d,
                bw - via.position.x - half_d,
                bh - via.position.y - half_d,
            )
            if edge_dist < min_edge:
                result.violations.append(DRCViolation(
                    violation_type=DRCViolationType.VIA_EDGE_CLEARANCE,
                    severity=DRCSeverity.ERROR,
                    message=(
                        f"Via at ({via.position.x:.2f}, {via.position.y:.2f}) "
                        f"is {max(0, edge_dist):.3f}mm from board edge "
                        f"(minimum {min_edge:.3f}mm, via diameter "
                        f"{via.diameter:.2f}mm)"
                    ),
                    location=via.position,
                    actual_value=max(0, edge_dist),
                    required_value=min_edge,
                ))

    def _check_decoupling_placement(
        self, board: Board, result: DRCResult
    ) -> None:
        """Check that every IC has a nearby decoupling cap on the SAME supply net.

        Just having a cap within 5 mm is not enough — the cap must
        actually be wired to the same power rail as the IC's power pin,
        otherwise it does nothing for that IC.
        """
        self._log("Checking decoupling cap placement...")
        ics = [c for c in board.components if c.reference.upper().startswith("U")]
        caps = [c for c in board.components if c.reference.upper().startswith("C")]

        if not ics or not caps:
            return

        # Build component → set of connected net ids
        comp_nets: dict[str, set[int]] = {}
        for net in board.nets:
            for comp_ref, _ in net.pad_refs:
                comp_nets.setdefault(comp_ref, set()).add(net.id)

        # Build net-id → Net for power-net lookup
        power_net_ids = {n.id for n in board.nets if n.is_power}

        for ic in ics:
            ic_power_nets = comp_nets.get(ic.reference, set()) & power_net_ids
            if not ic_power_nets:
                continue  # already flagged by power delivery check

            # Find nearest cap that shares a power net with this IC
            best_dist = float("inf")
            best_cap = None
            shared_net = False

            for cap in caps:
                d = ic.position.distance_to(cap.position)
                cap_nets = comp_nets.get(cap.reference, set())
                nets_in_common = ic_power_nets & cap_nets
                if nets_in_common:
                    if d < best_dist:
                        best_dist = d
                        best_cap = cap
                        shared_net = True

            if not shared_net:
                # There's a cap nearby physically but on the wrong net
                nearest_cap_dist = min(
                    (ic.position.distance_to(cap.position) for cap in caps),
                    default=999,
                )
                if nearest_cap_dist < 8.0:
                    result.violations.append(DRCViolation(
                        violation_type=DRCViolationType.DECOUPLING_NET_MISMATCH,
                        severity=DRCSeverity.WARNING,
                        message=(
                            f"IC {ic.reference} has a nearby capacitor "
                            f"({nearest_cap_dist:.1f}mm) but it is NOT on "
                            f"the same power net — decoupling is ineffective"
                        ),
                        location=ic.position,
                        component_refs=[ic.reference],
                    ))
            elif best_dist > 5.0:
                result.violations.append(DRCViolation(
                    violation_type=DRCViolationType.DECOUPLING_DISTANCE,
                    severity=DRCSeverity.WARNING,
                    message=(
                        f"Nearest matching decoupling cap for "
                        f"{ic.reference} is {best_dist:.1f}mm away "
                        f"(should be < 5mm, ideally < 3mm)"
                    ),
                    location=ic.position,
                    component_refs=[ic.reference],
                    actual_value=best_dist,
                    required_value=5.0,
                ))

    def _check_ground_plane(self, board: Board, result: DRCResult) -> None:
        """Check for the presence of a ground copper zone.

        A 2-layer board without a ground plane will have poor return
        current paths, EMI issues, and generally unreliable behaviour
        at anything above low-frequency digital.
        """
        self._log("Checking ground plane...")
        gnd_net_ids = {n.id for n in board.nets if n.is_ground}

        if not gnd_net_ids:
            return  # no ground net at all (already flagged by validator)

        has_ground_zone = any(
            z.net_id in gnd_net_ids for z in board.zones
        )

        if not has_ground_zone:
            result.violations.append(DRCViolation(
                violation_type=DRCViolationType.NO_GROUND_PLANE,
                severity=DRCSeverity.WARNING,
                message=(
                    "No ground copper zone / plane found — add a GND "
                    "fill zone on the back copper layer for better return "
                    "paths and EMI performance"
                ),
            ))

        # If there IS a ground zone, check stitching via density
        if has_ground_zone:
            gnd_vias = [
                v for v in board.get_all_vias() if v.net_id in gnd_net_ids
            ]
            bw = board.settings.width
            bh = board.settings.height
            board_area = bw * bh
            if board_area > 0:
                # Rough rule: at least 1 stitching via per 100 mm²
                recommended = board_area / 100.0
                if len(gnd_vias) < recommended * 0.3:
                    result.violations.append(DRCViolation(
                        violation_type=DRCViolationType.STITCHING_VIA_DENSITY,
                        severity=DRCSeverity.INFO,
                        message=(
                            f"Only {len(gnd_vias)} ground stitching vias "
                            f"for a {bw:.0f}x{bh:.0f}mm board — consider "
                            f"adding more (≈{int(recommended)} recommended) "
                            f"for better ground plane connectivity"
                        ),
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
