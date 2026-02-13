"""KiCad .kicad_pcb file exporter.

Generates KiCad-compatible PCB files that can be opened in KiCad
for verification, editing, or further design work.

This is a direct S-expression writer (no kiutils dependency required).
"""

from __future__ import annotations

from pathlib import Path
from textwrap import indent

from ..core.board import Board
from ..core.component import Component
from ..core.datatypes import Layer, PadShape, PadType, Point
from ..core.trace import CopperZone, TraceSegment, Via


class KiCadExporter:
    """Export board to KiCad .kicad_pcb format."""

    def __init__(self, board: Board) -> None:
        self.board = board

    def export(self, output_path: str | Path) -> str:
        """Export board as .kicad_pcb file. Returns file path."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        content = self._generate()
        output_path.write_text(content)
        return str(output_path)

    def _generate(self) -> str:
        """Generate the full .kicad_pcb S-expression content."""
        board = self.board
        parts = []

        parts.append(self._header())
        parts.append(self._layers())
        parts.append(self._setup())
        parts.append(self._nets())

        for comp in board.components:
            parts.append(self._footprint(comp))

        for seg in board.get_all_segments():
            parts.append(self._segment(seg))

        for via in board.get_all_vias():
            parts.append(self._via(via))

        for zone in board.zones:
            parts.append(self._zone(zone))

        # Board outline
        parts.append(self._board_outline())

        return f"(kicad_pcb\n{chr(10).join(parts)}\n)\n"

    def _header(self) -> str:
        return (
            '  (version 20221018)\n'
            '  (generator "ai-pcb-designer")\n'
            '  (generator_version "0.1.0")\n'
            f'  (general\n'
            f'    (thickness {self.board.settings.design_rules.board_thickness})\n'
            f'  )'
        )

    def _layers(self) -> str:
        return (
            '  (layers\n'
            '    (0 "F.Cu" signal)\n'
            '    (31 "B.Cu" signal)\n'
            '    (32 "B.Adhes" user "B.Adhesive")\n'
            '    (33 "F.Adhes" user "F.Adhesive")\n'
            '    (34 "B.Paste" user)\n'
            '    (35 "F.Paste" user)\n'
            '    (36 "B.SilkS" user "B.Silkscreen")\n'
            '    (37 "F.SilkS" user "F.Silkscreen")\n'
            '    (38 "B.Mask" user)\n'
            '    (39 "F.Mask" user)\n'
            '    (44 "Edge.Cuts" user)\n'
            '    (46 "B.CrtYd" user "B.Courtyard")\n'
            '    (47 "F.CrtYd" user "F.Courtyard")\n'
            '    (48 "B.Fab" user)\n'
            '    (49 "F.Fab" user)\n'
            '  )'
        )

    def _setup(self) -> str:
        rules = self.board.settings.design_rules
        return (
            '  (setup\n'
            '    (pad_to_mask_clearance {mask})\n'
            '    (pcbplotparams\n'
            '      (layerselection 0x00010fc_ffffffff)\n'
            '      (outputformat 1)\n'
            '    )\n'
            '  )'
        ).format(mask=rules.solder_mask_expansion)

    def _nets(self) -> str:
        lines = ['  (net 0 "")']
        for net in self.board.nets:
            name_escaped = net.name.replace('"', '\\"')
            lines.append(f'  (net {net.id} "{name_escaped}")')
        return "\n".join(lines)

    def _footprint(self, comp: Component) -> str:
        """Generate footprint S-expression for a placed component."""
        fp = comp.footprint
        layer = "F.Cu" if comp.side.name == "TOP" else "B.Cu"
        name = fp.name.replace('"', '\\"')

        parts = []
        parts.append(
            f'  (footprint "{name}"\n'
            f'    (layer "{layer}")\n'
            f'    (at {comp.position.x:.4f} {comp.position.y:.4f}'
            f'{f" {comp.rotation}" if comp.rotation else ""})\n'
            f'    (property "Reference" "{comp.reference}" (at 0 -2 0) '
            f'(layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))\n'
            f'    (property "Value" "{comp.value}" (at 0 2 0) '
            f'(layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))'
        )

        # Pads
        for pad in fp.pads:
            pad_type = "smd" if pad.is_smd else "thru_hole"
            shape = pad.shape.value
            layers_str = " ".join(f'"{l.value}"' for l in pad.layers)

            pad_line = (
                f'    (pad "{pad.number}" {pad_type} {shape} '
                f'(at {pad.position.x:.4f} {pad.position.y:.4f}) '
                f'(size {pad.size_x:.4f} {pad.size_y:.4f})'
            )

            if pad.drill_size > 0:
                pad_line += f" (drill {pad.drill_size:.4f})"

            pad_line += f" (layers {layers_str})"

            if pad.net_id:
                net_name = pad.net_name.replace('"', '\\"')
                pad_line += f' (net {pad.net_id} "{net_name}")'

            pad_line += ")"
            parts.append(pad_line)

        # Silkscreen lines
        for silk in fp.silk_lines:
            parts.append(
                f'    (fp_line (start {silk.start.x:.4f} {silk.start.y:.4f}) '
                f'(end {silk.end.x:.4f} {silk.end.y:.4f}) '
                f'(layer "F.SilkS") (width {silk.width:.4f}))'
            )

        # Courtyard
        if fp.courtyard:
            r = fp.courtyard.rect
            parts.append(
                f'    (fp_rect (start {r.x:.4f} {r.y:.4f}) '
                f'(end {r.x + r.width:.4f} {r.y + r.height:.4f}) '
                f'(layer "{fp.courtyard.layer.value}") (width 0.05))'
            )

        parts.append("  )")
        return "\n".join(parts)

    def _segment(self, seg: TraceSegment) -> str:
        layer = seg.layer.value
        net = self.board.get_net_by_id(seg.net_id)
        net_id = seg.net_id if net else 0
        return (
            f'  (segment (start {seg.start.x:.4f} {seg.start.y:.4f}) '
            f'(end {seg.end.x:.4f} {seg.end.y:.4f}) '
            f'(width {seg.width:.4f}) (layer "{layer}") (net {net_id}))'
        )

    def _via(self, via: Via) -> str:
        return (
            f'  (via (at {via.position.x:.4f} {via.position.y:.4f}) '
            f'(size {via.diameter:.4f}) (drill {via.drill:.4f}) '
            f'(layers "F.Cu" "B.Cu") (net {via.net_id}))'
        )

    def _zone(self, zone: CopperZone) -> str:
        """Generate zone S-expression."""
        net = self.board.get_net_by_id(zone.net_id)
        net_name = net.name if net else ""
        layer = zone.layer.value
        points = " ".join(f"(xy {p.x:.4f} {p.y:.4f})" for p in zone.outline)
        return (
            f'  (zone (net {zone.net_id}) (net_name "{net_name}") (layer "{layer}")\n'
            f'    (fill yes (thermal_gap 0.508) (thermal_bridge_width 0.508))\n'
            f'    (connect_pads (clearance {zone.clearance:.4f}))\n'
            f'    (polygon (pts {points}))\n'
            f'  )'
        )

    def _board_outline(self) -> str:
        """Generate board edge cuts."""
        corners = self.board.board_outline_points()
        lines = []
        for i in range(len(corners)):
            start = corners[i]
            end = corners[(i + 1) % len(corners)]
            lines.append(
                f'  (gr_line (start {start.x:.4f} {start.y:.4f}) '
                f'(end {end.x:.4f} {end.y:.4f}) '
                f'(layer "Edge.Cuts") (width 0.05))'
            )
        return "\n".join(lines)
