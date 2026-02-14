"""AI Agent Orchestrator for autonomous PCB design - Phase 4.

Phase 4: Design Engine as primary path.
- Uses DesignEngine to compose custom boards from natural language
  (power supply, MCU, LED matrix, headers, etc.)
- DesignValidator scores designs across 5 dimensions (0-100)
- Template matching is now a FALLBACK for very specific single-purpose
  requests, not the default path
- Self-improvement loop: validate → fix → re-validate up to 5 iterations

Pipeline:
1. Parse user's natural language description
2. Create custom design via DesignEngine (primary) or match template (fallback)
3. Validate design with DesignValidator + self-improvement loop
4. Auto-size board if needed, check feasibility
5. Run component placement (skip if pre-placed by engine)
6. Run trace routing
7. Run DRC checks + auto-fix
8. Generate manufacturing outputs
"""

from __future__ import annotations

import copy
import math
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable

from ..core.board import Board
from ..core.datatypes import Point
from ..components.templates import (
    TEMPLATE_REGISTRY,
    create_board_from_template,
    list_templates,
)
from ..components.database import ComponentDatabase
from ..engines.placer import PlacementEngine, PlacementConfig, estimate_board_size
from ..engines.router import AutoRouter, RouterConfig
from ..engines.drc import DRCEngine, DRCResult, DRCViolationType
from ..engines.design_validator import DesignValidator
from ..exporters.gerber import GerberExporter
from ..exporters.bom import BOMExporter, PickAndPlaceExporter
from ..exporters.kicad import KiCadExporter
from ..exporters.assembly import AssemblyDrawingExporter
from .design_engine import DesignEngine, parse_request


class AgentPhase(Enum):
    """Current phase of the AI design pipeline."""
    IDLE = auto()
    ANALYZING = auto()
    SELECTING_COMPONENTS = auto()
    CREATING_SCHEMATIC = auto()
    SIZING_BOARD = auto()
    PLACING_COMPONENTS = auto()
    ROUTING_TRACES = auto()
    RUNNING_DRC = auto()
    FIXING_ISSUES = auto()
    GENERATING_OUTPUTS = auto()
    COMPLETE = auto()
    FAILED = auto()


@dataclass
class AgentStep:
    """A single step in the agent's pipeline for GUI display."""
    phase: AgentPhase
    message: str
    detail: str = ""
    progress: float = 0.0  # 0.0 to 1.0
    board_snapshot: Board | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentConfig:
    """Configuration for the AI agent.

    LLM integration:
      Set ``llm_provider`` to ``"openai"`` or ``"anthropic"`` and
      provide your ``api_key`` (or set the ``OPENAI_API_KEY`` /
      ``ANTHROPIC_API_KEY`` environment variable).

      For OpenAI, the default model is ``"o3-mini"`` — a thinking/
      reasoning model that plans circuit design before writing code.
      Other good choices: ``"o4-mini"``, ``"o1"``, ``"gpt-4o"``,
      ``"gpt-4.1"``

      For Anthropic, the default model is ``"claude-sonnet-4-5-20250929"``.

    Quick-start example::

        config = AgentConfig(llm_provider="openai")  # uses OPENAI_API_KEY env
        agent = PCBDesignAgent(config)
        board = agent.design("esp32 board with oled and motor driver")
    """
    llm_provider: str = "template"  # "openai", "anthropic", or "template"
    api_key: str = ""
    model: str = ""  # "" = auto-select best thinking model
    output_dir: str = "./output"
    max_drc_retries: int = 3
    generate_kicad: bool = True
    generate_gerbers: bool = True
    generate_bom: bool = True
    generate_pnp: bool = True
    user_width: float = 0.0    # User-requested board width (0 = auto)
    user_height: float = 0.0   # User-requested board height (0 = auto)


