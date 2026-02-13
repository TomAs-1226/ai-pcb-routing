"""PCB trace autorouter using A* pathfinding on a grid.

This is a grid-based router that:
1. Discretizes the board into a routing grid
2. Marks obstacles (pads, existing traces, keepouts)
3. Routes each net using A* with cost heuristics
4. Supports 2-layer routing with vias
5. Uses net ordering (shortest first, power/ground last)
6. Provides step-by-step updates for GUI visualization
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..core.board import Board
from ..core.component import Component
from ..core.datatypes import Layer, Point
from ..core.net import Net
from ..core.trace import Trace, TraceSegment, Via


@dataclass
class RouterConfig:
    """Router configuration parameters."""
    grid_resolution: float = 0.25   # mm per grid cell
    trace_width: float = 0.25      # mm default trace width
    via_diameter: float = 0.8      # mm
    via_drill: float = 0.4         # mm
    clearance: float = 0.2         # mm
    via_cost: float = 50.0         # penalty for adding a via
    direction_change_cost: float = 1.5  # penalty for turning
    max_iterations_per_net: int = 50000
    power_trace_width: float = 0.5  # mm for power/ground


@dataclass
class RouteStep:
    """Record of a routing step for visualization."""
    net_name: str
    net_id: int
    phase: str  # "searching", "found", "failed", "placed"
    path: list[tuple[float, float]] = field(default_factory=list)
    layer: str = "F.Cu"
    vias: list[tuple[float, float]] = field(default_factory=list)
    message: str = ""


# Direction vectors: right, up, left, down, and diagonals
DIRECTIONS_4 = [(1, 0), (0, 1), (-1, 0), (0, -1)]
DIRECTIONS_8 = [
    (1, 0), (0, 1), (-1, 0), (0, -1),
    (1, 1), (1, -1), (-1, 1), (-1, -1),
]


class RoutingGrid:
    """2D grid representation of the board for pathfinding.

    Each cell can be:
        0 = free
        1 = obstacle (pad of different net, board edge)
        2 = trace (existing routed trace)
        net_id (>= 10) = pad belonging to that net (target-friendly)
    """

    def __init__(self, width_mm: float, height_mm: float, resolution: float) -> None:
        self.resolution = resolution
        self.cols = max(1, int(math.ceil(width_mm / resolution)))
        self.rows = max(1, int(math.ceil(height_mm / resolution)))
        # Two layers: front copper and back copper
        self.grid = np.zeros((2, self.rows, self.cols), dtype=np.int32)

    def mm_to_grid(self, x_mm: float, y_mm: float) -> tuple[int, int]:
        """Convert mm coordinates to grid coordinates."""
        gx = int(round(x_mm / self.resolution))
        gy = int(round(y_mm / self.resolution))
        return max(0, min(gx, self.cols - 1)), max(0, min(gy, self.rows - 1))

    def grid_to_mm(self, gx: int, gy: int) -> tuple[float, float]:
        """Convert grid coordinates back to mm."""
        return gx * self.resolution, gy * self.resolution

    def mark_obstacle(self, layer_idx: int, gx: int, gy: int, radius_cells: int = 1) -> None:
        """Mark cells as obstacles."""
        for dx in range(-radius_cells, radius_cells + 1):
            for dy in range(-radius_cells, radius_cells + 1):
                nx, ny = gx + dx, gy + dy
                if 0 <= nx < self.cols and 0 <= ny < self.rows:
                    if self.grid[layer_idx, ny, nx] == 0:
                        self.grid[layer_idx, ny, nx] = 1

    def mark_pad(self, layer_idx: int, gx: int, gy: int, net_id: int,
                 radius_cells: int = 1) -> None:
        """Mark cells as belonging to a net's pad."""
        for dx in range(-radius_cells, radius_cells + 1):
            for dy in range(-radius_cells, radius_cells + 1):
                nx, ny = gx + dx, gy + dy
                if 0 <= nx < self.cols and 0 <= ny < self.rows:
                    self.grid[layer_idx, ny, nx] = net_id + 10  # offset to avoid collision

    def mark_trace(self, layer_idx: int, gx: int, gy: int, clearance_cells: int = 1) -> None:
        """Mark cells as containing a trace + clearance."""
        for dx in range(-clearance_cells, clearance_cells + 1):
            for dy in range(-clearance_cells, clearance_cells + 1):
                nx, ny = gx + dx, gy + dy
                if 0 <= nx < self.cols and 0 <= ny < self.rows:
                    if self.grid[layer_idx, ny, nx] == 0:
                        self.grid[layer_idx, ny, nx] = 2

    def is_free(self, layer_idx: int, gx: int, gy: int, net_id: int) -> bool:
        """Check if a cell is routable for a given net."""
        if not (0 <= gx < self.cols and 0 <= gy < self.rows):
            return False
        val = self.grid[layer_idx, gy, gx]
        return val == 0 or val == net_id + 10  # free or same-net pad


