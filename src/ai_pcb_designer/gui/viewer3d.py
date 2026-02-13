"""3D PCB board viewer using software rendering.

Renders a pseudo-3D isometric view of the PCB board showing:
- Board substrate (green PCB with thickness)
- Component bodies with height
- Pads on the surface
- Traces on copper layers
- Vias as cylinders

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
COMP_BODY_COLOR = QColor(30, 30, 30)       # Dark gray IC body
COMP_BODY_PASSIVE = QColor(40, 30, 20)     # Brown passive body
SILK_COLOR = QColor(255, 255, 255, 200)    # White silk
BG_COLOR = QColor(25, 25, 35)              # Dark background


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

        # Project 3D -> 2D using isometric-like projection
        def project(x: float, y: float, z: float) -> tuple[float, float]:
            # Center on board
            px = x - cam.offset_x
            py = y - cam.offset_y

            # Rotate around Z axis
            rz = math.radians(cam.rot_z)
            rx = math.radians(cam.rot_x)

            x2 = px * math.cos(rz) - py * math.sin(rz)
            y2 = px * math.sin(rz) + py * math.cos(rz)
            z2 = z

            # Tilt (rotate around X)
            y3 = y2 * math.cos(rx) - z2 * math.sin(rx)
            z3 = y2 * math.sin(rx) + z2 * math.cos(rx)

            # Project to screen
            sx = cx + x2 * cam.zoom
            sy = cy + y3 * cam.zoom

            return sx, sy

        def depth(x: float, y: float, z: float) -> float:
            """Z-depth for sorting (higher = further from camera)."""
            rz = math.radians(cam.rot_z)
            rx = math.radians(cam.rot_x)
            px = x - cam.offset_x
            py = y - cam.offset_y
            x2 = px * math.cos(rz) - py * math.sin(rz)
            y2 = px * math.sin(rz) + py * math.cos(rz)
            z3 = y2 * math.sin(rx) + z * math.cos(rx)
            return z3

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
                pw = max(2, pad.size_x * cam.zoom * 0.4)
                ph = max(2, pad.size_y * cam.zoom * 0.4)

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
            fp_rect = comp.footprint.bounding_rect()
            ref = comp.reference.upper()

            # Determine component height
            if ref.startswith("U") or "ESP32" in comp.value.upper():
                comp_h = 2.5  # IC height
                body_color = COMP_BODY_COLOR
            elif ref.startswith("H"):
                continue  # Skip mounting holes for 3D
            elif ref.startswith(("R", "C", "D")):
                comp_h = 0.8  # Passive height
                body_color = COMP_BODY_PASSIVE
            elif "USB" in comp.value.upper():
                comp_h = 3.0  # Connector height
                body_color = QColor(60, 60, 60)
            elif ref.startswith("SW"):
                comp_h = 3.5
                body_color = QColor(50, 50, 50)
            elif ref.startswith("J"):
                comp_h = 8.0  # Pin header height
                body_color = QColor(30, 30, 30)
            else:
                comp_h = 1.0
                body_color = COMP_BODY_PASSIVE

            # Component bounding box corners (on top of board)
            cx = comp.position.x + fp_rect.x
            cy = comp.position.y + fp_rect.y
            cw = fp_rect.width
            ch = fp_rect.height

            d = depth(comp.position.x, comp.position.y, comp_h / 2)

            def draw_comp(p=painter, ccx=cx, ccy=cy, ccw=cw, cch=ch,
                         cc_h=comp_h, cc_color=body_color, cc_ref=comp.reference):
                # Top face
                top_corners = [
                    project(ccx, ccy, cc_h),
                    project(ccx + ccw, ccy, cc_h),
                    project(ccx + ccw, ccy + cch, cc_h),
                    project(ccx, ccy + cch, cc_h),
                ]
                # Bottom face (board surface)
                bot_corners = [
                    project(ccx, ccy, 0.1),
                    project(ccx + ccw, ccy, 0.1),
                    project(ccx + ccw, ccy + cch, 0.1),
                    project(ccx, ccy + cch, 0.1),
                ]

                # Draw sides (sorted by depth)
                side_pairs = [(0, 1), (1, 2), (2, 3), (3, 0)]
                s_depths = []
                for si, sj in side_pairs:
                    mid = (
                        (bot_corners[si][0] + bot_corners[sj][0]) / 2,
                        (bot_corners[si][1] + bot_corners[sj][1]) / 2,
                    )
                    s_depths.append((mid[1], si, sj))
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

                # Reference text on top
                center = project(ccx + ccw / 2, ccy + cch / 2, cc_h + 0.1)
                font = QFont("Monospace", max(5, int(cam.zoom * 0.8)))
                p.setFont(font)
                p.setPen(QPen(SILK_COLOR))
                p.drawText(
                    QRectF(center[0] - 30, center[1] - 8, 60, 16),
                    Qt.AlignmentFlag.AlignCenter,
                    cc_ref,
                )

            render_items.append((d, draw_comp))

        # Sort by depth (far objects first = painter's algorithm)
        render_items.sort(key=lambda item: item[0], reverse=True)

        # Draw all items
        for _, draw_fn in render_items:
            draw_fn()

        # Draw info text
        painter.setPen(QPen(QColor(150, 150, 150)))
        font = QFont("sans-serif", 10)
        painter.setFont(font)
        info_text = (
            f"Board: {bw:.0f} x {bh:.0f} mm  |  "
            f"Drag: rotate  |  Right-drag: pan  |  Scroll: zoom"
        )
        painter.drawText(10, h - 10, info_text)

        painter.end()
