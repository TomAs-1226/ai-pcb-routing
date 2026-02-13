"""Bill of Materials (BOM) and Pick-and-Place file exporters.

Generates manufacturing-ready CSV files:
- BOM: Component list with quantities, values, footprints, and MPNs
- Pick-and-Place (CPL): Component placement coordinates for SMT assembly
"""

from __future__ import annotations

import csv
from pathlib import Path
from dataclasses import dataclass

from ..core.board import Board
from ..core.component import Component
from ..core.datatypes import ComponentSide, PadType


@dataclass
class BOMEntry:
    """A single BOM line item (may group identical components)."""
    references: list[str]
    value: str
    footprint: str
    quantity: int
    manufacturer: str = ""
    mpn: str = ""
    description: str = ""


class BOMExporter:
    """Generate Bill of Materials CSV."""

    def __init__(self, board: Board) -> None:
        self.board = board

    def export(self, output_path: str | Path) -> str:
        """Export BOM as CSV file. Returns file path."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        entries = self._group_components()

        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Reference",
                "Value",
                "Footprint",
                "Quantity",
                "Manufacturer",
                "MPN",
                "Description",
            ])

            for entry in entries:
                writer.writerow([
                    ", ".join(sorted(entry.references)),
                    entry.value,
                    entry.footprint,
                    entry.quantity,
                    entry.manufacturer,
                    entry.mpn,
                    entry.description,
                ])

        return str(output_path)

    def _group_components(self) -> list[BOMEntry]:
        """Group identical components into single BOM entries."""
        groups: dict[str, BOMEntry] = {}

        for comp in self.board.components:
            # Skip mounting holes and other non-BOM items
            if comp.reference.startswith("H") and "Mount" in comp.value:
                continue

            key = f"{comp.value}|{comp.footprint.name}|{comp.mpn}"

            if key not in groups:
                groups[key] = BOMEntry(
                    references=[],
                    value=comp.value,
                    footprint=comp.footprint.name,
                    quantity=0,
                    manufacturer=comp.manufacturer,
                    mpn=comp.mpn,
                    description=comp.description,
                )

            groups[key].references.append(comp.reference)
            groups[key].quantity += 1

        return sorted(groups.values(), key=lambda e: e.references[0])

    def export_jlcpcb_bom(self, output_path: str | Path) -> str:
        """Export BOM in JLCPCB format.

        JLCPCB requires columns: Comment, Designator, Footprint, LCSC Part #
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        entries = self._group_components()

        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])

            for entry in entries:
                writer.writerow([
                    entry.value,
                    ", ".join(sorted(entry.references)),
                    entry.footprint,
                    entry.mpn,  # Would be LCSC part number if available
                ])

        return str(output_path)


class PickAndPlaceExporter:
    """Generate Pick-and-Place / Component Placement List (CPL) CSV."""

    def __init__(self, board: Board) -> None:
        self.board = board

    def export(self, output_path: str | Path) -> str:
        """Export pick-and-place file as CSV. Returns file path."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Designator",
                "Mid X (mm)",
                "Mid Y (mm)",
                "Layer",
                "Rotation",
                "Value",
                "Footprint",
            ])

            for comp in self.board.components:
                # Only SMD components need pick-and-place
                has_smd = any(p.is_smd for p in comp.footprint.pads)
                if not has_smd:
                    continue

                # Skip mounting holes
                if comp.reference.startswith("H"):
                    continue

                layer = "Top" if comp.side == ComponentSide.TOP else "Bottom"

                writer.writerow([
                    comp.reference,
                    f"{comp.position.x:.4f}",
                    f"{comp.position.y:.4f}",
                    layer,
                    f"{comp.rotation:.1f}",
                    comp.value,
                    comp.footprint.name,
                ])

        return str(output_path)

    def export_jlcpcb_cpl(self, output_path: str | Path) -> str:
        """Export CPL in JLCPCB format.

        JLCPCB requires columns: Designator, Mid X, Mid Y, Layer, Rotation
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Designator",
                "Mid X",
                "Mid Y",
                "Layer",
                "Rotation",
            ])

            for comp in self.board.components:
                has_smd = any(p.is_smd for p in comp.footprint.pads)
                if not has_smd:
                    continue
                if comp.reference.startswith("H"):
                    continue

                layer = "Top" if comp.side == ComponentSide.TOP else "Bottom"

                writer.writerow([
                    comp.reference,
                    f"{comp.position.x:.4f}mm",
                    f"{comp.position.y:.4f}mm",
                    layer,
                    f"{comp.rotation:.1f}",
                ])

        return str(output_path)
