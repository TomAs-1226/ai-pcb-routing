# AI PCB Designer

Fully autonomous, AI-powered PCB design tool that creates manufacturing-ready circuit boards from natural language descriptions. Designed for people with **zero PCB experience**.

## What It Does

You describe what you want in plain English, and the AI designs the entire board:

```
"Make me a carrier board for an ESP32 with USB-C, power LED, and GPIO breakout headers"
```

The tool autonomously:
1. **Selects components** (MCU, regulators, capacitors, connectors)
2. **Creates the schematic** (netlist with all electrical connections)
3. **Places components** on the board (force-directed autoplacement)
4. **Routes all traces** (A* grid-based autorouter)
5. **Runs Design Rule Checks** (validates manufacturability)
6. **Generates output files** ready to send to a PCB manufacturer

All steps are visualized in real-time in the GUI.

## Output Files

| File | Format | Purpose |
|------|--------|---------|
| Gerber files | RS-274X / X2 | PCB fabrication (copper, mask, silk, paste, outline) |
| Drill file | Excellon | Drill holes and vias |
| BOM | CSV | Bill of Materials with MPNs and quantities |
| Pick-and-Place | CSV | Component placement for SMT assembly |
| KiCad PCB | .kicad_pcb | Open in KiCad for verification/editing |
| JLCPCB BOM/CPL | CSV | Ready to upload to JLCPCB for assembly |

## Phase 1 Templates

| Template | Description |
|----------|-------------|
| `esp32_carrier` | ESP32-WROOM-32 carrier board with USB-C, 3.3V regulator, buttons, LED, GPIO breakout |
| `led_blinker` | Simple LED + resistor circuit (beginner project) |
| `sensor_breakout` | I2C sensor breakout with pull-ups and decoupling |

## Installation

### Requirements
- Python 3.10+
- PySide6 (Qt6) for the GUI
- numpy, shapely for geometry

### Easiest Way (macOS / Linux)

```bash
chmod +x run.sh
./run.sh
```

The launcher auto-detects the right Python, installs dependencies if needed, and starts the app.

### Easiest Way (Windows)

```cmd
run.bat
```

### Manual Install

**Important on macOS**: If you have multiple Python versions, make sure to use the same one for installing and running:

```bash
# Check which python you're using
python3 --version

# Install deps with THAT python
python3 -m pip install PySide6 numpy shapely

# Run with THAT python
PYTHONPATH=src python3 -m ai_pcb_designer
```

Or install as an editable package:

```bash
pip install -e ".[dev]"
python -m ai_pcb_designer
```

### Quick Start - GUI Mode

```bash
./run.sh                    # macOS/Linux
run.bat                     # Windows
```

### Quick Start - CLI Mode (no GUI needed)

```bash
# Design using a template
PYTHONPATH=src python3 -m ai_pcb_designer --cli --template esp32_carrier

# Design from description
PYTHONPATH=src python3 -m ai_pcb_designer --cli "Make me an ESP32 dev board with USB and LEDs"

# List available templates
PYTHONPATH=src python3 -m ai_pcb_designer --list-templates

# Specify output directory
PYTHONPATH=src python3 -m ai_pcb_designer --cli --template led_blinker --output ./my_board
```

### With LLM (Optional)

For AI-generated designs beyond built-in templates:

```bash
# OpenAI
python -m ai_pcb_designer --llm openai --api-key sk-...

# Anthropic
python -m ai_pcb_designer --llm anthropic --api-key sk-ant-...
```

## Architecture

```
src/ai_pcb_designer/
├── core/           # Data model: Board, Component, Net, Trace, Pad
├── components/     # Footprint library, board templates, parts database
├── engines/        # Schematic generator, autoplacer, autorouter, DRC
├── ai/             # AI agent orchestrator (autonomous pipeline)
├── exporters/      # Gerber, BOM, pick-and-place, KiCad exporters
├── gui/            # PySide6 GUI with real-time PCB renderer
└── main.py         # Entry point (GUI + CLI)
```

### Design Pipeline

```
User Description
       |
       v
+-------------+
|  AI Agent   | -- Analyzes request, selects template/components
+------+------+
       |
       v
+-------------+
|  Schematic  | -- Creates netlist (components + connections)
|   Engine    |
+------+------+
       |
       v
+-------------+
|  Autoplacer | -- Force-directed component placement
+------+------+
       |
       v
+-------------+
|  Autorouter | -- A* grid-based trace routing
+------+------+
       |
       v
+-------------+
|     DRC     | -- Design Rule Check (iterate if fails)
+------+------+
       |
       v
+-------------+
|  Exporters  | -- Gerber, BOM, PnP, KiCad output
+-------------+
```

### Component Database

The built-in database includes common components with real LCSC part numbers. Online mode searches the LCSC/JLCPCB parts API for access to millions of components.

## Cross-Platform

- **Windows**: Full GUI with PySide6/Qt6
- **macOS**: Full GUI with PySide6/Qt6
- **Linux**: Full GUI with PySide6/Qt6
- **Headless**: CLI mode works without display

## Running Tests

```bash
python tests/test_core.py
python tests/test_pipeline.py
```

## License

MIT
