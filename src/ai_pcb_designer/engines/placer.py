"""Component placement engine (autoplacer).

Places components on the board using a force-directed algorithm:
1. Start with initial placement (center-out or grid)
2. Apply attraction forces (connected components pull together)
3. Apply repulsion forces (components push apart to avoid overlap)
4. Apply boundary forces (keep components within board outline)
5. Iterate until convergence or max iterations
6. Snap to grid

This is a simplified but effective approach for the boards we target in Phase 1.
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
    grid_snap: float = 0.5           # mm, snap to grid
    padding: float = 2.0             # mm, min spacing between components
    edge_margin: float = 3.0         # mm, margin from board edge
    max_iterations: int = 500
    attraction_strength: float = 0.15
    repulsion_strength: float = 8.0
    boundary_strength: float = 0.5
    damping: float = 0.85
    convergence_threshold: float = 0.01  # mm total movement to stop
    seed: int | None = None


@dataclass
class PlacementStep:
    """Record of one placement iteration for visualization."""
    iteration: int
    positions: dict[str, tuple[float, float]]  # reference -> (x, y)
    total_force: float
    message: str = ""


class PlacementEngine:
    """Force-directed component placement engine.

    Produces animated placement steps for real-time GUI visualization.
    """

    def __init__(self, config: PlacementConfig | None = None) -> None:
        self.config = config or PlacementConfig()
        self._steps: list[PlacementStep] = []
        self._on_step: Callable[[PlacementStep], None] | None = None

    @property
    def steps(self) -> list[PlacementStep]:
        return self._steps

    def set_step_callback(self, callback: Callable[[PlacementStep], None]) -> None:
        """Set callback for real-time step updates (used by GUI)."""
        self._on_step = callback

    def place(self, board: Board) -> list[PlacementStep]:
        """Run the placement algorithm on all components in the board.

        Modifies component positions in-place and returns step history.
        """
        self._steps = []
        cfg = self.config
        rng = random.Random(cfg.seed)

        components = board.components
        if not components:
            return self._steps

        bw = board.settings.width
        bh = board.settings.height
        margin = cfg.edge_margin

        # Build connectivity map: how many nets connect two components
        connectivity = self._build_connectivity(board)

        # Step 1: Initial placement - arrange in a grid inside the board
        self._initial_placement(components, bw, bh, margin, rng)
        self._emit_step(0, components, 0.0, "Initial grid placement")

        # Step 2: Identify fixed components (USB connector on edge, etc.)
        fixed_refs = self._identify_edge_components(components, bw, bh, margin)

        # Step 3: Force-directed iteration
        velocities: dict[str, tuple[float, float]] = {
            c.reference: (0.0, 0.0) for c in components
        }

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
                    weight = connectivity.get(
                        (comp.reference, other.reference),
                        connectivity.get((other.reference, comp.reference), 0),
                    )
                    if weight > 0:
                        dx = other.position.x - comp.position.x
                        dy = other.position.y - comp.position.y
                        dist = max(math.hypot(dx, dy), 0.1)
                        force = cfg.attraction_strength * weight * dist
                        fx += force * dx / dist
                        fy += force * dy / dist

                # Repulsion from all other components
                for other in components:
                    if other.reference == comp.reference:
                        continue
                    dx = comp.position.x - other.position.x
                    dy = comp.position.y - other.position.y
                    dist = max(math.hypot(dx, dy), 0.1)

                    # Check overlap
                    other_rect = other.bounding_rect()
                    overlap = self._overlap_amount(comp_rect, other_rect, cfg.padding)

                    if overlap > 0 or dist < 5.0:
                        force = cfg.repulsion_strength / max(dist * dist, 0.01)
                        force *= (1.0 + overlap * 2.0)
                        fx += force * dx / dist
                        fy += force * dy / dist

                # Boundary forces - push back inside board
                if comp_rect.left < margin:
                    fx += cfg.boundary_strength * (margin - comp_rect.left)
                if comp_rect.right > bw - margin:
                    fx -= cfg.boundary_strength * (comp_rect.right - bw + margin)
                if comp_rect.top < margin:
                    fy += cfg.boundary_strength * (margin - comp_rect.top)
                if comp_rect.bottom > bh - margin:
                    fy -= cfg.boundary_strength * (comp_rect.bottom - bh + margin)

                # Update velocity with damping
                vx, vy = velocities[comp.reference]
                vx = (vx + fx) * cfg.damping
                vy = (vy + fy) * cfg.damping
                velocities[comp.reference] = (vx, vy)

                # Limit velocity
                speed = math.hypot(vx, vy)
                max_speed = 3.0
                if speed > max_speed:
                    vx *= max_speed / speed
                    vy *= max_speed / speed

                # Apply movement
                new_x = comp.position.x + vx
                new_y = comp.position.y + vy

                # Clamp to board bounds
                half_w = comp_rect.width / 2
                half_h = comp_rect.height / 2
                new_x = max(margin + half_w, min(bw - margin - half_w, new_x))
                new_y = max(margin + half_h, min(bh - margin - half_h, new_y))

                movement = math.hypot(new_x - comp.position.x, new_y - comp.position.y)
                total_movement += movement

                comp.position = Point(new_x, new_y)

            # Emit step for visualization
            if iteration % 5 == 0 or iteration < 10:
                self._emit_step(
                    iteration, components, total_movement,
                    f"Force iteration {iteration}, movement={total_movement:.3f}mm",
                )

            # Check convergence
            if total_movement < cfg.convergence_threshold:
                self._emit_step(
                    iteration, components, total_movement,
                    f"Converged at iteration {iteration}",
                )
                break

        # Step 4: Snap to grid
        for comp in components:
            snap = cfg.grid_snap
            comp.position = Point(
                round(comp.position.x / snap) * snap,
                round(comp.position.y / snap) * snap,
            )

        self._emit_step(
            cfg.max_iterations, components, 0.0,
            "Final placement (grid-snapped)",
        )

        return self._steps

    def _initial_placement(
        self,
        components: list[Component],
        board_w: float,
        board_h: float,
        margin: float,
        rng: random.Random,
    ) -> None:
        """Place components in an initial grid layout."""
        usable_w = board_w - 2 * margin
        usable_h = board_h - 2 * margin

        # Sort: largest components first (ICs, modules, connectors)
        sorted_comps = sorted(
            components,
            key=lambda c: c.footprint.bounding_rect().width * c.footprint.bounding_rect().height,
            reverse=True,
        )

        # Calculate grid dimensions
        n = len(sorted_comps)
        cols = max(1, math.ceil(math.sqrt(n * usable_w / usable_h)))
        rows = max(1, math.ceil(n / cols))

        cell_w = usable_w / cols
        cell_h = usable_h / rows

        for i, comp in enumerate(sorted_comps):
            col = i % cols
            row = i // cols
            cx = margin + cell_w * (col + 0.5) + rng.uniform(-cell_w * 0.1, cell_w * 0.1)
            cy = margin + cell_h * (row + 0.5) + rng.uniform(-cell_h * 0.1, cell_h * 0.1)
            comp.position = Point(cx, cy)

    def _identify_edge_components(
        self,
        components: list[Component],
        board_w: float,
        board_h: float,
        margin: float,
    ) -> set[str]:
        """Place connectors on board edges and mark them as fixed."""
        fixed = set()
        for comp in components:
            ref_upper = comp.reference.upper()
            val_upper = comp.value.upper()

            # USB connectors go on the top edge
            if "USB" in val_upper or "USB" in comp.footprint.name.upper():
                comp.position = Point(board_w / 2, margin + 5.0)
                comp.rotation = 0.0
                fixed.add(comp.reference)

            # Mounting holes go to corners
            elif ref_upper.startswith("H") and "MOUNT" in val_upper:
                corners = [
                    Point(margin + 2, margin + 2),
                    Point(board_w - margin - 2, margin + 2),
                    Point(margin + 2, board_h - margin - 2),
                    Point(board_w - margin - 2, board_h - margin - 2),
                ]
                # Find unused corner
                used_corners = set()
                for c in components:
                    if c.reference in fixed and c.reference.startswith("H"):
                        for ci, corner in enumerate(corners):
                            if c.position.distance_to(corner) < 1.0:
                                used_corners.add(ci)
                for ci, corner in enumerate(corners):
                    if ci not in used_corners:
                        comp.position = corner
                        fixed.add(comp.reference)
                        break

        return fixed

    def _build_connectivity(self, board: Board) -> dict[tuple[str, str], int]:
        """Build a map of how many nets connect pairs of components."""
        connectivity: dict[tuple[str, str], int] = {}

        for net in board.nets:
            refs = set()
            for comp_ref, _pad_num in net.pad_refs:
                refs.add(comp_ref)

            ref_list = sorted(refs)
            for i, r1 in enumerate(ref_list):
                for r2 in ref_list[i + 1:]:
                    key = (r1, r2)
                    connectivity[key] = connectivity.get(key, 0) + 1

        return connectivity

    @staticmethod
    def _overlap_amount(rect1: Rect, rect2: Rect, padding: float) -> float:
        """Calculate overlap between two rectangles with padding."""
        r1 = rect1.expanded(padding / 2)
        r2 = rect2.expanded(padding / 2)

        overlap_x = max(0, min(r1.right, r2.right) - max(r1.left, r2.left))
        overlap_y = max(0, min(r1.bottom, r2.bottom) - max(r1.top, r2.top))

        return overlap_x * overlap_y

    def _emit_step(
        self,
        iteration: int,
        components: list[Component],
        total_force: float,
        message: str,
    ) -> None:
        """Record a placement step."""
        positions = {
            c.reference: (c.position.x, c.position.y) for c in components
        }
        step = PlacementStep(
            iteration=iteration,
            positions=positions,
            total_force=total_force,
            message=message,
        )
        self._steps.append(step)
        if self._on_step:
            self._on_step(step)