class AutoRouter:
    """Grid-based A* autorouter with 2-layer support."""

    def __init__(self, config: RouterConfig | None = None) -> None:
        self.config = config or RouterConfig()
        self._steps: list[RouteStep] = []
        self._on_step: Callable[[RouteStep], None] | None = None

    @property
    def steps(self) -> list[RouteStep]:
        return self._steps

    def set_step_callback(self, callback: Callable[[RouteStep], None]) -> None:
        self._on_step = callback

    def route(self, board: Board) -> tuple[bool, list[RouteStep]]:
        """Route all nets on the board.

        Returns (all_routed, steps).
        """
        self._steps = []
        cfg = self.config

        # Build routing grid
        grid = RoutingGrid(
            board.settings.width,
            board.settings.height,
            cfg.grid_resolution,
        )

        # Mark board edge as obstacle
        self._mark_board_boundary(grid)

        # Mark all pads on the grid
        self._mark_all_pads(grid, board)

        # Order nets: short nets first, power/ground last (they get copper pours)
        ordered_nets = self._order_nets(board)

        all_routed = True
        for net in ordered_nets:
            if len(net.pad_refs) < 2:
                continue

            # Get pad positions for this net
            pad_positions = self._get_pad_positions(board, net)
            if len(pad_positions) < 2:
                continue

            # Determine trace width
            trace_width = cfg.power_trace_width if (
                net.is_power or net.is_ground
            ) else cfg.trace_width

            self._emit_step(net.name, net.id, "searching", [], message=f"Routing net: {net.name}")

            # Route using minimum spanning tree approach: connect closest pads first
            trace = Trace(net_id=net.id)
            connected = {0}  # indices of connected pads
            unconnected = set(range(1, len(pad_positions)))

            while unconnected:
                best_path = None
                best_cost = float("inf")
                best_from = -1
                best_to = -1

                for ci in connected:
                    for ui in unconnected:
                        start = pad_positions[ci]
                        end = pad_positions[ui]
                        path, layer_switches = self._astar(grid, start, end, net.id)
                        if path is not None:
                            cost = len(path) + len(layer_switches) * cfg.via_cost
                            if cost < best_cost:
                                best_cost = cost
                                best_path = path
                                best_from = ci
                                best_to = ui

                if best_path is None:
                    self._emit_step(
                        net.name, net.id, "failed", [],
                        message=f"Failed to route net: {net.name}",
                    )
                    all_routed = False
                    break

                # Convert grid path to trace segments
                self._path_to_trace(grid, best_path, trace, trace_width, net.id)

                # Mark routed path on grid
                clearance_cells = max(1, int(
                    math.ceil((trace_width / 2 + cfg.clearance) / cfg.grid_resolution)
                ))
                for gx, gy, layer_idx in best_path:
                    grid.mark_trace(layer_idx, gx, gy, clearance_cells)

                connected.add(best_to)
                unconnected.discard(best_to)

                # Emit step with path visualization
                path_mm = [
                    grid.grid_to_mm(gx, gy) for gx, gy, _ in best_path
                ]
                self._emit_step(
                    net.name, net.id, "found", path_mm,
                    message=f"Routed {net.name}: {pad_positions[best_from]} -> {pad_positions[best_to]}",
                )

            if trace.segments:
                board.add_trace(trace)
                self._emit_step(
                    net.name, net.id, "placed", [],
                    message=f"Completed net: {net.name} ({len(trace.segments)} segments)",
                )

        return all_routed, self._steps

    def _astar(
        self,
        grid: RoutingGrid,
        start: tuple[int, int, int],
        end: tuple[int, int, int],
        net_id: int,
    ) -> tuple[list[tuple[int, int, int]] | None, list[tuple[int, int]]]:
        """A* pathfinding on the routing grid.

        State: (gx, gy, layer_idx)
        Returns: (path, layer_switch_positions) or (None, [])
        """
        cfg = self.config

        sx, sy, sl = start
        ex, ey, el = end

        # Priority queue: (f_cost, g_cost, state, parent_state)
        open_set: list[tuple[float, float, tuple[int, int, int]]] = []
        heapq.heappush(open_set, (0.0, 0.0, (sx, sy, sl)))

        came_from: dict[tuple[int, int, int], tuple[int, int, int] | None] = {
            (sx, sy, sl): None
        }
        g_score: dict[tuple[int, int, int], float] = {(sx, sy, sl): 0.0}

        iterations = 0
        max_iter = cfg.max_iterations_per_net

        while open_set and iterations < max_iter:
            iterations += 1
            f, g, current = heapq.heappop(open_set)

            cx, cy, cl = current

            # Check if we reached the target
            if abs(cx - ex) <= 1 and abs(cy - ey) <= 1 and (cl == el or el == -1):
                # Reconstruct path
                path = []
                node = current
                while node is not None:
                    path.append(node)
                    node = came_from[node]
                path.reverse()

                # Find layer switches
                switches = []
                for i in range(1, len(path)):
                    if path[i][2] != path[i - 1][2]:
                        switches.append((path[i][0], path[i][1]))

                return path, switches

            # Explore neighbors on same layer
            for dx, dy in DIRECTIONS_8:
                nx, ny = cx + dx, cy + dy
                if not grid.is_free(cl, nx, ny, net_id):
                    continue

                # Diagonal cost
                move_cost = 1.414 if (dx != 0 and dy != 0) else 1.0

                # Direction change penalty
                parent = came_from.get(current)
                if parent is not None:
                    prev_dx = cx - parent[0]
                    prev_dy = cy - parent[1]
                    if (prev_dx, prev_dy) != (dx, dy):
                        move_cost += cfg.direction_change_cost * 0.1

                new_g = g + move_cost
                neighbor = (nx, ny, cl)

                if neighbor not in g_score or new_g < g_score[neighbor]:
                    g_score[neighbor] = new_g
                    h = math.hypot(nx - ex, ny - ey)
                    heapq.heappush(open_set, (new_g + h, new_g, neighbor))
                    came_from[neighbor] = current

            # Explore via to other layer
            other_layer = 1 - cl
            if grid.is_free(other_layer, cx, cy, net_id):
                new_g = g + cfg.via_cost
                via_neighbor = (cx, cy, other_layer)
                if via_neighbor not in g_score or new_g < g_score[via_neighbor]:
                    g_score[via_neighbor] = new_g
                    h = math.hypot(cx - ex, cy - ey)
                    heapq.heappush(open_set, (new_g + h, new_g, via_neighbor))
                    came_from[via_neighbor] = current

        return None, []

    def _path_to_trace(
        self,
        grid: RoutingGrid,
        path: list[tuple[int, int, int]],
        trace: Trace,
        width: float,
        net_id: int,
    ) -> None:
        """Convert a grid path into TraceSegments and Vias."""
        if len(path) < 2:
            return

        cfg = self.config
        current_start = path[0]
        current_layer = path[0][2]

        for i in range(1, len(path)):
            gx, gy, layer_idx = path[i]

            if layer_idx != current_layer:
                # Layer change - emit segment up to here, then add via
                prev = path[i - 1]
                sx, sy = grid.grid_to_mm(current_start[0], current_start[1])
                ex, ey = grid.grid_to_mm(prev[0], prev[1])

                if abs(sx - ex) > 0.01 or abs(sy - ey) > 0.01:
                    layer = Layer.F_CU if current_layer == 0 else Layer.B_CU
                    trace.add_segment(Point(sx, sy), Point(ex, ey), width, layer)

                # Add via
                vx, vy = grid.grid_to_mm(prev[0], prev[1])
                trace.add_via(Point(vx, vy), cfg.via_diameter, cfg.via_drill)

                current_start = path[i]
                current_layer = layer_idx

        # Final segment
        sx, sy = grid.grid_to_mm(current_start[0], current_start[1])
        ex, ey = grid.grid_to_mm(path[-1][0], path[-1][1])
        if abs(sx - ex) > 0.01 or abs(sy - ey) > 0.01:
            layer = Layer.F_CU if current_layer == 0 else Layer.B_CU
            trace.add_segment(Point(sx, sy), Point(ex, ey), width, layer)

    def _mark_board_boundary(self, grid: RoutingGrid) -> None:
        """Mark board edges as obstacles."""
        for layer_idx in range(2):
            for x in range(grid.cols):
                grid.mark_obstacle(layer_idx, x, 0)
                grid.mark_obstacle(layer_idx, x, grid.rows - 1)
            for y in range(grid.rows):
                grid.mark_obstacle(layer_idx, 0, y)
                grid.mark_obstacle(layer_idx, grid.cols - 1, y)

    def _mark_all_pads(self, grid: RoutingGrid, board: Board) -> None:
        """Mark all component pads on the grid."""
        cfg = self.config
        for comp in board.components:
            for pad in comp.footprint.pads:
                abs_pos = pad.absolute_position(comp.position, comp.rotation)
                gx, gy = grid.mm_to_grid(abs_pos.x, abs_pos.y)

                pad_radius = max(pad.size_x, pad.size_y) / 2
                radius_cells = max(1, int(math.ceil(pad_radius / cfg.grid_resolution)))

                net_id = pad.net_id or 0

                if pad.is_smd:
                    layer_idx = 0  # top layer for SMD
                    if net_id:
                        grid.mark_pad(layer_idx, gx, gy, net_id, radius_cells)
                    else:
                        grid.mark_obstacle(layer_idx, gx, gy, radius_cells)
                else:
                    # Through-hole: mark on both layers
                    for layer_idx in range(2):
                        if net_id:
                            grid.mark_pad(layer_idx, gx, gy, net_id, radius_cells)
                        else:
                            grid.mark_obstacle(layer_idx, gx, gy, radius_cells)

    def _get_pad_positions(
        self, board: Board, net: Net,
    ) -> list[tuple[int, int, int]]:
        """Get grid positions of all pads in a net."""
        positions = []
        seen = set()

        for comp_ref, pad_num in net.pad_refs:
            comp = board.get_component(comp_ref)
            if comp is None:
                continue
            pad = comp.footprint.get_pad(pad_num)
            if pad is None:
                continue

            abs_pos = pad.absolute_position(comp.position, comp.rotation)
            grid = RoutingGrid(
                board.settings.width,
                board.settings.height,
                self.config.grid_resolution,
            )
            gx, gy = grid.mm_to_grid(abs_pos.x, abs_pos.y)

            # Determine layer
            layer_idx = 0 if pad.is_smd else 0  # default to top for THT too

            key = (gx, gy, layer_idx)
            if key not in seen:
                seen.add(key)
                positions.append(key)

        return positions

    def _order_nets(self, board: Board) -> list[Net]:
        """Order nets for routing: short nets first, power/ground last."""
        def sort_key(net: Net) -> tuple[int, int]:
            priority = 0
            if net.is_ground:
                priority = 2  # ground last (gets copper pour)
            elif net.is_power:
                priority = 1  # power second-to-last
            return (priority, len(net.pad_refs))

        return sorted(board.nets, key=sort_key)

    def _emit_step(
        self,
        net_name: str,
        net_id: int,
        phase: str,
        path: list[tuple[float, float]],
        message: str = "",
        layer: str = "F.Cu",
    ) -> None:
        step = RouteStep(
            net_name=net_name,
            net_id=net_id,
            phase=phase,
            path=path,
            layer=layer,
            message=message,
        )
        self._steps.append(step)
        if self._on_step:
            self._on_step(step)
