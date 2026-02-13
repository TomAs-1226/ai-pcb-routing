"""Real-time PCB board renderer using Qt QGraphicsView.

Renders all PCB layers with accurate colors:
- Copper traces and pads
- Solder mask
- Silkscreen
- Board outline
- Component placement with reference designators
- Ratsnest (unrouted connections)

Supports pan, zoom, and layer visibility toggling.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QRectF, QPointF, QLineF
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

if TYPE_CHECKING:
    from ..core.board import Board
    from ..core.component import Component
    from ..core.datatypes import Layer

# ─── Color Palette ──────────────────────────────────────────────────────────

COLORS = {
    "board": QColor(30, 40, 30),        # Dark green board
    "board_edge": QColor(200, 200, 50),  # Yellow board outline
    "f_cu": QColor(200, 0, 0, 180),     # Red - front copper
    "b_cu": QColor(0, 0, 200, 180),     # Blue - back copper
    "f_mask": QColor(0, 100, 0, 80),    # Green tint - front mask
    "f_silk": QColor(255, 255, 255),    # White - front silkscreen
    "b_silk": QColor(200, 200, 200),    # Light gray - back silkscreen
    "via": QColor(180, 180, 0),         # Yellow vias
    "via_drill": QColor(40, 40, 40),    # Dark drill hole
    "pad_smd": QColor(200, 0, 0, 200),  # Red SMD pads
    "pad_tht": QColor(200, 180, 0),     # Gold THT pads
    "drill": QColor(40, 40, 40),        # Drill holes
    "ratsnest": QColor(100, 100, 255, 100),  # Light blue ratsnest
    "grid": QColor(50, 60, 50),         # Subtle grid
    "text": QColor(220, 220, 220),      # Reference text
    "courtyard": QColor(200, 0, 200, 40),  # Purple courtyard
    "highlight": QColor(255, 255, 0, 100),  # Yellow highlight
}

# Scale factor: 1mm = N pixels in the scene
MM_TO_PX = 10.0


class PCBGraphicsView(QGraphicsView):
    """Custom QGraphicsView with pan/zoom for PCB display."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        # View settings
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setBackgroundBrush(QBrush(QColor(20, 25, 20)))

        self._zoom_level = 1.0
        self._board: Board | None = None
        self._layer_visibility: dict[str, bool] = {
            "board": True,
            "f_cu": True,
            "b_cu": True,
            "f_silk": True,
            "pads": True,
            "vias": True,
            "traces": True,
            "ratsnest": True,
            "courtyard": False,
            "grid": True,
            "refs": True,
        }

    @property
    def layer_visibility(self) -> dict[str, bool]:
        return self._layer_visibility

    def set_layer_visible(self, layer_name: str, visible: bool) -> None:
        self._layer_visibility[layer_name] = visible
        if self._board:
            self.render_board(self._board)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Zoom with mouse wheel."""
        factor = 1.15
        if event.angleDelta().y() > 0:
            self.scale(factor, factor)
            self._zoom_level *= factor
        else:
            self.scale(1 / factor, 1 / factor)
            self._zoom_level /= factor

    def fit_board(self) -> None:
        """Fit the entire board in the view."""
        if self._scene.sceneRect().isNull():
            return
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom_level = 1.0

    def render_board(self, board: Board) -> None:
        """Render the entire board from scratch."""
        self._board = board
        self._scene.clear()

        vis = self._layer_visibility

        if vis.get("grid"):
            self._draw_grid(board)

        if vis.get("board"):
            self._draw_board_outline(board)

        if vis.get("courtyard"):
            self._draw_courtyards(board)

        if vis.get("f_cu") or vis.get("b_cu"):
            self._draw_traces(board)

        if vis.get("pads"):
            self._draw_pads(board)

        if vis.get("vias"):
            self._draw_vias(board)

        if vis.get("f_silk"):
            self._draw_silkscreen(board)

        if vis.get("ratsnest"):
            self._draw_ratsnest(board)

        if vis.get("refs"):
            self._draw_references(board)

        # Set scene rect with margin
        margin = 10 * MM_TO_PX
        self._scene.setSceneRect(
            -margin,
            -margin,
            board.settings.width * MM_TO_PX + 2 * margin,
            board.settings.height * MM_TO_PX + 2 * margin,
        )

    def _draw_grid(self, board: Board) -> None:
        """Draw placement grid."""
        pen = QPen(COLORS["grid"], 0.5)
        grid_mm = board.settings.grid_size
        w = board.settings.width
        h = board.settings.height

        # Don't draw grid if it would be too many lines
        if w / grid_mm > 200 or h / grid_mm > 200:
            grid_mm = max(w, h) / 50

        x = 0.0
        while x <= w:
            self._scene.addLine(
                x * MM_TO_PX, 0, x * MM_TO_PX, h * MM_TO_PX, pen
            )
            x += grid_mm

        y = 0.0
        while y <= h:
            self._scene.addLine(
                0, y * MM_TO_PX, w * MM_TO_PX, y * MM_TO_PX, pen
            )
            y += grid_mm

    def _draw_board_outline(self, board: Board) -> None:
        """Draw board edge outline and fill."""
        w = board.settings.width * MM_TO_PX
        h = board.settings.height * MM_TO_PX

        # Board fill
        rect = self._scene.addRect(
            0, 0, w, h,
            QPen(COLORS["board_edge"], 2),
            QBrush(COLORS["board"]),
        )
        rect.setZValue(-100)

    def _draw_pads(self, board: Board) -> None:
        """Draw all component pads."""
        for comp in board.components:
            for pad in comp.footprint.pads:
                abs_pos = pad.absolute_position(comp.position, comp.rotation)
                sx = pad.size_x * MM_TO_PX
                sy = pad.size_y * MM_TO_PX
                px = abs_pos.x * MM_TO_PX
                py = abs_pos.y * MM_TO_PX

                color = COLORS["pad_smd"] if pad.is_smd else COLORS["pad_tht"]

                if pad.shape.value == "circle":
                    item = self._scene.addEllipse(
                        px - sx / 2, py - sy / 2, sx, sy,
                        QPen(Qt.PenStyle.NoPen),
                        QBrush(color),
                    )
                else:
                    item = self._scene.addRect(
                        px - sx / 2, py - sy / 2, sx, sy,
                        QPen(Qt.PenStyle.NoPen),
                        QBrush(color),
                    )
                item.setZValue(10)

                # Draw drill hole for THT pads
                if pad.drill_size > 0:
                    ds = pad.drill_size * MM_TO_PX
                    drill = self._scene.addEllipse(
                        px - ds / 2, py - ds / 2, ds, ds,
                        QPen(Qt.PenStyle.NoPen),
                        QBrush(COLORS["drill"]),
                    )
                    drill.setZValue(11)

    def _draw_traces(self, board: Board) -> None:
        """Draw all routed traces."""
        for seg in board.get_all_segments():
            from ..core.datatypes import Layer as L
            color = COLORS["f_cu"] if seg.layer == L.F_CU else COLORS["b_cu"]
            z = 5 if seg.layer == L.F_CU else 4

            pen = QPen(color, seg.width * MM_TO_PX)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)

            line = self._scene.addLine(
                seg.start.x * MM_TO_PX, seg.start.y * MM_TO_PX,
                seg.end.x * MM_TO_PX, seg.end.y * MM_TO_PX,
                pen,
            )
            line.setZValue(z)

    def _draw_vias(self, board: Board) -> None:
        """Draw all vias."""
        for via in board.get_all_vias():
            px = via.position.x * MM_TO_PX
            py = via.position.y * MM_TO_PX
            d = via.diameter * MM_TO_PX
            dd = via.drill * MM_TO_PX

            # Via annular ring
            ring = self._scene.addEllipse(
                px - d / 2, py - d / 2, d, d,
                QPen(Qt.PenStyle.NoPen),
                QBrush(COLORS["via"]),
            )
            ring.setZValue(12)

            # Via drill
            drill = self._scene.addEllipse(
                px - dd / 2, py - dd / 2, dd, dd,
                QPen(Qt.PenStyle.NoPen),
                QBrush(COLORS["via_drill"]),
            )
            drill.setZValue(13)

    def _draw_silkscreen(self, board: Board) -> None:
        """Draw silkscreen markings."""
        pen = QPen(COLORS["f_silk"], 1.2)

        for comp in board.components:
            for silk in comp.footprint.silk_lines:
                start = silk.start.rotate(comp.rotation) + comp.position
                end = silk.end.rotate(comp.rotation) + comp.position

                silk_pen = QPen(COLORS["f_silk"], silk.width * MM_TO_PX)
                line = self._scene.addLine(
                    start.x * MM_TO_PX, start.y * MM_TO_PX,
                    end.x * MM_TO_PX, end.y * MM_TO_PX,
                    silk_pen,
                )
                line.setZValue(15)

            for circle in comp.footprint.silk_circles:
                center = circle.center.rotate(comp.rotation) + comp.position
                r = circle.radius * MM_TO_PX
                circ_pen = QPen(COLORS["f_silk"], circle.width * MM_TO_PX)
                item = self._scene.addEllipse(
                    center.x * MM_TO_PX - r,
                    center.y * MM_TO_PX - r,
                    2 * r, 2 * r,
                    circ_pen,
                    QBrush(Qt.BrushStyle.NoBrush),
                )
                item.setZValue(15)

    def _draw_ratsnest(self, board: Board) -> None:
        """Draw unrouted net connections as thin lines."""
        pen = QPen(COLORS["ratsnest"], 1)
        pen.setStyle(Qt.PenStyle.DashLine)

        routed_net_ids = {t.net_id for t in board.traces}

        for net in board.nets:
            if net.id in routed_net_ids:
                continue
            if len(net.pad_refs) < 2:
                continue

            # Draw lines between all pad pairs in unrouted nets
            positions = []
            for comp_ref, pad_num in net.pad_refs:
                comp = board.get_component(comp_ref)
                if comp:
                    pos = comp.get_pad_absolute_position(pad_num)
                    if pos:
                        positions.append(pos)

            for i in range(len(positions) - 1):
                p1 = positions[i]
                p2 = positions[i + 1]
                line = self._scene.addLine(
                    p1.x * MM_TO_PX, p1.y * MM_TO_PX,
                    p2.x * MM_TO_PX, p2.y * MM_TO_PX,
                    pen,
                )
                line.setZValue(1)

    def _draw_references(self, board: Board) -> None:
        """Draw component reference designators."""
        font = QFont("Monospace", 7)

        for comp in board.components:
            text = self._scene.addSimpleText(comp.reference, font)
            text.setBrush(QBrush(COLORS["text"]))
            text.setPos(
                comp.position.x * MM_TO_PX - 10,
                comp.position.y * MM_TO_PX - 15,
            )
            text.setZValue(20)

    def _draw_courtyards(self, board: Board) -> None:
        """Draw component courtyard areas."""
        for comp in board.components:
            cy = comp.footprint.courtyard
            if cy is None:
                continue

            r = cy.rect
            self._scene.addRect(
                (comp.position.x + r.x) * MM_TO_PX,
                (comp.position.y + r.y) * MM_TO_PX,
                r.width * MM_TO_PX,
                r.height * MM_TO_PX,
                QPen(COLORS["courtyard"], 1),
                QBrush(COLORS["courtyard"]),
            )
