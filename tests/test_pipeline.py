"""Integration tests for the full design pipeline."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_pcb_designer.components.templates import create_board_from_template, list_templates
from ai_pcb_designer.components.footprints import get_footprint, list_footprints
from ai_pcb_designer.components.database import ComponentDatabase
from ai_pcb_designer.engines.placer import PlacementEngine, PlacementConfig
from ai_pcb_designer.engines.router import AutoRouter, RouterConfig
from ai_pcb_designer.engines.drc import DRCEngine
from ai_pcb_designer.exporters.gerber import GerberExporter
from ai_pcb_designer.exporters.bom import BOMExporter, PickAndPlaceExporter
from ai_pcb_designer.exporters.kicad import KiCadExporter


def test_list_templates():
    templates = list_templates()
    assert len(templates) >= 3
    names = [t["name"] for t in templates]
    assert any("esp32" in n.lower() for n in names)


def test_list_footprints():
    fps = list_footprints()
    assert len(fps) >= 10
    assert "ESP32-WROOM-32" in fps
    assert "R_0603" in fps


def test_get_footprint():
    fp = get_footprint("R_0603")
    assert fp is not None
    assert len(fp.pads) == 2
    assert fp.pads[0].number == "1"


def test_esp32_footprint():
    fp = get_footprint("ESP32-WROOM-32")
    assert fp is not None
    assert len(fp.pads) == 39  # 38 signal + 1 GND pad


def test_create_led_blinker():
    board = create_board_from_template("led_blinker")
    assert board.name == "LED Blinker Board"
    assert len(board.components) == 3
    assert len(board.nets) == 3


def test_create_esp32_carrier():
    board = create_board_from_template("esp32_carrier")
    assert "ESP32" in board.name
    assert len(board.components) > 10
    assert len(board.nets) > 5


def test_placement_led_blinker():
    board = create_board_from_template("led_blinker")
    placer = PlacementEngine(PlacementConfig(max_iterations=50, seed=42))
    steps = placer.place(board)
    assert len(steps) > 0

    # All components should be within board bounds
    for comp in board.components:
        assert 0 <= comp.position.x <= board.settings.width
        assert 0 <= comp.position.y <= board.settings.height


def test_router_led_blinker():
    board = create_board_from_template("led_blinker")

    # Place first
    placer = PlacementEngine(PlacementConfig(max_iterations=50, seed=42))
    placer.place(board)

    # Route
    router = AutoRouter(RouterConfig(grid_resolution=0.5))
    all_routed, steps = router.route(board)
    assert len(steps) > 0
    # May or may not route everything, but should produce some traces


def test_drc_led_blinker():
    board = create_board_from_template("led_blinker")
    placer = PlacementEngine(PlacementConfig(max_iterations=50, seed=42))
    placer.place(board)

    drc = DRCEngine()
    result = drc.check(board)
    # DRC should return a result object
    assert result is not None
    assert isinstance(result.error_count, int)


def test_gerber_export():
    board = create_board_from_template("led_blinker")
    placer = PlacementEngine(PlacementConfig(max_iterations=50, seed=42))
    placer.place(board)

    with tempfile.TemporaryDirectory() as tmpdir:
        exporter = GerberExporter(board)
        files = exporter.export(tmpdir)
        assert len(files) > 0

        # Check files exist and have content
        for f in files:
            p = Path(f)
            assert p.exists()
            assert p.stat().st_size > 0


def test_bom_export():
    board = create_board_from_template("led_blinker")

    with tempfile.TemporaryDirectory() as tmpdir:
        bom_path = Path(tmpdir) / "bom.csv"
        BOMExporter(board).export(bom_path)
        assert bom_path.exists()

        content = bom_path.read_text()
        assert "Reference" in content
        assert "R1" in content


def test_pnp_export():
    board = create_board_from_template("led_blinker")
    placer = PlacementEngine(PlacementConfig(max_iterations=50, seed=42))
    placer.place(board)

    with tempfile.TemporaryDirectory() as tmpdir:
        pnp_path = Path(tmpdir) / "pnp.csv"
        PickAndPlaceExporter(board).export(pnp_path)
        assert pnp_path.exists()


def test_kicad_export():
    board = create_board_from_template("led_blinker")
    placer = PlacementEngine(PlacementConfig(max_iterations=50, seed=42))
    placer.place(board)

    with tempfile.TemporaryDirectory() as tmpdir:
        kicad_path = Path(tmpdir) / "test.kicad_pcb"
        KiCadExporter(board).export(kicad_path)
        assert kicad_path.exists()

        content = kicad_path.read_text()
        assert "(kicad_pcb" in content
        assert "F.Cu" in content


def test_component_database_builtin():
    db = ComponentDatabase()
    results = db.search("10k")
    assert len(results) > 0
    assert any("10k" in r.value for r in results)


def test_component_database_search_resistor():
    db = ComponentDatabase()
    results = db.search("resistor")
    assert len(results) > 0


if __name__ == "__main__":
    test_list_templates()
    test_list_footprints()
    test_get_footprint()
    test_esp32_footprint()
    test_create_led_blinker()
    test_create_esp32_carrier()
    test_placement_led_blinker()
    test_router_led_blinker()
    test_drc_led_blinker()
    test_gerber_export()
    test_bom_export()
    test_pnp_export()
    test_kicad_export()
    test_component_database_builtin()
    test_component_database_search_resistor()
    print("All pipeline tests passed!")
