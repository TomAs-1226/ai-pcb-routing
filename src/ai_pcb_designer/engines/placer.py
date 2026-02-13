"""Component placement engine (autoplacer) - Phase 2.

Placement strategy:
1. Calculate minimum feasible board size from component courtyards
2. Place fixed-position components first (connectors at edges, mounting holes at corners)
3. Place ICs/modules near center
4. Place dependent components near their parent (decoupling caps near ICs, etc.)
5. Force-directed refinement with strong boundary enforcement
6. Final overlap resolution and grid snap with bounds clamping

All placement is guaranteed to stay within board boundaries.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

from ..core.board import Board
from ..core.component import Component
from ..core.datatypes import Point, Rect


@dataclass
class PlacementConfig:
    """Configuration for the placement engine."""
    grid_snap: float = 0.5
    padding: float = 1.5          # mm, min courtyard-to-courtyard spacing
    edge_margin: float = 2.5      # mm, margin from board edge
    max_iterations: int = 300
    attraction_strength: float = 0.08
    repulsion_strength: float = 5.0
    boundary_strength: float = 2.0   # strong boundary push
    damping: float = 0.7
    convergence_threshold: float = 0.05
    seed: int | None = None


@dataclass
class PlacementStep:
    """Record of one placement iteration for visualization."""
    iteration: int
    positions: dict[str, tuple[float, float]]
    total_force: float
    message: str = ""


def estimate_board_size(board: Board) -> tuple[float, float]:
    """Estimate minimum board size from component courtyards.

    Returns (width_mm, height_mm) with routing overhead.
    """
    total_area = 0.0
    max_comp_w = 0.0
    max_comp_h = 0.0

    for comp in board.components:
        r = comp.footprint.bounding_rect()
        area = r.width * r.height
        total_area += area
        max_comp_w = max(max_comp_w, r.width)
        max_comp_h = max(max_comp_h, r.height)

    # Routing overhead: 2x for 2-layer, 1.6x for 4-layer
    layers = board.settings.num_copper_layers
    routing_mult = 2.0 if layers <= 2 else 1.6
    packing_coeff = 0.6  # comfortable density for auto-placement

    needed_area = total_area * routing_mult / packing_coeff
    # Add mounting hole area
    mounting_holes = sum(1 for c in board.components if c.reference.startswith("H"))
    needed_area += mounting_holes * 50.0

    # Compute dimensions with ~1.3 aspect ratio
    aspect = 1.3
    height = math.sqrt(needed_area / aspect)
    width = aspect * height

    margin = 2.5
    width = max(width + 2 * margin, max_comp_w + 10.0)
    height = max(height + 2 * margin, max_comp_h + 10.0)

    # Round up to 5mm increments
    width = math.ceil(width / 5.0) * 5.0
    height = math.ceil(height / 5.0) * 5.0

    return width, height


class PlacementEngine:
    """Component placement engine with proper physical constraints."""

    def __init__(self, config: PlacementConfig | None = None) -> None:
        self.config = config or PlacementConfig()
        self._steps: list[PlacementStep] = []
        self._on_step: Callable[[PlacementStep], None] | None = None

    @property
    def steps(self) -> list[PlacementStep]:
        return self._steps

    def set_step_callback(self, callback: Callable[[PlacementStep], None]) -> None:
        self._on_step = callback

    def place(self, board: Board) -> list[PlacementStep]:
        """Place all components. Modifies positions in-place."""
        self._steps = []
        cfg = self.config
        rng = random.Random(cfg.seed)

        components = board.components
        if not components:
            return self._steps

        bw = board.settings.width
        bh = board.settings.height
        margin = cfg.edge_margin

        connectivity = self._build_connectivity(board)

        # Phase 1: Categorize components
        fixed_comps: list[Component] = []
        main_ics: list[Component] = []
        dependent: list[Component] = []
        other: list[Component] = []

        for comp in components:
            ref = comp.reference.upper()
            val = comp.value.upper()
            fp = comp.footprint.name.upper()

            if ref.startswith("H") and "MOUNT" in val:
                fixed_comps.append(comp)
            elif "USB" in val or "USB" in fp:
                fixed_comps.append(comp)
            elif ref.startswith("U") or "ESP32" in fp or "WROOM" in fp:
                main_ics.append(comp)
            elif ref.startswith(("C", "R")) and len(ref) <= 3:
                dependent.append(comp)
            else:
                other.append(comp)

        # Phase 2: Place fixed components at board edges
        self._place_fixed_components(fixed_comps, bw, bh, margin)
        self._emit_step(0, components, 0, "Placed connectors and mounting holes")

        # Phase 3: Place main ICs near center
        self._place_main_ics(main_ics, bw, bh, margin, rng)
        self._emit_step(1, components, 0, "Placed main ICs")

        # Phase 4: Place dependent components near their connected ICs
        self._place_dependent(dependent, connectivity, components, bw, bh, margin, rng)
        self._emit_step(2, components, 0, "Placed passive components near ICs")

        # Phase 5: Place remaining components
        self._place_remaining(other, components, bw, bh, margin, rng)
        self._emit_step(3, components, 0, "Placed remaining components")

        # Phase 6: Force-directed refinement
        fixed_refs = {c.reference for c in fixed_comps}
        self._force_directed_refine(components, fixed_refs, connectivity, bw, bh, margin)

        # Phase 7: Final overlap resolution
        self._resolve_overlaps(components, fixed_refs, bw, bh, margin)

        # Phase 8: Grid snap with bounds clamping
        self._snap_and_clamp(components, bw, bh, margin)
        self._emit_step(cfg.max_iterations, components, 0, "Final placement complete")

        return self._steps

    def _place_fixed_components(
        self, comps: list[Component], bw: float, bh: float, margin: float,
    ) -> None:
        """Place connectors at edges and mounting holes at corners."""
        corner_idx = 0
        corners = [
            Point(margin + 2, margin + 2),
            Point(bw - margin - 2, margin + 2),
            Point(margin + 2, bh - margin - 2),
            Point(bw - margin - 2, bh - margin - 2),
        ]

        for comp in comps:
            val = comp.value.upper()
            fp = comp.footprint.name.upper()
            ref = comp.reference.upper()

            if "USB" in val or "USB" in fp:
                # USB connector at top edge center, with footprint touching edge
                fp_rect = comp.footprint.bounding_rect()
                comp.position = Point(bw / 2, margin + fp_rect.height / 2)
                comp.rotation = 0.0
            elif ref.startswith("H") and "MOUNT" in val:
                if corner_idx < len(corners):
                    comp.position = corners[corner_idx]
                    corner_idx += 1

    def _place_main_ics(
        self, comps: list[Component], bw: float, bh: float,
        margin: float, rng: random.Random,
    ) -> None:
        """Place main ICs near the board center."""
        cx, cy = bw / 2, bh / 2

        for i, comp in enumerate(comps):
            # Offset from center for multiple ICs
            offset_x = (i - len(comps) / 2) * 15.0
            x = max(margin + 10, min(bw - margin - 10, cx + offset_x))
            y = max(margin + 10, min(bh - margin - 10, cy))
            comp.position = Point(x, y)

    def _place_dependent(
        self, deps: list[Component], connectivity: dict,
        all_comps: list[Component], bw: float, bh: float,
        margin: float, rng: random.Random,
    ) -> None:
        """Place caps/resistors near the ICs they connect to."""
        placed_positions: dict[str, Point] = {c.reference: c.position for c in all_comps}

        for comp in deps:
            # Find the most-connected already-placed component
            best_target = None
            best_weight = 0
            for other_ref, pos in placed_positions.items():
                if other_ref == comp.reference:
                    continue
                key1 = (comp.reference, other_ref)
                key2 = (other_ref, comp.reference)
                w = connectivity.get(key1, 0) + connectivity.get(key2, 0)
                if w > best_weight:
                    best_weight = w
                    best_target = pos

            if best_target:
                # Place near target with random offset
                angle = rng.uniform(0, 2 * math.pi)
                dist = rng.uniform(3.0, 8.0)
                x = best_target.x + dist * math.cos(angle)
                y = best_target.y + dist * math.sin(angle)
            else:
                x = rng.uniform(margin + 5, bw - margin - 5)
                y = rng.uniform(margin + 5, bh - margin - 5)

            x = self._clamp_x(x, comp, bw, margin)
            y = self._clamp_y(y, comp, bh, margin)
            comp.position = Point(x, y)
            placed_positions[comp.reference] = comp.position

    def _place_remaining(
        self, comps: list[Component], all_comps: list[Component],
        bw: float, bh: float, margin: float, rng: random.Random,
    ) -> None:
        """Place remaining components in available space."""
        for comp in comps:
            x = rng.uniform(margin + 5, bw - margin - 5)
            y = rng.uniform(margin + 5, bh - margin - 5)
            x = self._clamp_x(x, comp, bw, margin)
            y = self._clamp_y(y, comp, bh, margin)
            comp.position = Point(x, y)

    def _force_directed_refine(
        self, components: list[Component], fixed_refs: set[str],
        connectivity: dict, bw: float, bh: float, margin: float,
    ) -> None:
        """Force-directed refinement to optimize placement."""
        cfg = self.config
        velocities = {c.reference: (0.0, 0.0) for c in components}

        for iteration in range(1, cfg.max_iterations + 1):
            total_movement = 0.0

            for comp in components:
                if comp.reference in fixed_refs:
                    continue

                fx, fy = 0.0, 0.0
                comp_rect = comp.bounding_rect()

                # Attraction to connected components
                for other in components:
                    if other.reference == comp.reference:
                        continue
                    key1 = (comp.reference, other.reference)
                    key2 = (other.reference, comp.reference)
                    weight = connectivity.get(key1, 0) + connectivity.get(key2, 0)
                    if weight > 0:
                        dx = other.position.x - comp.position.x
                        dy = other.position.y - comp.position.y
                        dist = max(math.hypot(dx, dy), 0.5)
                        force = cfg.attraction_strength * weight
                        fx += force * dx / dist
                        fy += force * dy / dist

                # Repulsion from all other components
                for other in components:
                    if other.reference == comp.reference:
                        continue
                    dx = comp.position.x - other.position.x
                    dy = comp.position.y - other.position.y
                    dist = max(math.hypot(dx, dy), 0.5)

                    other_rect = other.bounding_rect()
                    overlap = _overlap_amount(comp_rect, other_rect, cfg.padding)

                    if overlap > 0 or dist < 8.0:
                        force = cfg.repulsion_strength / max(dist, 1.0)
                        if overlap > 0:
                            force *= 3.0  # much stronger when overlapping
                        fx += force * dx / dist
                        fy += force * dy / dist

                # Strong boundary forces
                if comp_rect.left < margin:
                    fx += cfg.boundary_strength * (margin - comp_rect.left + 2.0)
                if comp_rect.right > bw - margin:
                    fx -= cfg.boundary_strength * (comp_rect.right - bw + margin + 2.0)
                if comp_rect.top < margin:
                    fy += cfg.boundary_strength * (margin - comp_rect.top + 2.0)
                if comp_rect.bottom > bh - margin:
                    fy -= cfg.boundary_strength * (comp_rect.bottom - bh + margin + 2.0)

                # Update velocity with damping
                vx, vy = velocities[comp.reference]
                vx = (vx + fx) * cfg.damping
                vy = (vy + fy) * cfg.damping

                # Clamp velocity
                speed = math.hypot(vx, vy)
                max_speed = 2.0
                if speed > max_speed:
                    scale = max_speed / speed
                    vx *= scale
                    vy *= scale

                # Store clamped velocity
                velocities[comp.reference] = (vx, vy)

                new_x = self._clamp_x(comp.position.x + vx, comp, bw, margin)
                new_y = self._clamp_y(comp.position.y + vy, comp, bh, margin)

                movement = math.hypot(new_x - comp.position.x, new_y - comp.position.y)
                total_movement += movement
                comp.position = Point(new_x, new_y)

            # Emit every 20th step to avoid flooding GUI
            if iteration % 20 == 0:
                self._emit_step(
                    iteration, components, total_movement,
                    f"Refining placement ({iteration}/{cfg.max_iterations})",
                )

            if total_movement < cfg.convergence_threshold:
                self._emit_step(
                    iteration, components, total_movement,
                    f"Placement converged at iteration {iteration}",
                )
                break

    def _resolve_overlaps(
        self, components: list[Component], fixed_refs: set[str],
        bw: float, bh: float, margin: float,
    ) -> None:
        """Final pass: push apart any remaining overlapping components."""
        for _ in range(50):
            any_overlap = False
            for i, c1 in enumerate(components):
                for c2 in components[i + 1:]:
                    r1 = c1.bounding_rect().expanded(0.5)
                    r2 = c2.bounding_rect().expanded(0.5)
                    if not r1.overlaps(r2):
                        continue
                    any_overlap = True

                    dx = c1.position.x - c2.position.x
                    dy = c1.position.y - c2.position.y
                    dist = max(math.hypot(dx, dy), 0.1)
                    push = 1.0

                    if c1.reference not in fixed_refs:
                        new_x = self._clamp_x(c1.position.x + push * dx / dist, c1, bw, margin)
                        new_y = self._clamp_y(c1.position.y + push * dy / dist, c1, bh, margin)
                        c1.position = Point(new_x, new_y)
                    if c2.reference not in fixed_refs:
                        new_x = self._clamp_x(c2.position.x - push * dx / dist, c2, bw, margin)
                        new_y = self._clamp_y(c2.position.y - push * dy / dist, c2, bh, margin)
                        c2.position = Point(new_x, new_y)

            if not any_overlap:
                break

    def _snap_and_clamp(
        self, components: list[Component], bw: float, bh: float, margin: float,
    ) -> None:
        """Grid snap with guaranteed bounds clamping."""
        snap = self.config.grid_snap
        for comp in components:
            x = round(comp.position.x / snap) * snap
            y = round(comp.position.y / snap) * snap
            x = self._clamp_x(x, comp, bw, margin)
            y = self._clamp_y(y, comp, bh, margin)
            comp.position = Point(x, y)

    def _clamp_x(self, x: float, comp: Component, bw: float, margin: float) -> float:
        r = comp.footprint.bounding_rect()
        half_w = r.width / 2 + 0.5
        return max(margin + half_w, min(bw - margin - half_w, x))

    def _clamp_y(self, y: float, comp: Component, bh: float, margin: float) -> float:
        r = comp.footprint.bounding_rect()
        half_h = r.height / 2 + 0.5
        return max(margin + half_h, min(bh - margin - half_h, y))

    def _build_connectivity(self, board: Board) -> dict[tuple[str, str], int]:
        connectivity: dict[tuple[str, str], int] = {}
        for net in board.nets:
            refs = set()
            for comp_ref, _ in net.pad_refs:
                refs.add(comp_ref)
            ref_list = sorted(refs)
            for i, r1 in enumerate(ref_list):
                for r2 in ref_list[i + 1:]:
                    key = (r1, r2)
                    connectivity[key] = connectivity.get(key, 0) + 1
        return connectivity

    def _emit_step(
        self, iteration: int, components: list[Component],
        total_force: float, message: str,
    ) -> None:
        positions = {c.reference: (c.position.x, c.position.y) for c in components}
        step = PlacementStep(iteration=iteration, positions=positions,
                             total_force=total_force, message=message)
        self._steps.append(step)
        if self._on_step:
            self._on_step(step)


def _overlap_amount(rect1: Rect, rect2: Rect, padding: float) -> float:
    r1 = rect1.expanded(padding / 2)
    r2 = rect2.expanded(padding / 2)
    overlap_x = max(0, min(r1.right, r2.right) - max(r1.left, r2.left))
    overlap_y = max(0, min(r1.bottom, r2.bottom) - max(r1.top, r2.top))
    return overlap_x * overlap_y