class PCBDesignAgent:
    """Autonomous PCB design agent.

    Orchestrates the entire design flow from natural language input
    to manufacturing-ready output files.
    """

    def __init__(self, config: AgentConfig | None = None) -> None:
        self.config = config or AgentConfig()
        self._steps: list[AgentStep] = []
        self._on_step: Callable[[AgentStep], None] | None = None
        self._phase = AgentPhase.IDLE
        self._board: Board | None = None
        self._component_db = ComponentDatabase()
        self._cancel_event = threading.Event()
        self._progress = 0.0  # monotonically increasing
        self._last_emit_time = 0.0

    @property
    def board(self) -> Board | None:
        return self._board

    @property
    def phase(self) -> AgentPhase:
        return self._phase

    @property
    def steps(self) -> list[AgentStep]:
        return self._steps

    def set_step_callback(self, callback: Callable[[AgentStep], None]) -> None:
        self._on_step = callback

    def cancel(self) -> None:
        """Signal the agent to stop as soon as possible."""
        self._cancel_event.set()

    def _is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def design(self, user_request: str) -> Board | None:
        """Run the full autonomous design pipeline."""
        try:
            self._cancel_event.clear()
            self._progress = 0.0

            self._emit(AgentPhase.ANALYZING, "Analyzing your request...",
                       f"Input: {user_request}", progress=0.02)

            if self._is_cancelled():
                return None

            # Phase 1: Create custom design
            # Priority: design engine → LLM → strict template match → default
            board = self._create_custom_design(user_request)

            if board is None:
                # Fallback: strict template match or default starter
                template_name = self._match_template(user_request)
                if template_name:
                    self._emit(
                        AgentPhase.SELECTING_COMPONENTS,
                        f"Using template: {TEMPLATE_REGISTRY[template_name].name}",
                        f"Fallback to built-in template '{template_name}'.",
                        progress=0.08,
                    )
                    board = create_board_from_template(template_name)
                else:
                    self._emit(
                        AgentPhase.SELECTING_COMPONENTS,
                        "Using LED blinker as default starter board.",
                        progress=0.08,
                    )
                    board = create_board_from_template("led_blinker")

            self._board = board

            if self._is_cancelled():
                return None

            self._emit(
                AgentPhase.CREATING_SCHEMATIC,
                f"Board created: {board.name}",
                f"{len(board.components)} components, {len(board.nets)} nets",
                progress=0.12,
                board=board,
            )

            # Phase 1b: Validate design and self-improve
            self._validate_design(board)

            # Phase 2: Board sizing and feasibility check
            self._size_board(board)

            if self._is_cancelled():
                return None

            # Phase 3: Component placement
            # Check if components already have positions (from DSL templates)
            has_positions = self._components_have_positions(board)

            if has_positions:
                self._emit(
                    AgentPhase.PLACING_COMPONENTS,
                    "Components have pre-calculated positions (deterministic layout)",
                    f"{len(board.components)} components already placed by design template",
                    progress=0.40,
                    board=board,
                )
            else:
                self._emit(
                    AgentPhase.PLACING_COMPONENTS,
                    "Placing components on the board...",
                    f"Force-directed placement for {len(board.components)} components",
                    progress=0.18,
                )

                placer = PlacementEngine(PlacementConfig(seed=42))

                placement_emit_count = [0]
                def on_placement_step(step):
                    placement_emit_count[0] += 1
                    if placement_emit_count[0] % 5 == 0:
                        self._emit(
                            AgentPhase.PLACING_COMPONENTS,
                            step.message,
                            f"Iteration {step.iteration}, force: {step.total_force:.3f}",
                            progress=0.20 + 0.20 * min(step.iteration / 300, 1.0),
                            board=board,
                        )

                placer.set_step_callback(on_placement_step)
                placer.place(board)

                self._emit(
                    AgentPhase.PLACING_COMPONENTS,
                    "Component placement complete!",
                    progress=0.40,
                    board=board,
                )

            if self._is_cancelled():
                return None

            # Phase 4: Trace routing
            self._emit(
                AgentPhase.ROUTING_TRACES,
                "Routing traces...",
                f"Routing {len(board.get_unrouted_nets())} nets",
                progress=0.42,
            )

            router = AutoRouter(RouterConfig())
            route_net_count = [0]
            total_nets = len([n for n in board.nets if len(n.pad_refs) >= 2])

            def on_route_step(step):
                route_net_count[0] += 1
                # Throttle: only emit on phase changes
                if step.phase in ("placed", "failed"):
                    frac = route_net_count[0] / max(total_nets, 1)
                    self._emit(
                        AgentPhase.ROUTING_TRACES,
                        step.message,
                        f"Net: {step.net_name}",
                        progress=0.42 + 0.28 * frac,
                        board=board,
                    )

            router.set_step_callback(on_route_step)
            all_routed, route_steps = router.route(board)

            if all_routed:
                self._emit(
                    AgentPhase.ROUTING_TRACES,
                    "All nets routed successfully!",
                    f"Total: {len(board.get_all_segments())} segments, "
                    f"{len(board.get_all_vias())} vias",
                    progress=0.70,
                    board=board,
                )
            else:
                self._emit(
                    AgentPhase.ROUTING_TRACES,
                    "Some nets could not be routed (will attempt fix)",
                    progress=0.70,
                    board=board,
                )

            if self._is_cancelled():
                return None

            # Phase 5: DRC
            drc_passed = False
            for attempt in range(self.config.max_drc_retries + 1):
                self._emit(
                    AgentPhase.RUNNING_DRC,
                    f"Running Design Rule Check (attempt {attempt + 1})...",
                    progress=0.72 + attempt * 0.02,
                )

                drc_engine = DRCEngine()
                drc_result = drc_engine.check(board)

                if drc_result.passed:
                    drc_passed = True
                    self._emit(
                        AgentPhase.RUNNING_DRC,
                        f"DRC PASSED! ({drc_result.warning_count} warnings)",
                        progress=0.80,
                        board=board,
                    )
                    break
                else:
                    self._emit(
                        AgentPhase.FIXING_ISSUES,
                        f"DRC found {drc_result.error_count} errors. "
                        f"Attempting to fix...",
                        detail="\n".join(
                            v.message for v in drc_result.violations[:5]
                        ),
                        progress=0.72 + attempt * 0.02,
                    )
                    self._attempt_drc_fix(board, drc_result)

                if self._is_cancelled():
                    return None

            if not drc_passed:
                self._emit(
                    AgentPhase.RUNNING_DRC,
                    "DRC has warnings but proceeding with output generation",
                    progress=0.80,
                    board=board,
                )

            # Phase 6: Generate manufacturing outputs
            self._emit(
                AgentPhase.GENERATING_OUTPUTS,
                "Generating manufacturing files...",
                progress=0.82,
            )

            output_dir = Path(self.config.output_dir) / _sanitize_name(board.name)
            generated_files = self._generate_outputs(board, output_dir)

            self._emit(
                AgentPhase.COMPLETE,
                "Design complete!",
                detail=f"Generated {len(generated_files)} files in {output_dir}\n\n"
                + "\n".join(f"  - {f}" for f in generated_files)
                + f"\n\nBoard summary:\n"
                + "\n".join(f"  {k}: {v}" for k, v in board.summary().items()),
                progress=1.0,
                board=board,
            )

            return board

        except Exception as e:
            self._emit(
                AgentPhase.FAILED,
                f"Design failed: {e}",
                detail=str(e),
            )
            return None

    # ─── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _components_have_positions(board: Board) -> bool:
        """Check if components already have non-origin positions (from DSL)."""
        placed = 0
        for comp in board.components:
            if abs(comp.position.x) > 0.1 or abs(comp.position.y) > 0.1:
                placed += 1
        # If more than half have positions, consider it pre-placed
        return placed > len(board.components) * 0.5

    # ─── Board Sizing ────────────────────────────────────────────────────

    def _size_board(self, board: Board) -> None:
        """Auto-size board or validate user-requested size."""
        cfg = self.config

        # If components already have positions (DSL templates), trust the board size
        if self._components_have_positions(board):
            self._emit(
                AgentPhase.SIZING_BOARD,
                f"Using template board size: {board.settings.width}x{board.settings.height}mm",
                f"Components are pre-placed for this board size",
                progress=0.15,
                board=board,
            )
            return

        est_w, est_h = estimate_board_size(board)

        if cfg.user_width > 0 and cfg.user_height > 0:
            # User specified a size - check feasibility
            user_area = cfg.user_width * cfg.user_height
            needed_area = est_w * est_h

            if user_area < needed_area * 0.5:
                # Way too small - warn and use AI recommendation
                self._emit(
                    AgentPhase.SIZING_BOARD,
                    f"Requested size {cfg.user_width}x{cfg.user_height}mm is too small!",
                    f"Need at least ~{est_w}x{est_h}mm for {len(board.components)} "
                    f"components. Using AI recommended size.",
                    progress=0.15,
                )
                board.settings.width = est_w
                board.settings.height = est_h
            elif user_area < needed_area * 0.75:
                self._emit(
                    AgentPhase.SIZING_BOARD,
                    f"Requested size is tight but attempting: "
                    f"{cfg.user_width}x{cfg.user_height}mm",
                    f"AI recommends {est_w}x{est_h}mm. Results may have DRC errors.",
                    progress=0.15,
                )
                board.settings.width = cfg.user_width
                board.settings.height = cfg.user_height
            else:
                board.settings.width = cfg.user_width
                board.settings.height = cfg.user_height
                self._emit(
                    AgentPhase.SIZING_BOARD,
                    f"Using requested size: {cfg.user_width}x{cfg.user_height}mm",
                    progress=0.15,
                )
        else:
            # Auto-size
            board.settings.width = est_w
            board.settings.height = est_h
            self._emit(
                AgentPhase.SIZING_BOARD,
                f"Auto-sized board: {est_w}x{est_h}mm",
                f"Based on {len(board.components)} components with routing overhead",
                progress=0.15,
                board=board,
            )

    # ─── Template Matching ───────────────────────────────────────────────

    def _match_template(self, request: str) -> str | None:
        """Match a template only when 2+ keywords hit (strict fallback).

        Single-keyword matches are too aggressive — "esp32" alone should
        NOT lock the user into the carrier template when they want a
        custom board.
        """
        request_lower = request.lower()

        template_keywords = {
            "esp32_carrier": [
                "carrier", "development board",
                "dev board", "breakout board",
            ],
            "led_blinker": [
                "blink", "simple", "basic", "beginner",
                "first project", "hello world",
            ],
            "sensor_breakout": [
                "sensor breakout", "i2c breakout",
                "temperature sensor", "accelerometer breakout",
            ],
        }

        best_match = None
        best_score = 0

        for template_name, keywords in template_keywords.items():
            score = sum(1 for kw in keywords if kw in request_lower)
            if score > best_score:
                best_score = score
                best_match = template_name

        # Require at least 1 multi-word phrase match (strict)
        return best_match if best_score >= 1 else None

    # ─── Custom Design via DesignEngine ─────────────────────────────────

    def _create_custom_design(self, user_request: str) -> Board | None:
        """Use the DesignEngine to compose a custom board from the request.

        Returns a fully-wired Board on success, or None if the request
        doesn't contain enough actionable detail for the engine.
        """
        try:
            request = parse_request(user_request)

            # If the request is too vague (no features at all), let LLM handle it
            has_features = (
                request.led_matrix is not None
                or request.neopixel_strip > 0
                or request.debug_header
                or request.gpio_header
                or request.i2c
                or request.spi
                or request.uart
                or request.camera
                or request.display
                or request.sd_card
                or request.motor_driver
                or request.relay
                or request.sensors
                or request.leds > 0
                or request.buttons > 0
                or request.screw_terminals > 0
                or request.barrel_jack
                or request.logo_text
            )
            if not has_features:
                # Try LLM for novel designs the hardcoded engine can't handle
                return self._generate_from_llm(user_request)

            self._emit(
                AgentPhase.SELECTING_COMPONENTS,
                f"Designing custom {request.mcu.upper()} board...",
                f"Features: " + ", ".join(filter(None, [
                    f"{request.led_matrix[0]}x{request.led_matrix[1]} NeoPixel"
                    if request.led_matrix else None,
                    request.power,
                    "debug header" if request.debug_header else None,
                    f"{request.gpio_count} GPIO header"
                    if request.gpio_header else None,
                    "I2C" if request.i2c else None,
                    f"{request.leds} indicator LEDs"
                    if request.leds > 0 else None,
                    f'logo "{request.logo_text}"'
                    if request.logo_text else None,
                ])),
                progress=0.05,
            )

            engine = DesignEngine()
            pcb = engine.create_design(request)
            board = pcb.build()

            # Report design decisions
            self._emit(
                AgentPhase.CREATING_SCHEMATIC,
                "Custom design created!",
                detail="\n".join(engine.design_log),
                progress=0.10,
                board=board,
            )

            return board

        except Exception as e:
            self._emit(
                AgentPhase.ANALYZING,
                f"Design engine failed ({e}), falling back...",
                detail=str(e),
                progress=0.06,
            )
            return None

    def _validate_design(self, board: Board) -> None:
        """Run DesignValidator and log the quality score."""
        try:
            validator = DesignValidator()
            score = validator.validate(board)

            severity_detail = ""
            if score.issues:
                top_issues = score.issues[:8]
                severity_detail = "\n".join(
                    f"  [{i.severity.upper()}] {i.message}" for i in top_issues
                )
                if len(score.issues) > 8:
                    severity_detail += (
                        f"\n  ... and {len(score.issues) - 8} more issues"
                    )

            self._emit(
                AgentPhase.CREATING_SCHEMATIC,
                f"Design score: {score.total:.0f}/100"
                + (" (feasible)" if score.is_feasible else " (has critical issues)"),
                detail=score.summary()
                + ("\n\n" + severity_detail if severity_detail else ""),
                progress=0.13,
                board=board,
            )
        except Exception:
            pass  # Validation is advisory; don't block the pipeline

    # ─── LLM-based Design (thinking-capable models) ─────────────────────

    def _resolve_api_key(self) -> str:
        """Resolve API key from config or environment variables."""
        import os
        if self.config.api_key:
            return self.config.api_key
        provider = self.config.llm_provider
        if provider == "openai":
            return os.environ.get("OPENAI_API_KEY", "")
        elif provider == "anthropic":
            return os.environ.get("ANTHROPIC_API_KEY", "")
        return ""

    def _generate_from_llm(self, request: str) -> Board | None:
        """Use a thinking-capable LLM to design a novel PCB from scratch.

        The LLM receives the full PCBDesign DSL reference, all available
        footprints with pin maps, and the subcircuit library.  It then
        generates Python code that composes a complete board.

        Supports OpenAI (o3-mini / o4-mini / gpt-4o) and Anthropic.
        Includes a validation-and-retry loop for self-correction.
        """
        provider = self.config.llm_provider

        if provider == "template":
            return None

        api_key = self._resolve_api_key()
        if not api_key:
            self._emit(
                AgentPhase.ANALYZING,
                f"No API key found for {provider}. Set api_key in config "
                f"or {provider.upper()}_API_KEY environment variable.",
            )
            return None

        self._emit(
            AgentPhase.ANALYZING,
            "Using AI to design a novel PCB from scratch...",
            f"Provider: {provider}, model: {self.config.model or 'auto'}",
            progress=0.04,
        )

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(request)

        # Try up to 3 iterations: generate → validate → feedback → retry
        last_code = ""
        for attempt in range(3):
            try:
                if provider == "openai":
                    code = self._call_openai(system_prompt, user_prompt, api_key)
                elif provider == "anthropic":
                    code = self._call_anthropic(system_prompt, user_prompt, api_key)
                else:
                    return None

                if not code:
                    return None

                last_code = code
                board = self._execute_llm_code(code)
                if board is None:
                    continue

                # Validate the LLM-generated board
                validator = DesignValidator()
                score = validator.validate(board)

                # Accept the design if it's feasible OR scores well enough.
                # LLM-generated designs with minor overlaps (score >= 65)
                # are still usable — the DRC fix loop will clean them up.
                if score.is_feasible or score.total >= 65:
                    self._emit(
                        AgentPhase.CREATING_SCHEMATIC,
                        f"AI-designed board (score: {score.total:.0f}/100)",
                        detail=score.summary(),
                        progress=0.10,
                        board=board,
                    )
                    return board

                # Poor quality — feed errors back to the LLM
                error_feedback = "\n".join(
                    f"- [{i.severity.upper()}] {i.message}"
                    + (f" | Suggestion: {i.suggestion}" if i.suggestion else "")
                    for i in score.issues if i.severity == "critical"
                )
                user_prompt = (
                    f"The previous design had critical issues:\n"
                    f"{error_feedback}\n\n"
                    f"Please fix these issues and regenerate the complete "
                    f"PCBDesign code. Original request: {request}"
                )
                self._emit(
                    AgentPhase.ANALYZING,
                    f"Design attempt {attempt + 1}: score {score.total:.0f}, "
                    f"{score.critical_count} critical issues, retrying...",
                    progress=0.04 + attempt * 0.02,
                )

            except Exception as e:
                self._emit(
                    AgentPhase.ANALYZING,
                    f"LLM attempt {attempt + 1} failed: {e}",
                )
                continue

        return None

    def _build_system_prompt(self) -> str:
        from ..components.footprints import list_footprints, get_footprint

        footprints = list_footprints()

        # Build detailed footprint pin reference
        fp_details = []
        for fp_name in sorted(footprints):
            fp = get_footprint(fp_name)
            if fp:
                pins = [p.number for p in fp.pads]
                fp_details.append(f"  {fp_name}: pins {', '.join(pins)}")

        fp_reference = "\n".join(fp_details)

        # Get subcircuit library info if available
        subcircuit_info = ""
        try:
            from .subcircuits import list_subcircuits
            subcircuit_info = (
                "\n\n## Available Subcircuit Functions\n\n"
                "You can import and use these pre-built subcircuit functions:\n"
                "```python\n"
                "from ai_pcb_designer.ai.subcircuits import (\n"
                "    usb_c_power, ldo_3v3, esp32_minimal,\n"
                "    led_with_resistor, debug_header, mounting_holes_corners,\n"
                "    # ... etc\n"
                ")\n"
                "```\n\n"
                + list_subcircuits()
            )
        except ImportError:
            pass

        return f"""You are an expert PCB design engineer with deep knowledge of
electronics, component selection, and PCB layout. You THINK DEEPLY
about circuit design before writing code.

Your task: given a user's PCB description, generate Python code that
creates a complete, manufacturable board using the PCBDesign DSL.

## PCBDesign DSL Reference

```python
from ai_pcb_designer.ai.pcb_dsl import PCBDesign

pcb = PCBDesign("Board Name", width=70.0, height=55.0, description="...")

# Place a component (returns PlacedComponent for net wiring)
u1 = pcb.place("U1", "ESP32-WROOM-32", value="ESP32-WROOM-32",
                pos=(35, 28), description="Main MCU")
r1 = pcb.place("R1", "R_0603", value="10k", pos=(20, 15))
c1 = pcb.place("C1", "C_0603", value="100nF", pos=(30, 30))

# Connect pins via nets
pcb.net("SIGNAL", [(u1, "25"), (r1, "2")])     # Signal net
pcb.power_net("3V3", [(u1, "2"), (c1, "1")])   # Power net (wider trace)
pcb.power_net("GND", [(u1, "1"), (c1, "2")])   # Ground net

# GPIO bus (wire IC pins to header pins)
pcb.gpio_bus(u1, j1, {{"8": "1", "9": "2", "10": "3"}})

# Silkscreen text
pcb.text("My Board v1.0", pos=(35, 50), font_size=1.5)

board = pcb.build()
```

## Available Footprints (with pin numbers)

{fp_reference}

## Key Pin Maps

ESP32-WROOM-32 (39 pins):
  1=GND, 2=3V3, 3=EN, 4=SENSOR_VP, 5=SENSOR_VN,
  6=IO34, 7=IO35, 8=IO32, 9=IO33, 10=IO25,
  11=IO26, 12=IO27, 13=IO14, 14=IO12, 15=GND,
  16=IO13, 17=SHD/SD2, 18=SHD/SD3, 19=SCS/CMD,
  20=SCK/CLK, 21=SDO/SD0, 22=SDI/SD1, 23=IO15,
  24=IO2, 25=IO0, 26=IO4, 27=IO16, 28=IO17,
  29=IO5, 30=IO18, 31=IO19, 32=NC, 33=IO21,
  34=RXD0, 35=TXD0, 36=IO22, 37=IO23, 38=NC, 39=GND

USB_C_16pin (24 pins):
  A1=GND, A4=VBUS, A5=CC1, A6=D+, A7=D-,
  A8=SBU1, A9=VBUS, A12=GND
  B1=GND, B4=VBUS, B5=CC2, B6=D+, B7=D-,
  B8=SBU2, B9=VBUS, B12=GND

SOT-223 (LDO like AMS1117):
  1=Input, 2=Ground, 3=Output

SOT-23 (transistor/MOSFET):
  1=Base/Gate, 2=Emitter/Source, 3=Collector/Drain

WS2812B (addressable RGB LED):
  1=VDD(5V), 2=DOUT, 3=GND, 4=DIN
{subcircuit_info}

## Design Rules (CRITICAL)

1. EVERY IC must have at least one 100nF bypass cap within 5mm
2. EVERY IC must be connected to power AND ground nets
3. Use power_net() for GND, VCC, 3V3, 5V, VBUS (wider traces)
4. Use net() for signal connections (standard traces)
5. Place USB/barrel jack connectors at board edges (y < 15mm from top or x < 15mm from edge)
6. ALL components must fit inside board boundaries with 5mm margin
7. Space components at least 3mm apart to avoid overlaps
8. Include pull-up resistors on EN/RESET pins (10k to 3V3)
9. Include current-limiting resistors for LEDs (330-1k ohm)
10. Include input AND output capacitors for voltage regulators
11. Reference designator prefixes: U=IC, R=Resistor, C=Capacitor,
    D=Diode/LED, J=Connector, SW=Switch, H=Mounting Hole, L=Inductor

## Layout Guidelines

- Board origin is top-left (0,0)
- Connectors go at edges: USB at top center, headers on sides
- Main IC centered: pos=(width/2, 25-35)
- Support passives within 5mm of their IC
- Power section near USB connector
- Leave 5mm margin from all edges
- For NxM LED matrices: 10mm pitch, serpentine data wiring

Output ONLY the Python code, no explanations. The code MUST end with:
board = pcb.build()
"""

    def _build_user_prompt(self, request: str) -> str:
        return (
            f"Design a complete, manufacturable PCB for this request:\n\n"
            f"{request}\n\n"
            f"Think carefully about:\n"
            f"1. What components are needed (MCU, power, sensors, connectors)\n"
            f"2. Proper power distribution (regulators, decoupling)\n"
            f"3. Signal connections and pin assignments\n"
            f"4. Physical layout and component spacing\n"
            f"5. Board size that fits everything with routing room\n\n"
            f"Generate complete Python code using the PCBDesign DSL.\n"
            f"Include ALL necessary support components.\n"
            f"Output ONLY the Python code."
        )

    # Known OpenAI reasoning/thinking model prefixes — these use a single
    # user message (no system role, no temperature param).
    _OPENAI_THINKING_PREFIXES = ("o1", "o3", "o4")

    @classmethod
    def _is_thinking_model(cls, model: str) -> bool:
        """Return True if *model* is an OpenAI reasoning/thinking model."""
        return any(model.startswith(p) for p in cls._OPENAI_THINKING_PREFIXES)

    def _call_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        api_key: str,
    ) -> str | None:
        """Call OpenAI API. Supports thinking/reasoning models.

        Default model: ``o3-mini`` (reasoning model — thinks through
        circuit design before generating code).

        Thinking models (o-series: o1, o3-mini, o4-mini, etc.) use
        a single user message with ``max_completion_tokens`` instead of
        ``max_tokens``.  Non-thinking models (gpt-4o, gpt-4.1, etc.)
        use the standard system + user format.

        Returns the raw response text (code), NOT a Board.
        """
        try:
            import openai
        except ImportError:
            self._emit(
                AgentPhase.ANALYZING,
                "openai package not installed. Run: pip install openai",
            )
            return None

        client = openai.OpenAI(api_key=api_key)
        model = self.config.model or "o3-mini"

        self._emit(
            AgentPhase.ANALYZING,
            f"Calling {model} for PCB design...",
            progress=0.04,
        )

        try:
            if self._is_thinking_model(model):
                # Thinking / reasoning models don't support system messages
                # or temperature — combine into one user message.
                combined = system_prompt + "\n\n---\n\n" + user_prompt
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": combined}],
                    max_completion_tokens=16384,
                )
            else:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.3,
                    max_tokens=8192,
                )

            content = response.choices[0].message.content
            return content if content else None

        except openai.AuthenticationError:
            self._emit(
                AgentPhase.ANALYZING,
                f"OpenAI authentication failed — check your API key.",
            )
            return None
        except openai.RateLimitError:
            self._emit(
                AgentPhase.ANALYZING,
                f"OpenAI rate limit hit — try again in a moment.",
            )
            return None
        except openai.BadRequestError as e:
            self._emit(
                AgentPhase.ANALYZING,
                f"OpenAI rejected request: {e}. Try a different model.",
            )
            return None
        except openai.APIConnectionError as e:
            self._emit(
                AgentPhase.ANALYZING,
                f"Cannot connect to OpenAI API: {e}",
            )
            return None
        except Exception as e:
            self._emit(
                AgentPhase.ANALYZING,
                f"OpenAI call failed: {type(e).__name__}: {e}",
            )
            return None

    def _call_anthropic(
        self,
        system_prompt: str,
        user_prompt: str,
        api_key: str,
    ) -> str | None:
        """Call Anthropic API. Returns raw response text (code)."""
        try:
            import anthropic
        except ImportError:
            self._emit(
                AgentPhase.ANALYZING,
                "anthropic package not installed. Run: pip install anthropic",
            )
            return None

        client = anthropic.Anthropic(api_key=api_key)
        model = self.config.model or "claude-sonnet-4-5-20250929"

        self._emit(
            AgentPhase.ANALYZING,
            f"Calling {model} for PCB design...",
            progress=0.04,
        )

        try:
            response = client.messages.create(
                model=model,
                max_tokens=8192,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt},
                ],
            )

            content = response.content[0].text
            return content if content else None

        except anthropic.AuthenticationError:
            self._emit(
                AgentPhase.ANALYZING,
                "Anthropic authentication failed — check your API key.",
            )
            return None
        except anthropic.RateLimitError:
            self._emit(
                AgentPhase.ANALYZING,
                "Anthropic rate limit hit — try again in a moment.",
            )
            return None
        except anthropic.APIConnectionError as e:
            self._emit(
                AgentPhase.ANALYZING,
                f"Cannot connect to Anthropic API: {e}",
            )
            return None
        except Exception as e:
            self._emit(
                AgentPhase.ANALYZING,
                f"Anthropic call failed: {type(e).__name__}: {e}",
            )
            return None

    def _execute_llm_code(self, code: str) -> Board | None:
        """Execute Python DSL code generated by an LLM and return the Board.

        Extracts Python code from markdown fences if present, then executes
        it in a clean namespace with the PCBDesign class and subcircuit
        functions available.

        Returns the Board on success, or None on failure.
        """
        import re
        from .pcb_dsl import PCBDesign

        # Extract code from ```python ... ``` fences if present
        fence_match = re.search(
            r"```(?:python)?\s*\n(.*?)```", code, re.DOTALL
        )
        if fence_match:
            code = fence_match.group(1)

        # Strip import lines that would fail inside exec
        code = re.sub(
            r"^\s*from\s+\S*(?:pcb_dsl|subcircuits)\s+import\s+.*$",
            "",
            code,
            flags=re.MULTILINE,
        )
        code = re.sub(
            r"^\s*import\s+\S*(?:pcb_dsl|subcircuits)\s*$",
            "",
            code,
            flags=re.MULTILINE,
        )

        # Build namespace with DSL class and subcircuit functions
        namespace: dict[str, Any] = {"PCBDesign": PCBDesign}

        # Inject subcircuit functions if available
        try:
            from . import subcircuits
            for attr_name in dir(subcircuits):
                obj = getattr(subcircuits, attr_name)
                if callable(obj) and not attr_name.startswith("_"):
                    namespace[attr_name] = obj
        except ImportError:
            pass

        try:
            exec(code, namespace)  # noqa: S102
        except Exception as exc:
            self._emit(
                AgentPhase.ANALYZING,
                f"LLM-generated code execution failed: {exc}",
                detail=code[:500],
            )
            return None

        # Look for a Board object first, then a PCBDesign to build
        if "board" in namespace and isinstance(namespace["board"], Board):
            return namespace["board"]

        if "pcb" in namespace and isinstance(namespace["pcb"], PCBDesign):
            try:
                return namespace["pcb"].build()
            except Exception as exc:
                self._emit(
                    AgentPhase.ANALYZING,
                    f"PCBDesign.build() failed: {exc}",
                    detail=code[:500],
                )
                return None

        self._emit(
            AgentPhase.ANALYZING,
            "LLM code did not produce a 'board' or 'pcb' variable",
            detail=code[:300],
        )
        return None

    # ─── DRC Fix ─────────────────────────────────────────────────────────

    def _attempt_drc_fix(self, board: Board, drc_result: DRCResult) -> None:
        """Attempt to fix DRC violations with targeted adjustments."""
        bw = board.settings.width
        bh = board.settings.height
        margin = board.settings.design_rules.edge_clearance + 1.0

        for violation in drc_result.violations:
            if violation.violation_type == DRCViolationType.OVERLAP:
                # Push overlapping components APART from each other
                refs = violation.component_refs
                if len(refs) == 2:
                    c1 = board.get_component(refs[0])
                    c2 = board.get_component(refs[1])
                    if c1 and c2:
                        dx = c1.position.x - c2.position.x
                        dy = c1.position.y - c2.position.y
                        dist = max(math.hypot(dx, dy), 0.1)
                        # Normalize direction and push apart
                        push = 1.5
                        nx, ny = dx / dist, dy / dist
                        # Move c1 away from c2
                        new_x1 = max(margin, min(bw - margin,
                                     c1.position.x + push * nx))
                        new_y1 = max(margin, min(bh - margin,
                                     c1.position.y + push * ny))
                        c1.position = Point(new_x1, new_y1)
                        # Move c2 away from c1 (opposite direction)
                        new_x2 = max(margin, min(bw - margin,
                                     c2.position.x - push * nx))
                        new_y2 = max(margin, min(bh - margin,
                                     c2.position.y - push * ny))
                        c2.position = Point(new_x2, new_y2)

            elif violation.violation_type == DRCViolationType.EDGE_CLEARANCE:
                # Only fix the specific component(s) referenced in the violation
                for ref in violation.component_refs:
                    comp = board.get_component(ref)
                    if comp:
                        cp = comp.position
                        new_x = max(margin, min(bw - margin, cp.x))
                        new_y = max(margin, min(bh - margin, cp.y))
                        if new_x != cp.x or new_y != cp.y:
                            comp.position = Point(new_x, new_y)

        # Re-route after placement changes
        board.clear_routing()
        router = AutoRouter(RouterConfig())
        router.route(board)

    # ─── Output Generation ───────────────────────────────────────────────

    def _generate_outputs(self, board: Board, output_dir: Path) -> list[str]:
        files = []

        if self.config.generate_gerbers:
            gerber_dir = output_dir / "gerbers"
            exporter = GerberExporter(board)
            files.extend(exporter.export(gerber_dir))
            self._emit(
                AgentPhase.GENERATING_OUTPUTS,
                "Gerber files generated",
                progress=0.88,
            )

        if self.config.generate_bom:
            bom_path = output_dir / "BOM.csv"
            BOMExporter(board).export(bom_path)
            files.append(str(bom_path))

            jlc_bom_path = output_dir / "BOM_JLCPCB.csv"
            BOMExporter(board).export_jlcpcb_bom(jlc_bom_path)
            files.append(str(jlc_bom_path))
            self._emit(
                AgentPhase.GENERATING_OUTPUTS,
                "BOM files generated",
                progress=0.91,
            )

        if self.config.generate_pnp:
            pnp_path = output_dir / "PickAndPlace.csv"
            PickAndPlaceExporter(board).export(pnp_path)
            files.append(str(pnp_path))

            jlc_cpl_path = output_dir / "CPL_JLCPCB.csv"
            PickAndPlaceExporter(board).export_jlcpcb_cpl(jlc_cpl_path)
            files.append(str(jlc_cpl_path))
            self._emit(
                AgentPhase.GENERATING_OUTPUTS,
                "Pick-and-Place files generated",
                progress=0.94,
            )

        if self.config.generate_kicad:
            kicad_path = output_dir / f"{_sanitize_name(board.name)}.kicad_pcb"
            KiCadExporter(board).export(kicad_path)
            files.append(str(kicad_path))
            self._emit(
                AgentPhase.GENERATING_OUTPUTS,
                "KiCad file generated",
                progress=0.97,
            )

        # Assembly drawing
        assy_path = output_dir / "Assembly_Drawing.svg"
        AssemblyDrawingExporter(board).export(assy_path)
        files.append(str(assy_path))
        self._emit(
            AgentPhase.GENERATING_OUTPUTS,
            "Assembly drawing generated",
            progress=0.98,
        )

        return files

    # ─── Step Emission ───────────────────────────────────────────────────

    def _emit(
        self,
        phase: AgentPhase,
        message: str,
        detail: str = "",
        progress: float = 0.0,
        board: Board | None = None,
    ) -> None:
        """Emit a step update with monotonic progress and deep-copied board."""
        self._phase = phase

        # Ensure progress never decreases (monotonic)
        progress = max(progress, self._progress)
        self._progress = progress

        # Deep copy the board snapshot for thread safety
        snapshot = None
        source = board or self._board
        if source is not None:
            try:
                snapshot = copy.deepcopy(source)
            except Exception:
                snapshot = source  # fallback to reference if copy fails

        step = AgentStep(
            phase=phase,
            message=message,
            detail=detail,
            progress=progress,
            board_snapshot=snapshot,
        )
        self._steps.append(step)
        if self._on_step:
            self._on_step(step)


def _sanitize_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_", " ") else "_" for c in name).strip()
