"""3D PCB board viewer using software rendering.

Renders a pseudo-3D isometric view of the PCB board showing:
- Board substrate (green PCB with thickness)
- Component bodies with height
- Pads on the surface
- Traces on copper layers
- Vias as cylinders
- Silk outlines on components

Uses QPainter-based software rendering for maximum compatibility
(works without OpenGL/GPU). Supports mouse rotation and zoom.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QPointF, QRectF, QPoint
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QWheelEvent,
    QMouseEvent,
)
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from ..core.board import Board


@dataclass
class Camera:
    """Simple isometric camera."""
    rot_x: float = 35.0  # tilt angle (degrees)
    rot_z: float = 30.0  # rotation angle (degrees)
    zoom: float = 6.0
    offset_x: float = 0.0
    offset_y: float = 0.0


# Colors
BOARD_COLOR_TOP = QColor(20, 80, 20)       # Dark green PCB top
BOARD_COLOR_SIDE = QColor(15, 60, 15)      # Darker side
BOARD_COLOR_BOTTOM = QColor(10, 50, 10)    # Darkest bottom
COPPER_F = QColor(200, 160, 80, 180)       # Gold/copper front
COPPER_B = QColor(200, 160, 80, 100)       # Lighter copper back
SOLDER_MASK = QColor(0, 100, 30, 160)      # Green solder mask
PAD_COLOR = QColor(200, 170, 80)           # Gold pads
VIA_COLOR = QColor(180, 180, 0)            # Yellow vias
TRACE_F_COLOR = QColor(200, 50, 50, 160)   # Red traces (front)
TRACE_B_COLOR = QColor(50, 50, 200, 160)   # Blue traces (back)
SILK_COLOR = QColor(255, 255, 255, 200)    # White silk
BG_COLOR = QColor(25, 25, 35)              # Dark background

# Component body colors by type
_COMP_COLORS = {
    "ic":        QColor(30, 30, 30),       # Dark gray IC body
    "passive":   QColor(40, 30, 20),       # Brown passive body
    "connector": QColor(60, 60, 60),       # Medium gray connector
    "switch":    QColor(50, 50, 50),       # Dark switch
    "header":    QColor(30, 30, 30),       # Black header
    "led":       QColor(200, 200, 180),    # Light yellow LED
    "relay":     QColor(30, 30, 100),      # Blue relay
    "crystal":   QColor(180, 180, 180),    # Silver crystal
    "default":   QColor(40, 30, 20),       # Brown default
}


def _classify_component(ref: str, value: str) -> tuple[float, QColor]:
    """Determine component height and body color from reference/value.

    Returns (height_mm, body_color).
    """
    ref_up = ref.upper()
    val_up = value.upper()

    # Mounting holes - skip
    if ref_up.startswith("H"):
        return 0.0, _COMP_COLORS["default"]

    # ICs and modules
    if ref_up.startswith("U"):
        if "ESP32" in val_up:
            return 3.0, QColor(50, 50, 50)   # Taller module with shielding
        if "LDO" in val_up or "AMS1117" in val_up or "REG" in val_up:
            return 1.8, QColor(30, 30, 30)
        if "STM32" in val_up or "ATMEGA" in val_up or "PIC" in val_up:
            return 1.5, QColor(30, 30, 30)
        if "OLED" in val_up or "SSD1306" in val_up:
            return 2.0, QColor(20, 20, 40)   # Dark blue OLED module
        return 2.5, _COMP_COLORS["ic"]

    # Resistors
    if ref_up.startswith("R"):
        return 0.6, QColor(40, 30, 20)

    # Capacitors
    if ref_up.startswith("C"):
        if "100U" in val_up or "22U" in val_up or "47U" in val_up:
            return 1.2, QColor(140, 100, 40)  # Taller electrolytic
        return 0.6, QColor(120, 90, 50)  # Beige ceramic cap

    # LEDs
    if ref_up.startswith("D"):
        if "WS2812" in val_up or "NEOPIXEL" in val_up:
            return 1.5, QColor(255, 255, 240)  # White addressable LED
        if "1N" in val_up or "SCHOTTKY" in val_up:
            return 0.8, QColor(40, 40, 40)   # Black diode
        # Regular LED - slightly translucent look
        return 0.8, QColor(200, 30, 30)  # Red LED default

    # Connectors (USB, headers, jacks)
    if ref_up.startswith("J"):
        if "USB" in val_up:
            return 3.5, QColor(180, 180, 180)  # Silver USB
        if "BARREL" in val_up or "JACK" in val_up:
            return 5.0, QColor(30, 30, 30)
        if "MICROSD" in val_up or "SD" in val_up:
            return 2.0, QColor(180, 180, 180)
        if "FPC" in val_up or "FFC" in val_up:
            return 1.5, QColor(200, 180, 130)
        if "SCREW" in val_up or "TERMINAL" in val_up:
            return 6.0, QColor(0, 100, 0)  # Green terminal block
        if "SENSOR" in val_up:
            return 8.0, _COMP_COLORS["header"]
        # Pin headers
        return 8.0, _COMP_COLORS["header"]

    # Switches / buttons
    if ref_up.startswith("SW"):
        return 3.5, QColor(50, 50, 50)

    # Transistors / MOSFETs
    if ref_up.startswith("Q"):
        return 1.2, QColor(30, 30, 30)

    # Relays
    if ref_up.startswith("K"):
        return 10.0, _COMP_COLORS["relay"]

    # Inductors
    if ref_up.startswith("L"):
        return 1.0, QColor(50, 50, 50)

    # Crystals / oscillators
    if ref_up.startswith("Y") or "CRYSTAL" in val_up:
        return 0.8, _COMP_COLORS["crystal"]

    return 1.0, _COMP_COLORS["default"]


class Board3DWidget(QWidget):
    """3D PCB viewer widget using QPainter software rendering."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._board: Board | None = None
        self._camera = Camera()
        self._last_mouse_pos: QPoint | None = None
        self._drag_button: Qt.MouseButton | None = None

        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)

    def set_board(self, board: Board) -> None:
        self._board = board
        # Center camera on board
        self._camera.offset_x = board.settings.width / 2
        self._camera.offset_y = board.settings.height / 2
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta > 0:
            self._camera.zoom *= 1.15
        else:
            self._camera.zoom /= 1.15
        self._camera.zoom = max(1.0, min(50.0, self._camera.zoom))
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._last_mouse_pos = event.pos()
        self._drag_button = event.button()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._last_mouse_pos is None:
            return

        dx = event.pos().x() - self._last_mouse_pos.x()
        dy = event.pos().y() - self._last_mouse_pos.y()

        if self._drag_button == Qt.MouseButton.LeftButton:
            # Rotate
            self._camera.rot_z += dx * 0.5
            self._camera.rot_x = max(5, min(85, self._camera.rot_x - dy * 0.5))
        elif self._drag_button == Qt.MouseButton.RightButton:
            # Pan
            self._camera.offset_x -= dx / self._camera.zoom
            self._camera.offset_y -= dy / self._camera.zoom

        self._last_mouse_pos = event.pos()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._last_mouse_pos = None
        self._drag_button = None

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), BG_COLOR)

        if self._board is None:
            painter.setPen(QPen(QColor(128, 128, 128)))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                           "No board to display")
            painter.end()
            return

        board = self._board
        cam = self._camera
        w = self.width()
        h = self.height()
        cx, cy = w / 2, h / 2

        bw = board.settings.width
        bh = board.settings.height
        thickness = board.settings.design_rules.board_thickness

        # Pre-compute trig values for rotation
        rz = math.radians(cam.rot_z)
        rx = math.radians(cam.rot_x)
        cos_rz, sin_rz = math.cos(rz), math.sin(rz)
        cos_rx, sin_rx = math.cos(rx), math.sin(rx)

        # Project 3D -> 2D using isometric-like projection
        def project(x: float, y: float, z: float) -> tuple[float, float]:
            # Center on board
            px = x - cam.offset_x
            py = y - cam.offset_y

            # Rotate around Z axis
            x2 = px * cos_rz - py * sin_rz
            y2 = px * sin_rz + py * cos_rz

            # Tilt (rotate around X)
            y3 = y2 * cos_rx - z * sin_rx

            # Project to screen
            sx = cx + x2 * cam.zoom
            sy = cy + y3 * cam.zoom

            return sx, sy

        def depth(x: float, y: float, z: float) -> float:
            """Z-depth for sorting (higher = further from camera)."""
            px = x - cam.offset_x
            py = y - cam.offset_y
            y2 = px * sin_rz + py * cos_rz
            z3 = y2 * sin_rx + z * cos_rx
            return z3

        def rotate_point(px: float, py: float, angle_deg: float,
                        origin_x: float, origin_y: float) -> tuple[float, float]:
            """Rotate a point around an origin in 2D (board plane)."""
            rad = math.radians(angle_deg)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            dx = px - origin_x
            dy = py - origin_y
            return (origin_x + dx * cos_a - dy * sin_a,
                    origin_y + dx * sin_a + dy * cos_a)

        # ─── Draw Board Substrate ────────────────────────────────────

        # Board corners in 3D (top surface at z=0, bottom at z=-thickness)
        corners_top = [
            (0, 0, 0), (bw, 0, 0), (bw, bh, 0), (0, bh, 0)
        ]
        corners_bot = [
            (0, 0, -thickness), (bw, 0, -thickness),
            (bw, bh, -thickness), (0, bh, -thickness)
        ]

        # Draw board bottom first
        poly_bot = QPolygonF()
        for x, y, z in corners_bot:
            sx, sy = project(x, y, z)
            poly_bot.append(QPointF(sx, sy))
        painter.setPen(QPen(QColor(100, 100, 50), 1))
        painter.setBrush(QBrush(BOARD_COLOR_BOTTOM))
        painter.drawPolygon(poly_bot)

        # Draw board sides (4 sides)
        sides = [
            (0, 1), (1, 2), (2, 3), (3, 0)
        ]
        # Sort sides by depth to draw far ones first
        side_depths = []
        for i, j in sides:
            mid_x = (corners_top[i][0] + corners_top[j][0]) / 2
            mid_y = (corners_top[i][1] + corners_top[j][1]) / 2
            d = depth(mid_x, mid_y, -thickness / 2)
            side_depths.append((d, i, j))
        side_depths.sort(reverse=True)  # far first

        for _, i, j in side_depths:
            poly = QPolygonF()
            for x, y, z in [corners_top[i], corners_top[j],
                            corners_bot[j], corners_bot[i]]:
                sx, sy = project(x, y, z)
                poly.append(QPointF(sx, sy))
            painter.setPen(QPen(QColor(80, 80, 40), 1))
            painter.setBrush(QBrush(BOARD_COLOR_SIDE))
            painter.drawPolygon(poly)

        # Draw board top (solder mask)
        poly_top = QPolygonF()
        for x, y, z in corners_top:
            sx, sy = project(x, y, z)
            poly_top.append(QPointF(sx, sy))
        painter.setPen(QPen(QColor(100, 180, 80), 1))
        painter.setBrush(QBrush(SOLDER_MASK))
        painter.drawPolygon(poly_top)

        # ─── Collect and sort renderable items by depth ──────────────

        render_items = []  # (depth, draw_func)

        # Traces on front copper (z = 0.035, just above board)
        from ..core.datatypes import Layer as L
        for seg in board.get_all_segments():
            is_front = seg.layer == L.F_CU
            z = 0.05 if is_front else -thickness - 0.05
            color = TRACE_F_COLOR if is_front else TRACE_B_COLOR

            sx1, sy1 = project(seg.start.x, seg.start.y, z)
            sx2, sy2 = project(seg.end.x, seg.end.y, z)
            d = depth(
                (seg.start.x + seg.end.x) / 2,
                (seg.start.y + seg.end.y) / 2,
                z,
            )
            trace_w = max(1.5, seg.width * cam.zoom * 0.8)

            def draw_trace(p=painter, x1=sx1, y1=sy1, x2=sx2, y2=sy2,
                          tw=trace_w, c=color):
                pen = QPen(c, tw)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

            render_items.append((d, draw_trace))

        # Vias
        for via in board.get_all_vias():
            sx, sy = project(via.position.x, via.position.y, 0)
            d = depth(via.position.x, via.position.y, 0)
            r = max(2, via.diameter * cam.zoom * 0.4)
            dr = max(1, via.drill * cam.zoom * 0.4)

            def draw_via(p=painter, px=sx, py=sy, vr=r, vdr=dr):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(VIA_COLOR))
                p.drawEllipse(QPointF(px, py), vr, vr)
                p.setBrush(QBrush(QColor(40, 40, 40)))
                p.drawEllipse(QPointF(px, py), vdr, vdr)

            render_items.append((d, draw_via))

        # Pads
        for comp in board.components:
            for pad in comp.footprint.pads:
                abs_pos = pad.absolute_position(comp.position, comp.rotation)
                z = 0.05  # slightly above board surface
                sx, sy = project(abs_pos.x, abs_pos.y, z)
                d = depth(abs_pos.x, abs_pos.y, z)

                # Account for rotation in pad sizing
                rot_rad = math.radians(comp.rotation)
                cos_r = abs(math.cos(rot_rad))
                sin_r = abs(math.sin(rot_rad))
                pw_raw = pad.size_x * cos_r + pad.size_y * sin_r
                ph_raw = pad.size_x * sin_r + pad.size_y * cos_r
                pw = max(2, pw_raw * cam.zoom * 0.4)
                ph = max(2, ph_raw * cam.zoom * 0.4)

                def draw_pad(p=painter, px=sx, py=sy, ppw=pw, pph=ph,
                            is_smd=pad.is_smd, drill=pad.drill_size):
                    color = PAD_COLOR
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QBrush(color))
                    p.drawEllipse(QPointF(px, py), ppw, pph)
                    if drill > 0:
                        dr = max(1, drill * cam.zoom * 0.3)
                        p.setBrush(QBrush(QColor(40, 40, 40)))
                        p.drawEllipse(QPointF(px, py), dr, dr)

                render_items.append((d, draw_pad))

        # Component bodies
        for comp in board.components:
            ref = comp.reference.upper()

            # Determine component height and color
            comp_h, body_color = _classify_component(ref, comp.value)

            # Skip mounting holes and zero-height items
            if comp_h <= 0.0:
                continue

            # Get the footprint bounding rect (in local coordinates)
            fp_rect = comp.footprint.bounding_rect()

            # Compute the 4 corners of the component body in local coords
            local_corners = [
                (fp_rect.x, fp_rect.y),
                (fp_rect.x + fp_rect.width, fp_rect.y),
                (fp_rect.x + fp_rect.width, fp_rect.y + fp_rect.height),
                (fp_rect.x, fp_rect.y + fp_rect.height),
            ]

            # Rotate each corner by the component rotation and translate
            # to board coordinates
            board_corners = []
            for lx, ly in local_corners:
                bx, by = rotate_point(
                    lx, ly, comp.rotation, 0.0, 0.0
                )
                board_corners.append((
                    comp.position.x + bx,
                    comp.position.y + by,
                ))

            # Center for depth sorting
            avg_x = sum(c[0] for c in board_corners) / 4
            avg_y = sum(c[1] for c in board_corners) / 4
            d = depth(avg_x, avg_y, comp_h / 2)

            def draw_comp(p=painter, corners=board_corners,
                         cc_h=comp_h, cc_color=body_color,
                         cc_ref=comp.reference,
                         cc_val=comp.value):
                # Project all 8 corners (4 top + 4 bottom)
                top_corners = [project(bx, by, cc_h) for bx, by in corners]
                bot_corners = [project(bx, by, 0.1) for bx, by in corners]

                # Draw sides (sorted by depth for correct overlap)
                side_pairs = [(0, 1), (1, 2), (2, 3), (3, 0)]
                s_depths = []
                for si, sj in side_pairs:
                    mid_sx = (corners[si][0] + corners[sj][0]) / 2
                    mid_sy = (corners[si][1] + corners[sj][1]) / 2
                    s_d = depth(mid_sx, mid_sy, cc_h / 2)
                    s_depths.append((s_d, si, sj))
                s_depths.sort(reverse=True)

                side_color = QColor(
                    max(0, cc_color.red() - 20),
                    max(0, cc_color.green() - 20),
                    max(0, cc_color.blue() - 20),
                )

                for _, si, sj in s_depths:
                    poly = QPolygonF()
                    poly.append(QPointF(*top_corners[si]))
                    poly.append(QPointF(*top_corners[sj]))
                    poly.append(QPointF(*bot_corners[sj]))
                    poly.append(QPointF(*bot_corners[si]))
                    p.setPen(QPen(QColor(80, 80, 80), 0.5))
                    p.setBrush(QBrush(side_color))
                    p.drawPolygon(poly)

                # Top face
                poly_t = QPolygonF()
                for pt in top_corners:
                    poly_t.append(QPointF(*pt))
                p.setPen(QPen(QColor(100, 100, 100), 0.5))
                p.setBrush(QBrush(cc_color))
                p.drawPolygon(poly_t)

                # Pin 1 marker (small dot on top face)
                if len(top_corners) >= 1:
                    p1x, p1y = top_corners[0]
                    # Midpoint between corner 0 and center
                    tcx = sum(pt[0] for pt in top_corners) / 4
                    tcy = sum(pt[1] for pt in top_corners) / 4
                    mx = p1x * 0.7 + tcx * 0.3
                    my = p1y * 0.7 + tcy * 0.3
                    dot_r = max(1.5, cam.zoom * 0.3)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QBrush(QColor(255, 255, 255, 180)))
                    p.drawEllipse(QPointF(mx, my), dot_r, dot_r)

                # Reference + value text on top
                tcx = sum(pt[0] for pt in top_corners) / 4
                tcy = sum(pt[1] for pt in top_corners) / 4
                font = QFont("Monospace", max(5, int(cam.zoom * 0.8)))
                p.setFont(font)
                p.setPen(QPen(SILK_COLOR))
                p.drawText(
                    QRectF(tcx - 40, tcy - 12, 80, 14),
                    Qt.AlignmentFlag.AlignCenter,
                    cc_ref,
                )
                # Part value / name below reference
                if cc_val and cc_val != cc_ref:
                    font_small = QFont("Monospace", max(4, int(cam.zoom * 0.6)))
                    p.setFont(font_small)
                    p.setPen(QPen(QColor(200, 200, 160, 200)))
                    p.drawText(
                        QRectF(tcx - 40, tcy + 1, 80, 12),
                        Qt.AlignmentFlag.AlignCenter,
                        cc_val,
                    )

            render_items.append((d, draw_comp))

        # Silk screen lines on board surface
        for comp in board.components:
            for silk in comp.footprint.silk_lines:
                # Rotate silk line endpoints by component rotation
                s_abs = silk.start.rotate(comp.rotation) + comp.position
                e_abs = silk.end.rotate(comp.rotation) + comp.position
                z = 0.08
                sx1, sy1 = project(s_abs.x, s_abs.y, z)
                sx2, sy2 = project(e_abs.x, e_abs.y, z)
                d_val = depth(
                    (s_abs.x + e_abs.x) / 2,
                    (s_abs.y + e_abs.y) / 2, z)
                lw = max(0.5, silk.width * cam.zoom * 0.4)

                def draw_silk(p=painter, x1=sx1, y1=sy1, x2=sx2, y2=sy2,
                             slw=lw):
                    p.setPen(QPen(SILK_COLOR, slw))
                    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

                render_items.append((d_val, draw_silk))

        # Sort by depth (far objects first = painter's algorithm)
        render_items.sort(key=lambda item: item[0], reverse=True)

        # Draw all items
        for _, draw_fn in render_items:
            draw_fn()

        # Draw info text
        painter.setPen(QPen(QColor(150, 150, 150)))
        font = QFont("sans-serif", 10)
        painter.setFont(font)
        comp_count = len(board.components)
        net_count = len(board.nets)
        info_text = (
            f"Board: {bw:.0f} x {bh:.0f} mm  |  "
            f"{comp_count} components, {net_count} nets  |  "
            f"Drag: rotate  |  Right-drag: pan  |  Scroll: zoom"
        )
        painter.drawText(10, h - 10, info_text)

        painter.end()
