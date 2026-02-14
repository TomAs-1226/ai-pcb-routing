"""AI-driven PCB design validator and quality scorer.

Evaluates board designs across five dimensions:
- Physical feasibility (components fit, no overlaps, valid net references)
- Signal integrity (bypass caps near ICs, trace lengths)
- Power delivery (power/ground nets, IC connections, decoupling)
- Placement quality (connector accessibility, board utilization)
- Routing feasibility (congestion estimation, net complexity)

Produces a composite score (0-100) with detailed per-category breakdowns
and actionable design improvement suggestions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..core.board import Board
from ..core.component import Component
from ..core.datatypes import Point


@dataclass
class DesignIssue:
    """A single design quality issue found during validation."""

    category: str
    severity: str  # "critical", "warning", or "info"
    message: str
    component_refs: list[str] = field(default_factory=list)
    location: Point | None = None
    suggestion: str = ""


@dataclass
class DesignScore:
    """Composite design quality score with per-category breakdown.

    Each sub-score ranges from 0 to 100.  The total is a weighted
    combination of all five categories.
    """

    total: float = 0.0
    feasibility: float = 0.0
    signal_integrity: float = 0.0
    power_delivery: float = 0.0
    placement_quality: float = 0.0
    routing_estimate: float = 0.0
    issues: list[DesignIssue] = field(default_factory=list)

    @property
    def is_feasible(self) -> bool:
        """True when the design contains no critical issues."""
        return all(i.severity != "critical" for i in self.issues)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def summary(self) -> str:
        """Human-readable summary of the design score."""
        lines = [
            f"Design Score: {self.total:.1f}/100",
            f"  Feasibility:       {self.feasibility:.1f}",
            f"  Signal Integrity:  {self.signal_integrity:.1f}",
            f"  Power Delivery:    {self.power_delivery:.1f}",
            f"  Placement Quality: {self.placement_quality:.1f}",
            f"  Routing Estimate:  {self.routing_estimate:.1f}",
            f"  Issues: {self.critical_count} critical, "
            f"{self.warning_count} warnings, "
            f"{sum(1 for i in self.issues if i.severity == 'info')} info",
        ]
        if not self.is_feasible:
            lines.append("  ** Design has critical issues that must be resolved **")
        return "\n".join(lines)


class DesignValidator:
    """Validates a PCB board design and produces a quality score."""

    def validate(self, board: Board) -> DesignScore:
        """Run all validation checks and return a composite score."""
        issues: list[DesignIssue] = []

        feasibility = self._check_physical_feasibility(board, issues)
        signal = self._check_signal_integrity(board, issues)
        power = self._check_power_delivery(board, issues)
        placement = self._check_placement_quality(board, issues)
        routing = self._check_routing_feasibility(board, issues)

        total = (
            feasibility * 0.30
            + signal * 0.20
            + power * 0.20
            + placement * 0.15
            + routing * 0.15
        )

        return DesignScore(
            total=max(0.0, min(100.0, total)),
            feasibility=max(0.0, min(100.0, feasibility)),
            signal_integrity=max(0.0, min(100.0, signal)),
            power_delivery=max(0.0, min(100.0, power)),
            placement_quality=max(0.0, min(100.0, placement)),
            routing_estimate=max(0.0, min(100.0, routing)),
            issues=issues,
        )

    # ------------------------------------------------------------------
    # Physical feasibility
    # ------------------------------------------------------------------

    def _check_physical_feasibility(
        self, board: Board, issues: list[DesignIssue]
    ) -> float:
        """Check that the design is physically realisable.

        * Every component must fit within the board outline.
        * No significant overlaps between non-mounting-hole components.
        * All net pad references must point to valid components / pads.
        """
        score = 100.0
        bw = board.settings.width
        bh = board.settings.height

        # --- Components within board bounds ---
        for comp in board.components:
            r = comp.bounding_rect()
            if r.left < 0 or r.top < 0 or r.right > bw or r.bottom > bh:
                issues.append(DesignIssue(
                    category="feasibility",
                    severity="critical",
                    message=(
                        f"Component {comp.reference} extends outside "
                        f"board boundaries"
                    ),
                    component_refs=[comp.reference],
                    location=comp.position,
                    suggestion=(
                        f"Move {comp.reference} so that it fits entirely "
                        f"within the {bw:.1f} x {bh:.1f} mm board area"
                    ),
                ))
                score -= 15

        # --- Significant overlaps ---
        comps = board.components
        for i, c1 in enumerate(comps):
            # Skip mounting holes for overlap checks
            if c1.reference.upper().startswith("H") and "MOUNT" in c1.value.upper():
                continue
            r1 = c1.bounding_rect()
            for c2 in comps[i + 1:]:
                if c2.reference.upper().startswith("H") and "MOUNT" in c2.value.upper():
                    continue
                r2 = c2.bounding_rect()
                if not r1.overlaps(r2):
                    continue

                # Compute overlap area
                overlap_x = max(
                    0.0, min(r1.right, r2.right) - max(r1.left, r2.left)
                )
                overlap_y = max(
                    0.0, min(r1.bottom, r2.bottom) - max(r1.top, r2.top)
                )
                overlap_area = overlap_x * overlap_y

                smaller_area = min(
                    r1.width * r1.height, r2.width * r2.height
                )
                if smaller_area <= 0:
                    continue

                ratio = overlap_area / smaller_area
                if ratio > 0.30:
                    issues.append(DesignIssue(
                        category="feasibility",
                        severity="critical",
                        message=(
                            f"Significant overlap ({ratio:.0%}) between "
                            f"{c1.reference} and {c2.reference}"
                        ),
                        component_refs=[c1.reference, c2.reference],
                        location=r1.center,
                        suggestion=(
                            f"Increase spacing between {c1.reference} and "
                            f"{c2.reference} to eliminate overlap"
                        ),
                    ))
                    score -= 10

        # --- Valid net pad references ---
        comp_map: dict[str, Component] = {
            c.reference: c for c in board.components
        }
        for net in board.nets:
            for comp_ref, pad_number in net.pad_refs:
                comp = comp_map.get(comp_ref)
                if comp is None:
                    issues.append(DesignIssue(
                        category="feasibility",
                        severity="critical",
                        message=(
                            f"Net '{net.name}' references non-existent "
                            f"component '{comp_ref}'"
                        ),
                        component_refs=[comp_ref],
                        suggestion=(
                            f"Add component '{comp_ref}' to the board or "
                            f"remove the pad reference from net '{net.name}'"
                        ),
                    ))
                    score -= 5
                elif comp.footprint.get_pad(pad_number) is None:
                    issues.append(DesignIssue(
                        category="feasibility",
                        severity="critical",
                        message=(
                            f"Net '{net.name}' references non-existent pad "
                            f"'{pad_number}' on component '{comp_ref}'"
                        ),
                        component_refs=[comp_ref],
                        location=comp.position,
                        suggestion=(
                            f"Verify pad numbering on {comp_ref} footprint "
                            f"'{comp.footprint.name}'"
                        ),
                    ))
                    score -= 5

        return score

    # ------------------------------------------------------------------
    # Signal integrity
    # ------------------------------------------------------------------

    def _check_signal_integrity(
        self, board: Board, issues: list[DesignIssue]
    ) -> float:
        """Evaluate signal integrity aspects of the design.

        * ICs should have bypass capacitors within 5 mm.
        * Bypass caps ideally within 3 mm (informational).
        * Very long signal nets (> 80 mm span) are flagged.
        """
        score = 100.0

        comp_map: dict[str, Component] = {
            c.reference: c for c in board.components
        }

        # Identify ICs (reference starts with U) and capacitors
        ics = [c for c in board.components if c.reference.upper().startswith("U")]
        caps = [c for c in board.components if c.reference.upper().startswith("C")]

        for ic in ics:
            if not caps:
                issues.append(DesignIssue(
                    category="signal_integrity",
                    severity="warning",
                    message=f"No bypass capacitor found near IC {ic.reference}",
                    component_refs=[ic.reference],
                    location=ic.position,
                    suggestion=(
                        f"Add a 100nF bypass capacitor within 5mm of "
                        f"{ic.reference}"
                    ),
                ))
                score -= 10
                continue

            min_dist = min(
                ic.position.distance_to(cap.position) for cap in caps
            )

            if min_dist > 5.0:
                issues.append(DesignIssue(
                    category="signal_integrity",
                    severity="warning",
                    message=(
                        f"Nearest bypass capacitor to IC {ic.reference} is "
                        f"{min_dist:.1f}mm away (should be < 5mm)"
                    ),
                    component_refs=[ic.reference],
                    location=ic.position,
                    suggestion=(
                        f"Move a decoupling capacitor closer to "
                        f"{ic.reference} (within 5mm)"
                    ),
                ))
                score -= 10
            elif min_dist > 3.0:
                issues.append(DesignIssue(
                    category="signal_integrity",
                    severity="info",
                    message=(
                        f"Bypass capacitor for {ic.reference} is "
                        f"{min_dist:.1f}mm away; ideal placement is < 3mm"
                    ),
                    component_refs=[ic.reference],
                    location=ic.position,
                    suggestion=(
                        f"For best decoupling, place capacitor within 3mm "
                        f"of {ic.reference}"
                    ),
                ))
                score -= 3

        # --- Very long signal nets ---
        for net in board.nets:
            if net.is_power or net.is_ground:
                continue
            if len(net.pad_refs) < 2:
                continue

            positions: list[Point] = []
            for comp_ref, pad_number in net.pad_refs:
                comp = comp_map.get(comp_ref)
                if comp is None:
                    continue
                pad_pos = comp.get_pad_absolute_position(pad_number)
                if pad_pos is not None:
                    positions.append(pad_pos)

            if len(positions) < 2:
                continue

            # Compute net span as max distance between any two pads
            max_span = 0.0
            for pi in range(len(positions)):
                for pj in range(pi + 1, len(positions)):
                    d = positions[pi].distance_to(positions[pj])
                    if d > max_span:
                        max_span = d

            if max_span > 80.0:
                issues.append(DesignIssue(
                    category="signal_integrity",
                    severity="warning",
                    message=(
                        f"Signal net '{net.name}' spans {max_span:.1f}mm "
                        f"(long traces degrade signal quality)"
                    ),
                    suggestion=(
                        f"Consider rearranging components on net "
                        f"'{net.name}' to reduce trace length"
                    ),
                ))
                score -= 3

        return score

    # ------------------------------------------------------------------
    # Power delivery
    # ------------------------------------------------------------------

    def _check_power_delivery(
        self, board: Board, issues: list[DesignIssue]
    ) -> float:
        """Evaluate power distribution network quality.

        * Board must have at least one power net.
        * Board must have at least one ground net.
        * ICs must be connected to power and ground.
        * Decoupling capacitors should be present.
        """
        score = 100.0

        power_nets = [n for n in board.nets if n.is_power]
        ground_nets = [n for n in board.nets if n.is_ground]

        if not power_nets:
            issues.append(DesignIssue(
                category="power_delivery",
                severity="critical",
                message="No power net found in the design",
                suggestion=(
                    "Add a power net (e.g. VCC, 3V3, 5V) and connect it "
                    "to all ICs requiring power"
                ),
            ))
            score -= 40

        if not ground_nets:
            issues.append(DesignIssue(
                category="power_delivery",
                severity="critical",
                message="No ground net found in the design",
                suggestion=(
                    "Add a ground net (e.g. GND) and connect it to all "
                    "components requiring a ground reference"
                ),
            ))
            score -= 40

        # Build set of component refs connected to power / ground
        power_connected: set[str] = set()
        ground_connected: set[str] = set()
        for net in power_nets:
            for comp_ref, _ in net.pad_refs:
                power_connected.add(comp_ref)
        for net in ground_nets:
            for comp_ref, _ in net.pad_refs:
                ground_connected.add(comp_ref)

        # ICs should be connected to both power and ground
        ics = [c for c in board.components if c.reference.upper().startswith("U")]
        for ic in ics:
            if power_nets and ic.reference not in power_connected:
                issues.append(DesignIssue(
                    category="power_delivery",
                    severity="critical",
                    message=(
                        f"IC {ic.reference} is not connected to any "
                        f"power net"
                    ),
                    component_refs=[ic.reference],
                    location=ic.position,
                    suggestion=(
                        f"Connect {ic.reference} VCC/VDD pin to the "
                        f"appropriate power net"
                    ),
                ))
                score -= 15

            if ground_nets and ic.reference not in ground_connected:
                issues.append(DesignIssue(
                    category="power_delivery",
                    severity="critical",
                    message=(
                        f"IC {ic.reference} is not connected to any "
                        f"ground net"
                    ),
                    component_refs=[ic.reference],
                    location=ic.position,
                    suggestion=(
                        f"Connect {ic.reference} GND/VSS pin to the "
                        f"ground net"
                    ),
                ))
                score -= 15

        # Decoupling capacitors
        caps = [c for c in board.components if c.reference.upper().startswith("C")]
        if not caps:
            issues.append(DesignIssue(
                category="power_delivery",
                severity="warning",
                message="No decoupling capacitors found in the design",
                suggestion=(
                    "Add 100nF decoupling capacitors near each IC power "
                    "pin for stable power delivery"
                ),
            ))
            score -= 15

        return score

    # ------------------------------------------------------------------
    # Placement quality
    # ------------------------------------------------------------------

    def _check_placement_quality(
        self, board: Board, issues: list[DesignIssue]
    ) -> float:
        """Evaluate component placement quality.

        * USB connectors should be near the board edge (< 15mm).
        * Headers should be accessible (< 20mm from edge).
        * Board utilization should be in a healthy range (5%-60%).
        """
        score = 100.0
        bw = board.settings.width
        bh = board.settings.height

        for comp in board.components:
            val = comp.value.upper()
            fp_name = comp.footprint.name.upper()
            ref = comp.reference.upper()

            # --- USB connectors near edge ---
            if "USB" in val or "USB" in fp_name:
                edge_dist = min(
                    comp.position.x,
                    comp.position.y,
                    bw - comp.position.x,
                    bh - comp.position.y,
                )
                if edge_dist > 15.0:
                    issues.append(DesignIssue(
                        category="placement",
                        severity="warning",
                        message=(
                            f"USB connector {comp.reference} is "
                            f"{edge_dist:.1f}mm from the nearest board "
                            f"edge (should be < 15mm)"
                        ),
                        component_refs=[comp.reference],
                        location=comp.position,
                        suggestion=(
                            f"Move {comp.reference} closer to a board edge "
                            f"for cable accessibility"
                        ),
                    ))
                    score -= 10

            # --- Headers accessibility ---
            if ref.startswith("J") and "USB" not in val and "USB" not in fp_name:
                edge_dist = min(
                    comp.position.x,
                    comp.position.y,
                    bw - comp.position.x,
                    bh - comp.position.y,
                )
                if edge_dist > 20.0:
                    issues.append(DesignIssue(
                        category="placement",
                        severity="info",
                        message=(
                            f"Header {comp.reference} is {edge_dist:.1f}mm "
                            f"from the nearest edge; consider moving it "
                            f"closer for easier access"
                        ),
                        component_refs=[comp.reference],
                        location=comp.position,
                        suggestion=(
                            f"Place {comp.reference} within 20mm of a "
                            f"board edge for better accessibility"
                        ),
                    ))
                    score -= 3

        # --- Board utilization ---
        board_area = bw * bh
        if board_area > 0:
            total_comp_area = 0.0
            for comp in board.components:
                r = comp.bounding_rect()
                total_comp_area += r.width * r.height
            utilization = total_comp_area / board_area

            if utilization < 0.05:
                issues.append(DesignIssue(
                    category="placement",
                    severity="warning",
                    message=(
                        f"Board utilization is very low ({utilization:.1%}); "
                        f"the board may be oversized"
                    ),
                    suggestion=(
                        "Consider reducing the board dimensions to save "
                        "cost and space"
                    ),
                ))
                score -= 5
            elif utilization > 0.60:
                issues.append(DesignIssue(
                    category="placement",
                    severity="warning",
                    message=(
                        f"Board utilization is very high ({utilization:.1%}); "
                        f"routing may be difficult"
                    ),
                    suggestion=(
                        "Consider increasing board size or moving to a "
                        "4-layer stackup for more routing room"
                    ),
                ))
                score -= 5

        return score

    # ------------------------------------------------------------------
    # Routing feasibility
    # ------------------------------------------------------------------

    def _check_routing_feasibility(
        self, board: Board, issues: list[DesignIssue]
    ) -> float:
        """Estimate routing difficulty.

        * Divide the board into a 10mm grid and count net crossings
          per region to detect congestion hot-spots.
        * Flag nets that span most of the board diagonal.
        * Note large designs with many nets.
        """
        score = 100.0
        bw = board.settings.width
        bh = board.settings.height
        comp_map: dict[str, Component] = {
            c.reference: c for c in board.components
        }

        grid_size = 10.0
        cols = max(1, int(math.ceil(bw / grid_size)))
        rows = max(1, int(math.ceil(bh / grid_size)))

        # congestion[row][col] = set of net ids passing through
        congestion: list[list[set[int]]] = [
            [set() for _ in range(cols)] for _ in range(rows)
        ]

        board_diag = math.hypot(bw, bh)

        for net in board.nets:
            if len(net.pad_refs) < 2:
                continue

            positions: list[Point] = []
            for comp_ref, pad_number in net.pad_refs:
                comp = comp_map.get(comp_ref)
                if comp is None:
                    continue
                pad_pos = comp.get_pad_absolute_position(pad_number)
                if pad_pos is not None:
                    positions.append(pad_pos)

            if len(positions) < 2:
                continue

            # Mark grid cells covered by the bounding box of the net
            xs = [p.x for p in positions]
            ys = [p.y for p in positions]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)

            col_start = max(0, int(min_x / grid_size))
            col_end = min(cols - 1, int(max_x / grid_size))
            row_start = max(0, int(min_y / grid_size))
            row_end = min(rows - 1, int(max_y / grid_size))

            for r in range(row_start, row_end + 1):
                for c in range(col_start, col_end + 1):
                    congestion[r][c].add(net.id)

            # Check for nets spanning most of the board diagonal
            net_span = math.hypot(max_x - min_x, max_y - min_y)
            if board_diag > 0 and net_span > 0.80 * board_diag:
                issues.append(DesignIssue(
                    category="routing",
                    severity="info",
                    message=(
                        f"Net '{net.name}' spans {net_span:.1f}mm "
                        f"({net_span / board_diag:.0%} of the board "
                        f"diagonal)"
                    ),
                    suggestion=(
                        f"Rearrange components on net '{net.name}' to "
                        f"reduce routing distance"
                    ),
                ))
                score -= 3

        # Evaluate congestion grid
        max_congestion = 0
        worst_cell: tuple[int, int] | None = None
        for r in range(rows):
            for c in range(cols):
                count = len(congestion[r][c])
                if count > max_congestion:
                    max_congestion = count
                    worst_cell = (r, c)

        if max_congestion > 30:
            cell_x = (worst_cell[1] + 0.5) * grid_size if worst_cell else 0.0
            cell_y = (worst_cell[0] + 0.5) * grid_size if worst_cell else 0.0
            issues.append(DesignIssue(
                category="routing",
                severity="warning",
                message=(
                    f"High routing congestion ({max_congestion} nets) "
                    f"near ({cell_x:.0f}, {cell_y:.0f})mm"
                ),
                location=Point(cell_x, cell_y),
                suggestion=(
                    "Spread components apart in the congested area or "
                    "consider a 4-layer board to provide more routing "
                    "channels"
                ),
            ))
            score -= 15
        elif max_congestion > 20:
            cell_x = (worst_cell[1] + 0.5) * grid_size if worst_cell else 0.0
            cell_y = (worst_cell[0] + 0.5) * grid_size if worst_cell else 0.0
            issues.append(DesignIssue(
                category="routing",
                severity="info",
                message=(
                    f"Moderate routing congestion ({max_congestion} nets) "
                    f"near ({cell_x:.0f}, {cell_y:.0f})mm"
                ),
                location=Point(cell_x, cell_y),
                suggestion=(
                    "Monitor congestion in this area during routing; "
                    "slight component adjustment may help"
                ),
            ))
            score -= 5

        # Large designs with many nets
        net_count = len(board.nets)
        if net_count > 50:
            extra = net_count - 50
            penalty = extra * 0.2
            issues.append(DesignIssue(
                category="routing",
                severity="info",
                message=(
                    f"Design has {net_count} nets; routing complexity "
                    f"increases with net count"
                ),
                suggestion=(
                    "Consider a 4-layer stackup or breaking the design "
                    "into sub-modules for easier routing"
                ),
            ))
            score -= penalty

        return score
