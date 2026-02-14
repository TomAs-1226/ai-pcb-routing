"""PCB trace autorouter using A* pathfinding - Phase 4.

Key features:
- Rip-up-and-retry: when a net fails, rip up blocking nets and retry
- Route short signal nets first, then longer ones, then power/GND last
- GND gets both routed traces (Gerber connectivity) AND copper pour (KiCad)
- AI-driven via cost: short signal nets strongly prefer single-layer routing
- Nearest-neighbor heuristic for multi-pad nets (O(n) vs O(n²))
- Adaptive grid resolution for large boards (>50 nets)
- Better obstacle marking with proper clearance
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
from ..core.trace import CopperZone, Trace, TraceSegment, Via


@dataclass
class RouterConfig:
    grid_resolution: float = 0.5      # mm per grid cell
    trace_width: float = 0.25         # mm
    via_diameter: float = 0.8         # mm
    via_drill: float = 0.4            # mm
    clearance: float = 0.25           # mm (edge-to-edge copper clearance)
    via_cost: float = 80.0            # higher = fewer vias
    direction_change_cost: float = 1.5
    max_iterations_per_net: int = 150000
    power_trace_width: float = 0.5    # mm
    max_rip_up_attempts: int = 3      # rip-up-and-retry cycles
    gnd_pour: bool = True             # use ground pour instead of routing GND


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
    """2D multi-layer grid for A* pathfinding."""

    def __init__(self, width_mm: float, height_mm: float, resolution: float) -> None:
        self.resolution = resolution
        self.cols = max(1, int(math.ceil(width_mm / resolution)))
        self.rows = max(1, int(math.ceil(height_mm / resolution)))
        # Cell values: 0=free, 1=obstacle, 2=trace, net_id+100=pad for net
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
        marker = net_id + 100
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                nx, ny = gx + dx, gy + dy
                if 0 <= nx < self.cols and 0 <= ny < self.rows:
                    self.grid[layer_idx, ny, nx] = marker

    def mark_trace(self, layer_idx: int, gx: int, gy: int, net_id: int,
                   clearance: int = 1) -> None:
        """Mark a trace cell and its clearance zone."""
        marker = net_id + 100
        for dx in range(-clearance, clearance + 1):
            for dy in range(-clearance, clearance + 1):
                nx, ny = gx + dx, gy + dy
                if 0 <= nx < self.cols and 0 <= ny < self.rows:
                    val = self.grid[layer_idx, ny, nx]
                    if val == 0:
                        self.grid[layer_idx, ny, nx] = 2  # generic blocked

    def unmark_trace(self, layer_idx: int, gx: int, gy: int, clearance: int = 1) -> None:
        """Remove a trace and its clearance marking."""
        for dx in range(-clearance, clearance + 1):
            for dy in range(-clearance, clearance + 1):
                nx, ny = gx + dx, gy + dy
                if 0 <= nx < self.cols and 0 <= ny < self.rows:
                    if self.grid[layer_idx, ny, nx] == 2:
                        self.grid[layer_idx, ny, nx] = 0

    def is_free(self, layer_idx: int, gx: int, gy: int, net_id: int) -> bool:
        if not (0 <= gx < self.cols and 0 <= gy < self.rows):
            return False
        val = self.grid[layer_idx, gy, gx]
        return val == 0 or val == net_id + 100


class AutoRouter:
    """Grid-based A* autorouter with rip-up-and-retry for high completion rates."""

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
        """Route all nets on the board. Returns (all_routed, steps).

        The router adapts to board complexity: for large boards with
        many nets (e.g. LED matrices), it adjusts grid resolution and
        iteration limits to balance quality with performance.
        """
        self._steps = []
        cfg = self.config

        # AI: adapt grid resolution for large boards
        board_area = board.settings.width * board.settings.height
        net_count = len([n for n in board.nets if len(n.pad_refs) >= 2])
        if board_area > 5000 and net_count > 50:
            resolution = max(cfg.grid_resolution, 1.0)
            self._emit_step("", 0, "searching",
                            message=f"Large design ({net_count} nets, "
                            f"{board_area:.0f}mm²) — using {resolution}mm grid")
        else:
            resolution = cfg.grid_resolution

        grid = RoutingGrid(board.settings.width, board.settings.height, resolution)
        self._active_resolution = resolution
        self._mark_board_boundary(grid)
        self._mark_all_pads(grid, board)

        ordered_nets = self._order_nets(board)

        # Route ALL nets including GND (traces needed for Gerber connectivity)
        # GND pour is added ADDITIONALLY for KiCad (zone fill handles clearance)
        gnd_nets = [n for n in ordered_nets if n.is_ground and cfg.gnd_pour]
        all_routeable = ordered_nets  # Route everything

        routed_traces: dict[int, tuple[Trace, list[tuple[int, int, int]]]] = {}
        failed_nets: list[Net] = []

        # ─── Pass 1: Route all nets (including GND) ───────────────
        for net in all_routeable:
            if len(net.pad_refs) < 2:
                continue

            success, trace, path_cells = self._route_net(grid, board, net)
            if success and trace:
                routed_traces[net.id] = (trace, path_cells)
                board.add_trace(trace)
            else:
                failed_nets.append(net)

        # ─── Pass 2: Rip-up-and-retry for failed nets ─────────────
        for attempt in range(cfg.max_rip_up_attempts):
            if not failed_nets:
                break

            still_failed = []
            for net in failed_nets:
                success = self._rip_up_and_retry(
                    grid, board, net, routed_traces, all_routeable
                )
                if not success:
                    still_failed.append(net)

            failed_nets = still_failed

            if failed_nets:
                self._emit_step("", 0, "retry",
                                message=f"Rip-up pass {attempt + 1}: "
                                f"{len(failed_nets)} nets still unrouted")

        # ─── Pass 3: GND copper pour (for KiCad zone fill) ────────
        for net in gnd_nets:
            self._add_ground_pour(board, net)
            self._emit_step(net.name, net.id, "placed",
                            message=f"Added ground pour for {net.name}")

        total_routeable = len([n for n in all_routeable if len(n.pad_refs) >= 2])
        routed_count = total_routeable - len(failed_nets)

        return len(failed_nets) == 0, self._steps

    def _route_net(
        self, grid: RoutingGrid, board: Board, net: Net,
    ) -> tuple[bool, Trace | None, list[tuple[int, int, int]]]:
        """Route a single net. Returns (success, trace, path_cells).

        The router is AI-aware: it adjusts strategy per net type.
        Short signal nets between adjacent components get higher via
        cost (prefer staying on one layer). Power nets get lower via
        cost (they may need both layers).
        """
        cfg = self.config
        res = getattr(self, "_active_resolution", cfg.grid_resolution)

        pad_positions = self._get_pad_positions(grid, board, net)
        if len(pad_positions) < 2:
            return False, None, []

        trace_width = cfg.power_trace_width if (
            net.is_power or net.is_ground
        ) else cfg.trace_width

        # AI: compute effective via cost based on net characteristics
        if net.is_power or net.is_ground:
            effective_via_cost = cfg.via_cost * 0.5  # power: vias OK
        elif len(pad_positions) == 2:
            gx1, gy1, _ = pad_positions[0]
            gx2, gy2, _ = pad_positions[1]
            est_len = math.hypot(gx2 - gx1, gy2 - gy1) * res
            if est_len < 15:
                effective_via_cost = cfg.via_cost * 3.0  # short: avoid vias
            else:
                effective_via_cost = cfg.via_cost * 1.5
        else:
            effective_via_cost = cfg.via_cost

        self._current_via_cost = effective_via_cost

        self._emit_step(net.name, net.id, "searching",
                        message=f"Routing {net.name} ({len(pad_positions)} pads)")

        trace = Trace(net_id=net.id)
        all_path_cells: list[tuple[int, int, int]] = []
        connected = {0}
        unconnected = set(range(1, len(pad_positions)))

        while unconnected:
            best_path = None
            best_cost = float("inf")
            best_to = -1

            # AI: nearest-neighbor heuristic instead of trying ALL pairs
            candidates: list[tuple[float, int, int]] = []
            for ui in unconnected:
                ux, uy, _ = pad_positions[ui]
                min_dist = float("inf")
                best_ci = 0
                for ci in connected:
                    cx, cy, _ = pad_positions[ci]
                    d = math.hypot(ux - cx, uy - cy)
                    if d < min_dist:
                        min_dist = d
                        best_ci = ci
                candidates.append((min_dist, ui, best_ci))
            candidates.sort()

            # Try the nearest 3 candidates
            for _, ui, ci in candidates[:3]:
                path, switches = self._astar(
                    grid, pad_positions[ci], pad_positions[ui], net.id
                )
                if path is not None:
                    cost = len(path) + len(switches) * effective_via_cost
                    if cost < best_cost:
                        best_cost = cost
                        best_path = path
                        best_to = ui

            # If nearest candidates failed, try more
            if best_path is None and len(candidates) > 3:
                for _, ui, ci in candidates[3:min(8, len(candidates))]:
                    path, switches = self._astar(
                        grid, pad_positions[ci], pad_positions[ui], net.id
                    )
                    if path is not None:
                        cost = len(path) + len(switches) * effective_via_cost
                        if cost < best_cost:
                            best_cost = cost
                            best_path = path
                            best_to = ui

            if best_path is None:
                self._emit_step(net.name, net.id, "failed",
                                message=f"Could not route: {net.name}")
                return False, None, []

            self._path_to_trace(grid, best_path, trace, trace_width, net.id)

            clearance_cells = max(1, int(math.ceil(
                (trace_width / 2 + cfg.clearance) / res
            )))
            for gx, gy, layer_idx in best_path:
                grid.mark_trace(layer_idx, gx, gy, net.id, clearance_cells)
                all_path_cells.append((gx, gy, layer_idx))

            connected.add(best_to)
            unconnected.discard(best_to)

        if trace.segments:
            trace.segments = self._simplify_segments(trace.segments)
            self._emit_step(net.name, net.id, "placed",
                            message=f"Routed {net.name} ({len(trace.segments)} segs)")
            return True, trace, all_path_cells

        return False, None, []

    def _rip_up_and_retry(
        self,
        grid: RoutingGrid,
        board: Board,
        failed_net: Net,
        routed_traces: dict[int, tuple[Trace, list[tuple[int, int, int]]]],
        all_nets: list[Net],
    ) -> bool:
        """Rip up blocking nets and retry routing the failed net."""
        cfg = self.config

        pad_positions = self._get_pad_positions(grid, board, failed_net)
        if len(pad_positions) < 2:
            return False

        # Find which routed nets might be blocking us
        blocking_net_ids: set[int] = set()
        for pos in pad_positions:
            gx, gy, li = pos
            for dx in range(-10, 11):
                for dy in range(-10, 11):
                    nx, ny = gx + dx, gy + dy
                    if 0 <= nx < grid.cols and 0 <= ny < grid.rows:
                        val = grid.grid[li, ny, nx]
                        if val >= 100:
                            bid = val - 100
                            if bid != failed_net.id and bid in routed_traces:
                                blocking_net_ids.add(bid)

        if not blocking_net_ids:
            return False

        clearance_cells = max(1, int(math.ceil(
            (cfg.trace_width / 2 + cfg.clearance) / cfg.grid_resolution
        )))

        for bid in list(blocking_net_ids)[:2]:
            if bid not in routed_traces:
                continue

            old_trace, old_cells = routed_traces[bid]

            # Rip up
            board.traces = [t for t in board.traces if t.net_id != bid]
            for gx, gy, li in old_cells:
                grid.unmark_trace(li, gx, gy, clearance_cells)
            del routed_traces[bid]

            # Try routing the failed net
            success, trace, path_cells = self._route_net(grid, board, failed_net)
            if success and trace:
                routed_traces[failed_net.id] = (trace, path_cells)
                board.add_trace(trace)

                # Re-route the ripped net
                ripped_net = next((n for n in all_nets if n.id == bid), None)
                if ripped_net:
                    s2, t2, pc2 = self._route_net(grid, board, ripped_net)
                    if s2 and t2:
                        routed_traces[bid] = (t2, pc2)
                        board.add_trace(t2)
                        return True
                    else:
                        # Undo: ripped net can't re-route
                        board.traces = [t for t in board.traces if t.net_id != failed_net.id]
                        for gx2, gy2, li2 in path_cells:
                            grid.unmark_trace(li2, gx2, gy2, clearance_cells)
                        del routed_traces[failed_net.id]
                        s3, t3, pc3 = self._route_net(grid, board, ripped_net)
                        if s3 and t3:
                            routed_traces[bid] = (t3, pc3)
                            board.add_trace(t3)
                else:
                    return True
            else:
                # Re-route the ripped net back
                ripped_net = next((n for n in all_nets if n.id == bid), None)
                if ripped_net:
                    s2, t2, pc2 = self._route_net(grid, board, ripped_net)
                    if s2 and t2:
                        routed_traces[bid] = (t2, pc2)
                        board.add_trace(t2)

        return False

    def _add_ground_pour(self, board: Board, net: Net) -> None:
        """Add a ground copper pour covering the entire board."""
        w = board.settings.width
        h = board.settings.height
        margin = 0.5

        zone = CopperZone(
            net_id=net.id,
            layer=Layer.B_CU,
            outline=[
                Point(margin, margin),
                Point(w - margin, margin),
                Point(w - margin, h - margin),
                Point(margin, h - margin),
            ],
            clearance=0.3,
        )
        board.add_zone(zone)

        zone_f = CopperZone(
            net_id=net.id,
            layer=Layer.F_CU,
            outline=[
                Point(margin, margin),
                Point(w - margin, margin),
                Point(w - margin, h - margin),
                Point(margin, h - margin),
            ],
            clearance=0.3,
            priority=0,
        )
        board.add_zone(zone_f)

    def _astar(
        self, grid: RoutingGrid,
        start: tuple[int, int, int], end: tuple[int, int, int], net_id: int,
    ) -> tuple[list[tuple[int, int, int]] | None, list[tuple[int, int]]]:
        """A* pathfinding between two grid positions."""
        cfg = self.config
        sx, sy, sl = start
        ex, ey, el = end

        open_set: list[tuple[float, float, tuple[int, int, int]]] = []
        heapq.heappush(open_set, (0.0, 0.0, (sx, sy, sl)))
        came_from: dict[tuple[int, int, int], tuple[int, int, int] | None] = {
            (sx, sy, sl): None
        }
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
                switches = [
                    (path[i][0], path[i][1])
                    for i in range(1, len(path))
                    if path[i][2] != path[i - 1][2]
                ]
                return path, switches

            for dx, dy in DIRECTIONS_8:
                nx, ny = cx + dx, cy + dy
                if not grid.is_free(cl, nx, ny, net_id):
                    continue

                move_cost = 1.414 if (dx != 0 and dy != 0) else 1.0

                parent = came_from.get(current)
                if parent is not None:
                    pdx, pdy = cx - parent[0], cy - parent[1]
                    if (pdx, pdy) != (dx, dy):
                        move_cost += cfg.direction_change_cost * 0.15

                new_g = g + move_cost
                neighbor = (nx, ny, cl)

                if neighbor not in g_score or new_g < g_score[neighbor]:
                    g_score[neighbor] = new_g
                    h = math.hypot(nx - ex, ny - ey)
                    heapq.heappush(open_set, (new_g + h, new_g, neighbor))
                    came_from[neighbor] = current

            other_layer = 1 - cl
            via_cost = getattr(self, "_current_via_cost", cfg.via_cost)
            if grid.is_free(other_layer, cx, cy, net_id):
                new_g = g + via_cost
                via_n = (cx, cy, other_layer)
                if via_n not in g_score or new_g < g_score[via_n]:
                    g_score[via_n] = new_g
                    h = math.hypot(cx - ex, cy - ey)
                    heapq.heappush(open_set, (new_g + h, new_g, via_n))
                    came_from[via_n] = current

        return None, []

    def _path_to_trace(
        self, grid: RoutingGrid, path: list[tuple[int, int, int]],
        trace: Trace, width: float, net_id: int,
    ) -> None:
        """Convert a grid path to trace segments and vias."""
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
        """Merge colinear adjacent segments."""
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
                cross = abs(dx1 * dy2 - dy1 * dx2)
                if cross < 0.01:
                    result[-1] = TraceSegment(
                        prev.start, seg.end, prev.width, prev.layer, prev.net_id
                    )
                    continue
            result.append(seg)
        return result

    def _mark_board_boundary(self, grid: RoutingGrid) -> None:
        """Mark board edges as obstacles."""
        edge = max(1, int(math.ceil(0.5 / grid.resolution)))
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
        """Mark all pads on the grid."""
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

    def _get_pad_positions(
        self, grid: RoutingGrid, board: Board, net: Net,
    ) -> list[tuple[int, int, int]]:
        """Get grid positions for all pads in a net."""
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
        """Order nets: short signal nets first, then power, then GND."""
        def sort_key(net: Net) -> tuple[int, int, float]:
            if net.is_ground:
                priority = 2
            elif net.is_power:
                priority = 1
            else:
                priority = 0

            pad_count = len(net.pad_refs)

            wire_len = 0.0
            if pad_count >= 2:
                positions = []
                for comp_ref, pad_num in net.pad_refs:
                    comp = board.get_component(comp_ref)
                    if comp:
                        pos = comp.get_pad_absolute_position(pad_num)
                        if pos:
                            positions.append(pos)
                if len(positions) >= 2:
                    for i in range(len(positions) - 1):
                        wire_len += positions[i].distance_to(positions[i + 1])

            return (priority, pad_count, wire_len)

        return sorted(board.nets, key=sort_key)

    def _emit_step(
        self, net_name: str, net_id: int, phase: str,
        path: list[tuple[float, float]] | None = None,
        message: str = "",
    ) -> None:
        step = RouteStep(
            net_name=net_name, net_id=net_id, phase=phase,
            path=path or [], message=message,
        )
        self._steps.append(step)
        if self._on_step:
            self._on_step(step)
