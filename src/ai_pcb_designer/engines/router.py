"""PCB trace autorouter using A* pathfinding on a grid - Phase 2.

Fixes from Phase 1:
- Single shared RoutingGrid (no more grid-per-pad allocation)
- Through-hole pads marked on both layers
- Simplified trace segments (colinear segments merged)
- Better net ordering and progress reporting
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..core.board import Board
from ..core.datatypes import Layer, Point
from ..core.net import Net
from ..core.trace import Trace, TraceSegment, Via


@dataclass
class RouterConfig:
    grid_resolution: float = 0.25
    trace_width: float = 0.25
    via_diameter: float = 0.8
    via_drill: float = 0.4
    clearance: float = 0.2
    via_cost: float = 50.0
    direction_change_cost: float = 2.0
    max_iterations_per_net: int = 80000
    power_trace_width: float = 0.5


@dataclass
class RouteStep:
    net_name: str
    net_id: int
    phase: str
    path: list[tuple[float, float]] = field(default_factory=list)
    layer: str = "F.Cu"
    vias: list[tuple[float, float]] = field(default_factory=list)
    message: str = ""


DIRECTIONS_8 = [
    (1, 0), (0, 1), (-1, 0), (0, -1),
    (1, 1), (1, -1), (-1, 1), (-1, -1),
]


class RoutingGrid:
    """2D grid for pathfinding. Shared across all nets."""

    def __init__(self, width_mm: float, height_mm: float, resolution: float) -> None:
        self.resolution = resolution
        self.cols = max(1, int(math.ceil(width_mm / resolution)))
        self.rows = max(1, int(math.ceil(height_mm / resolution)))
        self.grid = np.zeros((2, self.rows, self.cols), dtype=np.int32)

    def mm_to_grid(self, x_mm: float, y_mm: float) -> tuple[int, int]:
        gx = int(round(x_mm / self.resolution))
        gy = int(round(y_mm / self.resolution))
        return max(0, min(gx, self.cols - 1)), max(0, min(gy, self.rows - 1))

    def grid_to_mm(self, gx: int, gy: int) -> tuple[float, float]:
        return gx * self.resolution, gy * self.resolution

    def mark_obstacle(self, layer_idx: int, gx: int, gy: int, radius: int = 1) -> None:
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                nx, ny = gx + dx, gy + dy
                if 0 <= nx < self.cols and 0 <= ny < self.rows:
                    if self.grid[layer_idx, ny, nx] == 0:
                        self.grid[layer_idx, ny, nx] = 1

    def mark_pad(self, layer_idx: int, gx: int, gy: int, net_id: int, radius: int = 1) -> None:
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                nx, ny = gx + dx, gy + dy
                if 0 <= nx < self.cols and 0 <= ny < self.rows:
                    self.grid[layer_idx, ny, nx] = net_id + 10

    def mark_trace(self, layer_idx: int, gx: int, gy: int, clearance: int = 1) -> None:
        for dx in range(-clearance, clearance + 1):
            for dy in range(-clearance, clearance + 1):
                nx, ny = gx + dx, gy + dy
                if 0 <= nx < self.cols and 0 <= ny < self.rows:
                    if self.grid[layer_idx, ny, nx] == 0:
                        self.grid[layer_idx, ny, nx] = 2

    def is_free(self, layer_idx: int, gx: int, gy: int, net_id: int) -> bool:
        if not (0 <= gx < self.cols and 0 <= gy < self.rows):
            return False
        val = self.grid[layer_idx, gy, gx]
        return val == 0 or val == net_id + 10


class AutoRouter:
    """Grid-based A* autorouter with multi-layer support."""

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
        self._steps = []
        cfg = self.config

        grid = RoutingGrid(board.settings.width, board.settings.height, cfg.grid_resolution)
        self._mark_board_boundary(grid)
        self._mark_all_pads(grid, board)

        ordered_nets = self._order_nets(board)

        total_nets = len([n for n in ordered_nets if len(n.pad_refs) >= 2])
        routed_count = 0
        failed_count = 0

        for net in ordered_nets:
            if len(net.pad_refs) < 2:
                continue

            pad_positions = self._get_pad_positions(grid, board, net)
            if len(pad_positions) < 2:
                continue

            trace_width = cfg.power_trace_width if (
                net.is_power or net.is_ground
            ) else cfg.trace_width

            self._emit_step(net.name, net.id, "searching",
                            message=f"Routing {net.name} ({routed_count + 1}/{total_nets})")

            trace = Trace(net_id=net.id)
            connected = {0}
            unconnected = set(range(1, len(pad_positions)))

            while unconnected:
                best_path = None
                best_cost = float("inf")
                best_to = -1

                for ci in connected:
                    for ui in unconnected:
                        path, switches = self._astar(
                            grid, pad_positions[ci], pad_positions[ui], net.id
                        )
                        if path is not None:
                            cost = len(path) + len(switches) * cfg.via_cost
                            if cost < best_cost:
                                best_cost = cost
                                best_path = path
                                best_to = ui

                if best_path is None:
                    failed_count += 1
                    self._emit_step(net.name, net.id, "failed",
                                    message=f"Could not route: {net.name}")
                    break

                self._path_to_trace(grid, best_path, trace, trace_width, net.id)

                clearance_cells = max(1, int(math.ceil(
                    (trace_width / 2 + cfg.clearance) / cfg.grid_resolution
                )))
                for gx, gy, layer_idx in best_path:
                    grid.mark_trace(layer_idx, gx, gy, clearance_cells)

                connected.add(best_to)
                unconnected.discard(best_to)

            if trace.segments:
                trace.segments = self._simplify_segments(trace.segments)
                board.add_trace(trace)
                routed_count += 1
                self._emit_step(net.name, net.id, "placed",
                                message=f"Routed {net.name} ({len(trace.segments)} segs)")

        return failed_count == 0, self._steps

    def _astar(
        self, grid: RoutingGrid,
        start: tuple[int, int, int], end: tuple[int, int, int], net_id: int,
    ) -> tuple[list[tuple[int, int, int]] | None, list[tuple[int, int]]]:
        cfg = self.config
        sx, sy, sl = start
        ex, ey, el = end

        open_set: list[tuple[float, float, tuple[int, int, int]]] = []
        heapq.heappush(open_set, (0.0, 0.0, (sx, sy, sl)))
        came_from: dict[tuple[int, int, int], tuple[int, int, int] | None] = {(sx, sy, sl): None}
        g_score: dict[tuple[int, int, int], float] = {(sx, sy, sl): 0.0}

        iterations = 0

        while open_set and iterations < cfg.max_iterations_per_net:
            iterations += 1
            f, g, current = heapq.heappop(open_set)
            cx, cy, cl = current

            if abs(cx - ex) <= 1 and abs(cy - ey) <= 1 and (cl == el or el == -1):
                path = []
                node = current
                while node is not None:
                    path.append(node)
                    node = came_from[node]
                path.reverse()
                switches = [(path[i][0], path[i][1])
                            for i in range(1, len(path)) if path[i][2] != path[i - 1][2]]
                return path, switches

            for dx, dy in DIRECTIONS_8:
                nx, ny = cx + dx, cy + dy
                if not grid.is_free(cl, nx, ny, net_id):
                    continue
                move_cost = 1.414 if (dx != 0 and dy != 0) else 1.0
                parent = came_from.get(current)
                if parent is not None:
                    if (cx - parent[0], cy - parent[1]) != (dx, dy):
                        move_cost += cfg.direction_change_cost * 0.1
                new_g = g + move_cost
                neighbor = (nx, ny, cl)
                if neighbor not in g_score or new_g < g_score[neighbor]:
                    g_score[neighbor] = new_g
                    h = math.hypot(nx - ex, ny - ey)
                    heapq.heappush(open_set, (new_g + h, new_g, neighbor))
                    came_from[neighbor] = current

            other_layer = 1 - cl
            if grid.is_free(other_layer, cx, cy, net_id):
                new_g = g + cfg.via_cost
                via_n = (cx, cy, other_layer)
                if via_n not in g_score or new_g < g_score[via_n]:
                    g_score[via_n] = new_g
                    h = math.hypot(cx - ex, cy - ey)
                    heapq.heappush(open_set, (new_g + h, new_g, via_n))
                    came_from[via_n] = current

        return None, []

    def _path_to_trace(self, grid: RoutingGrid, path: list[tuple[int, int, int]],
                       trace: Trace, width: float, net_id: int) -> None:
        if len(path) < 2:
            return
        cfg = self.config
        current_start = path[0]
        current_layer = path[0][2]

        for i in range(1, len(path)):
            gx, gy, layer_idx = path[i]
            if layer_idx != current_layer:
                prev = path[i - 1]
                sx, sy = grid.grid_to_mm(current_start[0], current_start[1])
                ex, ey = grid.grid_to_mm(prev[0], prev[1])
                if abs(sx - ex) > 0.01 or abs(sy - ey) > 0.01:
                    layer = Layer.F_CU if current_layer == 0 else Layer.B_CU
                    trace.add_segment(Point(sx, sy), Point(ex, ey), width, layer)
                vx, vy = grid.grid_to_mm(prev[0], prev[1])
                trace.add_via(Point(vx, vy), cfg.via_diameter, cfg.via_drill)
                current_start = path[i]
                current_layer = layer_idx

        sx, sy = grid.grid_to_mm(current_start[0], current_start[1])
        ex, ey = grid.grid_to_mm(path[-1][0], path[-1][1])
        if abs(sx - ex) > 0.01 or abs(sy - ey) > 0.01:
            layer = Layer.F_CU if current_layer == 0 else Layer.B_CU
            trace.add_segment(Point(sx, sy), Point(ex, ey), width, layer)

    def _simplify_segments(self, segments: list[TraceSegment]) -> list[TraceSegment]:
        if len(segments) <= 1:
            return segments
        result = [segments[0]]
        for seg in segments[1:]:
            prev = result[-1]
            if (prev.layer == seg.layer and prev.width == seg.width
                    and abs(prev.end.x - seg.start.x) < 0.01
                    and abs(prev.end.y - seg.start.y) < 0.01):
                dx1 = prev.end.x - prev.start.x
                dy1 = prev.end.y - prev.start.y
                dx2 = seg.end.x - seg.start.x
                dy2 = seg.end.y - seg.start.y
                if abs(dx1 * dy2 - dy1 * dx2) < 0.01:
                    result[-1] = TraceSegment(prev.start, seg.end, prev.width, prev.layer, prev.net_id)
                    continue
            result.append(seg)
        return result

    def _mark_board_boundary(self, grid: RoutingGrid) -> None:
        edge = max(1, int(math.ceil(0.3 / grid.resolution)))
        for li in range(2):
            for x in range(grid.cols):
                for d in range(edge):
                    if d < grid.rows:
                        grid.grid[li, d, x] = 1
                    if grid.rows - 1 - d >= 0:
                        grid.grid[li, grid.rows - 1 - d, x] = 1
            for y in range(grid.rows):
                for d in range(edge):
                    if d < grid.cols:
                        grid.grid[li, y, d] = 1
                    if grid.cols - 1 - d >= 0:
                        grid.grid[li, y, grid.cols - 1 - d] = 1

    def _mark_all_pads(self, grid: RoutingGrid, board: Board) -> None:
        cfg = self.config
        for comp in board.components:
            for pad in comp.footprint.pads:
                abs_pos = pad.absolute_position(comp.position, comp.rotation)
                gx, gy = grid.mm_to_grid(abs_pos.x, abs_pos.y)
                pad_radius = max(pad.size_x, pad.size_y) / 2
                radius_cells = max(1, int(math.ceil(pad_radius / cfg.grid_resolution)))
                net_id = pad.net_id or 0

                if pad.is_smd:
                    if net_id:
                        grid.mark_pad(0, gx, gy, net_id, radius_cells)
                    else:
                        grid.mark_obstacle(0, gx, gy, radius_cells)
                else:
                    for li in range(2):
                        if net_id:
                            grid.mark_pad(li, gx, gy, net_id, radius_cells)
                        else:
                            grid.mark_obstacle(li, gx, gy, radius_cells)

    def _get_pad_positions(self, grid: RoutingGrid, board: Board,
                           net: Net) -> list[tuple[int, int, int]]:
        """Get grid positions using the SHARED grid."""
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
            gx, gy = grid.mm_to_grid(abs_pos.x, abs_pos.y)
            layer_idx = 0
            key = (gx, gy, layer_idx)
            if key not in seen:
                seen.add(key)
                positions.append(key)
        return positions

    def _order_nets(self, board: Board) -> list[Net]:
        def sort_key(net: Net) -> tuple[int, int]:
            p = 2 if net.is_ground else (1 if net.is_power else 0)
            return (p, len(net.pad_refs))
        return sorted(board.nets, key=sort_key)

    def _emit_step(self, net_name: str, net_id: int, phase: str,
                   path: list[tuple[float, float]] | None = None,
                   message: str = "") -> None:
        step = RouteStep(net_name=net_name, net_id=net_id, phase=phase,
                         path=path or [], message=message)
        self._steps.append(step)
        if self._on_step:
            self._on_step(step)
