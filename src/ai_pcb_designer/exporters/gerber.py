"""Gerber RS-274X / X2 file exporter.

Generates manufacturing-ready Gerber files for each PCB layer.
Uses the gerber-writer library for spec-compliant output.

If gerber-writer is not installed, falls back to direct RS-274X generation.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

from ..core.board import Board
from ..core.component import Component
from ..core.datatypes import Layer, PadShape, Point
from ..core.trace import TraceSegment, Via, CopperZone


# ─── Stroke font for silkscreen text ─────────────────────────────────────────
# Each character is a list of line segments: [(x1, y1, x2, y2), ...]
# in a 0-1 normalized coordinate system (scaled by font_size at render time).

_FONT: dict[str, list[tuple[float, float, float, float]]] = {
    "A": [(0, 1, 0.5, 0), (0.5, 0, 1, 1), (0.2, 0.6, 0.8, 0.6)],
    "B": [(0, 0, 0, 1), (0, 0, 0.7, 0), (0.7, 0, 0.8, 0.15), (0.8, 0.15, 0.8, 0.35),
          (0.8, 0.35, 0.7, 0.5), (0, 0.5, 0.7, 0.5), (0.7, 0.5, 0.8, 0.65),
          (0.8, 0.65, 0.8, 0.85), (0.8, 0.85, 0.7, 1), (0, 1, 0.7, 1)],
    "C": [(1, 0.1, 0.7, 0), (0.7, 0, 0.3, 0), (0.3, 0, 0, 0.3), (0, 0.3, 0, 0.7),
          (0, 0.7, 0.3, 1), (0.3, 1, 0.7, 1), (0.7, 1, 1, 0.9)],
    "D": [(0, 0, 0, 1), (0, 0, 0.6, 0), (0.6, 0, 0.9, 0.3), (0.9, 0.3, 0.9, 0.7),
          (0.9, 0.7, 0.6, 1), (0.6, 1, 0, 1)],
    "E": [(0, 0, 0, 1), (0, 0, 1, 0), (0, 0.5, 0.7, 0.5), (0, 1, 1, 1)],
    "F": [(0, 0, 0, 1), (0, 0, 1, 0), (0, 0.5, 0.7, 0.5)],
    "G": [(1, 0.1, 0.7, 0), (0.7, 0, 0.3, 0), (0.3, 0, 0, 0.3), (0, 0.3, 0, 0.7),
          (0, 0.7, 0.3, 1), (0.3, 1, 0.7, 1), (0.7, 1, 1, 0.7), (1, 0.7, 1, 0.5),
          (1, 0.5, 0.6, 0.5)],
    "H": [(0, 0, 0, 1), (1, 0, 1, 1), (0, 0.5, 1, 0.5)],
    "I": [(0.3, 0, 0.7, 0), (0.5, 0, 0.5, 1), (0.3, 1, 0.7, 1)],
    "J": [(0.3, 0, 0.8, 0), (0.6, 0, 0.6, 0.8), (0.6, 0.8, 0.4, 1), (0.4, 1, 0.1, 0.8)],
    "K": [(0, 0, 0, 1), (1, 0, 0, 0.5), (0, 0.5, 1, 1)],
    "L": [(0, 0, 0, 1), (0, 1, 1, 1)],
    "M": [(0, 1, 0, 0), (0, 0, 0.5, 0.5), (0.5, 0.5, 1, 0), (1, 0, 1, 1)],
    "N": [(0, 1, 0, 0), (0, 0, 1, 1), (1, 1, 1, 0)],
    "O": [(0.3, 0, 0.7, 0), (0.7, 0, 1, 0.3), (1, 0.3, 1, 0.7), (1, 0.7, 0.7, 1),
          (0.7, 1, 0.3, 1), (0.3, 1, 0, 0.7), (0, 0.7, 0, 0.3), (0, 0.3, 0.3, 0)],
    "P": [(0, 0, 0, 1), (0, 0, 0.7, 0), (0.7, 0, 0.9, 0.15), (0.9, 0.15, 0.9, 0.35),
          (0.9, 0.35, 0.7, 0.5), (0.7, 0.5, 0, 0.5)],
    "Q": [(0.3, 0, 0.7, 0), (0.7, 0, 1, 0.3), (1, 0.3, 1, 0.7), (1, 0.7, 0.7, 1),
          (0.7, 1, 0.3, 1), (0.3, 1, 0, 0.7), (0, 0.7, 0, 0.3), (0, 0.3, 0.3, 0),
          (0.7, 0.7, 1, 1)],
    "R": [(0, 0, 0, 1), (0, 0, 0.7, 0), (0.7, 0, 0.9, 0.15), (0.9, 0.15, 0.9, 0.35),
          (0.9, 0.35, 0.7, 0.5), (0.7, 0.5, 0, 0.5), (0.5, 0.5, 1, 1)],
    "S": [(1, 0.1, 0.7, 0), (0.7, 0, 0.3, 0), (0.3, 0, 0, 0.15), (0, 0.15, 0, 0.35),
          (0, 0.35, 0.3, 0.5), (0.3, 0.5, 0.7, 0.5), (0.7, 0.5, 1, 0.65),
          (1, 0.65, 1, 0.85), (1, 0.85, 0.7, 1), (0.7, 1, 0.3, 1), (0.3, 1, 0, 0.9)],
    "T": [(0, 0, 1, 0), (0.5, 0, 0.5, 1)],
    "U": [(0, 0, 0, 0.8), (0, 0.8, 0.3, 1), (0.3, 1, 0.7, 1), (0.7, 1, 1, 0.8),
          (1, 0.8, 1, 0)],
    "V": [(0, 0, 0.5, 1), (0.5, 1, 1, 0)],
    "W": [(0, 0, 0.25, 1), (0.25, 1, 0.5, 0.5), (0.5, 0.5, 0.75, 1), (0.75, 1, 1, 0)],
    "X": [(0, 0, 1, 1), (1, 0, 0, 1)],
    "Y": [(0, 0, 0.5, 0.5), (1, 0, 0.5, 0.5), (0.5, 0.5, 0.5, 1)],
    "Z": [(0, 0, 1, 0), (1, 0, 0, 1), (0, 1, 1, 1)],
    "0": [(0.3, 0, 0.7, 0), (0.7, 0, 1, 0.3), (1, 0.3, 1, 0.7), (1, 0.7, 0.7, 1),
          (0.7, 1, 0.3, 1), (0.3, 1, 0, 0.7), (0, 0.7, 0, 0.3), (0, 0.3, 0.3, 0)],
    "1": [(0.3, 0.2, 0.5, 0), (0.5, 0, 0.5, 1), (0.2, 1, 0.8, 1)],
    "2": [(0, 0.2, 0.3, 0), (0.3, 0, 0.7, 0), (0.7, 0, 1, 0.2), (1, 0.2, 1, 0.4),
          (1, 0.4, 0, 1), (0, 1, 1, 1)],
    "3": [(0, 0.1, 0.3, 0), (0.3, 0, 0.7, 0), (0.7, 0, 1, 0.2), (1, 0.2, 0.7, 0.5),
          (0.7, 0.5, 0.4, 0.5), (0.7, 0.5, 1, 0.8), (1, 0.8, 0.7, 1),
          (0.7, 1, 0.3, 1), (0.3, 1, 0, 0.9)],
    "4": [(0, 0, 0, 0.5), (0, 0.5, 1, 0.5), (0.7, 0, 0.7, 1)],
    "5": [(1, 0, 0, 0), (0, 0, 0, 0.5), (0, 0.5, 0.7, 0.5), (0.7, 0.5, 1, 0.7),
          (1, 0.7, 1, 0.85), (1, 0.85, 0.7, 1), (0.7, 1, 0.3, 1), (0.3, 1, 0, 0.9)],
    "6": [(0.7, 0, 0.3, 0), (0.3, 0, 0, 0.3), (0, 0.3, 0, 0.7), (0, 0.7, 0.3, 1),
          (0.3, 1, 0.7, 1), (0.7, 1, 1, 0.7), (1, 0.7, 0.7, 0.5), (0.7, 0.5, 0, 0.5)],
    "7": [(0, 0, 1, 0), (1, 0, 0.3, 1)],
    "8": [(0.3, 0, 0.7, 0), (0.7, 0, 1, 0.15), (1, 0.15, 1, 0.35), (1, 0.35, 0.7, 0.5),
          (0.3, 0.5, 0, 0.35), (0, 0.35, 0, 0.15), (0, 0.15, 0.3, 0),
          (0.3, 0.5, 0.7, 0.5), (0.7, 0.5, 1, 0.65), (1, 0.65, 1, 0.85),
          (1, 0.85, 0.7, 1), (0.7, 1, 0.3, 1), (0.3, 1, 0, 0.85),
          (0, 0.85, 0, 0.65), (0, 0.65, 0.3, 0.5)],
    "9": [(1, 0.5, 0.3, 0.5), (0.3, 0.5, 0, 0.3), (0, 0.3, 0.3, 0), (0.3, 0, 0.7, 0),
          (0.7, 0, 1, 0.3), (1, 0.3, 1, 0.7), (1, 0.7, 0.7, 1), (0.7, 1, 0.3, 1)],
    " ": [],
    ".": [(0.4, 0.9, 0.6, 0.9), (0.6, 0.9, 0.6, 1), (0.6, 1, 0.4, 1), (0.4, 1, 0.4, 0.9)],
    "-": [(0.2, 0.5, 0.8, 0.5)],
    "_": [(0, 1, 1, 1)],
    "*": [(0.2, 0.2, 0.8, 0.8), (0.8, 0.2, 0.2, 0.8), (0.5, 0.1, 0.5, 0.9)],
}


def _render_text_to_lines(
    text: str, x: float, y: float, font_size: float,
) -> list[tuple[float, float, float, float]]:
    """Render text to a list of line segments using the stroke font.

    Returns [(x1, y1, x2, y2), ...] in board coordinates.
    """
    result: list[tuple[float, float, float, float]] = []
    char_width = font_size * 0.7
    cursor_x = x

    for ch in text.upper():
        strokes = _FONT.get(ch)
        if strokes is None:
            cursor_x += char_width
            continue
        for x1, y1, x2, y2 in strokes:
            result.append((
                cursor_x + x1 * font_size * 0.6,
                y + y1 * font_size,
                cursor_x + x2 * font_size * 0.6,
                y + y2 * font_size,
            ))
        cursor_x += char_width

    return result


# Layer mapping to Gerber file extensions and attributes
LAYER_FILE_MAP = {
    Layer.F_CU: ("F_Cu.gbr", ".GTL", "Copper,L1,Top,Signal"),
    Layer.B_CU: ("B_Cu.gbr", ".GBL", "Copper,L2,Bot,Signal"),
    Layer.F_MASK: ("F_Mask.gbr", ".GTS", "Soldermask,Top"),
    Layer.B_MASK: ("B_Mask.gbr", ".GBS", "Soldermask,Bot"),
    Layer.F_SILK: ("F_SilkS.gbr", ".GTO", "Legend,Top"),
    Layer.B_SILK: ("B_SilkS.gbr", ".GBO", "Legend,Bot"),
    Layer.F_PASTE: ("F_Paste.gbr", ".GTP", "Paste,Top"),
    Layer.B_PASTE: ("B_Paste.gbr", ".GBP", "Paste,Bot"),
    Layer.EDGE_CUTS: ("Edge_Cuts.gbr", ".GKO", "Profile,NP"),
}


class GerberExporter:
    """Export board to Gerber RS-274X files (native implementation).

    Generates one file per layer with full RS-274X compliance.
    """

    def __init__(self, board: Board) -> None:
        self.board = board

    def export(self, output_dir: str | Path) -> list[str]:
        """Export all layers as Gerber files.

        Returns list of generated file paths.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        generated = []

        # Copper layers
        for layer in (Layer.F_CU, Layer.B_CU):
            path = output_dir / LAYER_FILE_MAP[layer][0]
            self._write_copper_layer(path, layer)
            generated.append(str(path))

        # Solder mask layers
        for layer in (Layer.F_MASK, Layer.B_MASK):
            path = output_dir / LAYER_FILE_MAP[layer][0]
            self._write_mask_layer(path, layer)
            generated.append(str(path))

        # Silkscreen layers
        for layer in (Layer.F_SILK, Layer.B_SILK):
            path = output_dir / LAYER_FILE_MAP[layer][0]
            self._write_silk_layer(path, layer)
            generated.append(str(path))

        # Paste layers
        for layer in (Layer.F_PASTE, Layer.B_PASTE):
            path = output_dir / LAYER_FILE_MAP[layer][0]
            self._write_paste_layer(path, layer)
            generated.append(str(path))

        # Board outline
        path = output_dir / LAYER_FILE_MAP[Layer.EDGE_CUTS][0]
        self._write_edge_cuts(path)
        generated.append(str(path))

        # Drill file
        drill_path = output_dir / "drill.drl"
        self._write_drill_file(drill_path)
        generated.append(str(drill_path))

        return generated

    def _write_copper_layer(self, path: Path, layer: Layer) -> None:
        """Write a copper layer Gerber file."""
        lines = self._gerber_header(layer)
        apertures: dict[str, int] = {}  # shape_key -> D-code
        next_dcode = 10

        board = self.board

        # Collect all pads on this layer
        for comp in board.components:
            for pad in comp.footprint.pads:
                if layer not in pad.layers:
                    continue

                abs_pos = pad.absolute_position(comp.position, comp.rotation)
                shape_key = f"{pad.shape.value}_{pad.size_x:.4f}x{pad.size_y:.4f}"

                if shape_key not in apertures:
                    dcode = next_dcode
                    next_dcode += 1
                    apertures[shape_key] = dcode

                    # Define aperture
                    if pad.shape == PadShape.CIRCLE:
                        lines.append(f"%ADD{dcode}C,{pad.size_x:.4f}*%")
                    elif pad.shape == PadShape.RECT:
                        lines.append(f"%ADD{dcode}R,{pad.size_x:.4f}X{pad.size_y:.4f}*%")
                    elif pad.shape == PadShape.OVAL:
                        lines.append(f"%ADD{dcode}O,{pad.size_x:.4f}X{pad.size_y:.4f}*%")
                    else:
                        lines.append(
                            f"%ADD{dcode}R,{pad.size_x:.4f}X{pad.size_y:.4f}*%"
                        )

                dcode = apertures[shape_key]
                lines.append(f"D{dcode}*")
                lines.append(
                    f"X{self._coord(abs_pos.x)}Y{self._coord(abs_pos.y)}D03*"
                )

        # Collect all trace segments on this layer
        trace_apertures: dict[float, int] = {}
        for seg in board.get_all_segments():
            if seg.layer != layer:
                continue

            if seg.width not in trace_apertures:
                dcode = next_dcode
                next_dcode += 1
                trace_apertures[seg.width] = dcode
                lines.append(f"%ADD{dcode}C,{seg.width:.4f}*%")

            dcode = trace_apertures[seg.width]
            lines.append(f"D{dcode}*")
            lines.append(
                f"X{self._coord(seg.start.x)}Y{self._coord(seg.start.y)}D02*"
            )
            lines.append(
                f"X{self._coord(seg.end.x)}Y{self._coord(seg.end.y)}D01*"
            )

        # Vias (appear on all copper layers)
        for via in board.get_all_vias():
            shape_key = f"via_{via.diameter:.4f}"
            if shape_key not in apertures:
                dcode = next_dcode
                next_dcode += 1
                apertures[shape_key] = dcode
                lines.append(f"%ADD{dcode}C,{via.diameter:.4f}*%")

            dcode = apertures[shape_key]
            lines.append(f"D{dcode}*")
            lines.append(
                f"X{self._coord(via.position.x)}Y{self._coord(via.position.y)}D03*"
            )

        # NOTE: Copper zones (pours) are NOT exported to Gerber.
        # Gerber is a "dumb" format with no clearance computation — a solid
        # polygon pour would short to every pad on the layer.  Copper zones
        # are exported only in KiCad format where the EDA tool computes
        # proper thermal relief and clearance fills.
        # GND connectivity in Gerber relies on routed traces instead.

        lines.append("M02*")
        path.write_text("\n".join(lines))

    def _write_mask_layer(self, path: Path, layer: Layer) -> None:
        """Write a solder mask layer (openings where mask is removed)."""
        is_top = layer == Layer.F_MASK
        copper_layer = Layer.F_CU if is_top else Layer.B_CU
        expansion = self.board.settings.design_rules.solder_mask_expansion

        lines = self._gerber_header(layer)
        apertures: dict[str, int] = {}
        next_dcode = 10

        for comp in self.board.components:
            for pad in comp.footprint.pads:
                if copper_layer not in pad.layers:
                    continue

                abs_pos = pad.absolute_position(comp.position, comp.rotation)
                sx = pad.size_x + 2 * expansion
                sy = pad.size_y + 2 * expansion
                shape_key = f"{pad.shape.value}_{sx:.4f}x{sy:.4f}"

                if shape_key not in apertures:
                    dcode = next_dcode
                    next_dcode += 1
                    apertures[shape_key] = dcode
                    if pad.shape == PadShape.CIRCLE:
                        lines.append(f"%ADD{dcode}C,{sx:.4f}*%")
                    else:
                        lines.append(f"%ADD{dcode}R,{sx:.4f}X{sy:.4f}*%")

                lines.append(f"D{apertures[shape_key]}*")
                lines.append(
                    f"X{self._coord(abs_pos.x)}Y{self._coord(abs_pos.y)}D03*"
                )

        # Via openings
        for via in self.board.get_all_vias():
            d = via.diameter + 2 * expansion
            shape_key = f"via_mask_{d:.4f}"
            if shape_key not in apertures:
                dcode = next_dcode
                next_dcode += 1
                apertures[shape_key] = dcode
                lines.append(f"%ADD{dcode}C,{d:.4f}*%")
            lines.append(f"D{apertures[shape_key]}*")
            lines.append(
                f"X{self._coord(via.position.x)}Y{self._coord(via.position.y)}D03*"
            )

        lines.append("M02*")
        path.write_text("\n".join(lines))

    def _write_silk_layer(self, path: Path, layer: Layer) -> None:
        """Write silkscreen layer."""
        is_top = layer == Layer.F_SILK
        lines = self._gerber_header(layer)
        next_dcode = 10

        # Silk line aperture
        lines.append(f"%ADD{next_dcode}C,0.1200*%")
        silk_dcode = next_dcode
        next_dcode += 1

        for comp in self.board.components:
            if not is_top:
                continue

            for silk_line in comp.footprint.silk_lines:
                start = silk_line.start.rotate(comp.rotation) + comp.position
                end = silk_line.end.rotate(comp.rotation) + comp.position

                lines.append(f"D{silk_dcode}*")
                lines.append(
                    f"X{self._coord(start.x)}Y{self._coord(start.y)}D02*"
                )
                lines.append(
                    f"X{self._coord(end.x)}Y{self._coord(end.y)}D01*"
                )

        # Board-level silk text (logos, labels)
        if is_top:
            for st in getattr(self.board, "silk_texts", []):
                text_lines = _render_text_to_lines(
                    st.text, st.position.x, st.position.y, st.font_size
                )
                for x1, y1, x2, y2 in text_lines:
                    lines.append(f"D{silk_dcode}*")
                    lines.append(
                        f"X{self._coord(x1)}Y{self._coord(y1)}D02*"
                    )
                    lines.append(
                        f"X{self._coord(x2)}Y{self._coord(y2)}D01*"
                    )

        lines.append("M02*")
        path.write_text("\n".join(lines))

    def _write_paste_layer(self, path: Path, layer: Layer) -> None:
        """Write solder paste layer (for stencil)."""
        is_top = layer == Layer.F_PASTE
        copper_layer = Layer.F_CU if is_top else Layer.B_CU
        shrink = self.board.settings.design_rules.paste_mask_shrink

        lines = self._gerber_header(layer)
        apertures: dict[str, int] = {}
        next_dcode = 10

        for comp in self.board.components:
            for pad in comp.footprint.pads:
                if not pad.is_smd or copper_layer not in pad.layers:
                    continue

                abs_pos = pad.absolute_position(comp.position, comp.rotation)
                sx = pad.size_x - 2 * shrink
                sy = pad.size_y - 2 * shrink
                if sx <= 0 or sy <= 0:
                    continue

                shape_key = f"{pad.shape.value}_{sx:.4f}x{sy:.4f}"
                if shape_key not in apertures:
                    dcode = next_dcode
                    next_dcode += 1
                    apertures[shape_key] = dcode
                    if pad.shape == PadShape.CIRCLE:
                        lines.append(f"%ADD{dcode}C,{sx:.4f}*%")
                    else:
                        lines.append(f"%ADD{dcode}R,{sx:.4f}X{sy:.4f}*%")

                lines.append(f"D{apertures[shape_key]}*")
                lines.append(
                    f"X{self._coord(abs_pos.x)}Y{self._coord(abs_pos.y)}D03*"
                )

        lines.append("M02*")
        path.write_text("\n".join(lines))

    def _write_edge_cuts(self, path: Path) -> None:
        """Write board outline Gerber."""
        lines = self._gerber_header(Layer.EDGE_CUTS)

        # Outline aperture (0.05mm line)
        lines.append("%ADD10C,0.0500*%")
        lines.append("D10*")

        corners = self.board.board_outline_points()
        if corners:
            lines.append(
                f"X{self._coord(corners[0].x)}Y{self._coord(corners[0].y)}D02*"
            )
            for pt in corners[1:]:
                lines.append(f"X{self._coord(pt.x)}Y{self._coord(pt.y)}D01*")
            lines.append(
                f"X{self._coord(corners[0].x)}Y{self._coord(corners[0].y)}D01*"
            )

        lines.append("M02*")
        path.write_text("\n".join(lines))

    def _write_drill_file(self, path: Path) -> None:
        """Write Excellon drill file."""
        lines = [
            "M48",
            ";DRILL file generated by AI-PCB-Designer",
            ";FORMAT={-:-/ absolute / metric / decimal}",
            "FMAT,2",
            "METRIC,TZ",
        ]

        # Collect all drill sizes
        drills: dict[float, list[Point]] = {}

        # Via drills
        for via in self.board.get_all_vias():
            drills.setdefault(via.drill, []).append(via.position)

        # THT pad drills
        for comp in self.board.components:
            for pad in comp.footprint.pads:
                if pad.drill_size > 0:
                    abs_pos = pad.absolute_position(comp.position, comp.rotation)
                    drills.setdefault(pad.drill_size, []).append(abs_pos)

        # Define tools
        tool_num = 1
        tool_map: dict[float, int] = {}
        for drill_size in sorted(drills.keys()):
            tool_map[drill_size] = tool_num
            lines.append(f"T{tool_num:02d}C{drill_size:.4f}")
            tool_num += 1

        lines.append("%")

        # Drill hits
        for drill_size in sorted(drills.keys()):
            tool = tool_map[drill_size]
            lines.append(f"T{tool:02d}")
            for pos in drills[drill_size]:
                lines.append(f"X{pos.x:.4f}Y{pos.y:.4f}")

        lines.append("T0")
        lines.append("M30")
        path.write_text("\n".join(lines))

    def _gerber_header(self, layer: Layer) -> list[str]:
        """Generate Gerber file header with X2 attributes."""
        _, _, attr = LAYER_FILE_MAP[layer]
        return [
            "G04 Generated by AI-PCB-Designer*",
            f"G04 Board: {self.board.name}*",
            "%MOMM*%",          # Millimeters
            "%FSLAX46Y46*%",    # Format: leading zeros omitted, 4.6 decimal
            f"%TF.FileFunction,{attr}*%",
            "%TF.GenerationSoftware,AI-PCB-Designer,0.1.0*%",
            "%IPPOS*%",
            "%LPD*%",
        ]

    @staticmethod
    def _coord(value_mm: float) -> str:
        """Convert mm to Gerber coordinate (4.6 format, integer)."""
        return str(int(round(value_mm * 1000000)))
