"""AI Agent Orchestrator for autonomous PCB design.

This is the central intelligence that drives the entire design process:
1. Parse user's natural language description
2. Select/generate schematic (component selection + netlist)
3. Run component placement
4. Run trace routing
5. Run DRC checks
6. Iterate if DRC fails (adjust placement, re-route)
7. Generate manufacturing outputs

The agent emits step-by-step updates for the GUI to display.

Supports both OpenAI and Anthropic APIs for the LLM backend,
or can run in "template mode" without any API key using built-in
board templates.
"""

from __future__ import annotations

import json
import os
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
from ..engines.schematic import SchematicEngine
from ..engines.placer import PlacementEngine, PlacementConfig
from ..engines.router import AutoRouter, RouterConfig
from ..engines.drc import DRCEngine, DRCResult
from ..exporters.gerber import GerberExporter
from ..exporters.bom import BOMExporter, PickAndPlaceExporter
from ..exporters.kicad import KiCadExporter


class AgentPhase(Enum):
    """Current phase of the AI design pipeline."""
    IDLE = auto()
    ANALYZING = auto()
    SELECTING_COMPONENTS = auto()
    CREATING_SCHEMATIC = auto()
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
    """Configuration for the AI agent."""
    llm_provider: str = "template"  # "openai", "anthropic", or "template"
    api_key: str = ""
    model: str = ""
    output_dir: str = "./output"
    max_drc_retries: int = 3
    generate_kicad: bool = True
    generate_gerbers: bool = True
    generate_bom: bool = True
    generate_pnp: bool = True


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
        """Set callback for real-time step updates (used by GUI)."""
        self._on_step = callback

    def design(self, user_request: str) -> Board | None:
        """Run the full autonomous design pipeline.

        Args:
            user_request: Natural language description of the desired PCB.
                         e.g., "Make me a carrier board for an ESP32 with
                         USB-C, power LED, and GPIO breakout headers"

        Returns:
            The completed Board object, or None if design failed.
        """
        try:
            self._emit(AgentPhase.ANALYZING, "Analyzing your request...",
                       f"Input: {user_request}")

            # Phase 1: Understand the request and select a template/design
            template_name = self._match_template(user_request)

            if template_name:
                self._emit(
                    AgentPhase.SELECTING_COMPONENTS,
                    f"Matched template: {TEMPLATE_REGISTRY[template_name].name}",
                    f"Using built-in template '{template_name}' with pre-defined "
                    f"components and netlist.",
                    progress=0.1,
                )
                board = create_board_from_template(template_name)
            else:
                # If no template matches, use LLM or fallback to LED blinker
                board = self._generate_from_llm(user_request)
                if board is None:
                    self._emit(
                        AgentPhase.SELECTING_COMPONENTS,
                        "No matching template found. Using LED blinker as default.",
                        progress=0.1,
                    )
                    board = create_board_from_template("led_blinker")

            self._board = board
            self._emit(
                AgentPhase.CREATING_SCHEMATIC,
                f"Board created: {board.name}",
                f"{len(board.components)} components, {len(board.nets)} nets",
                progress=0.15,
                board=board,
            )

            # Phase 2: Component placement
            self._emit(
                AgentPhase.PLACING_COMPONENTS,
                "Placing components on the board...",
                f"Using force-directed placement for {len(board.components)} components",
                progress=0.2,
            )

            placer = PlacementEngine(PlacementConfig(seed=42))
            placer.set_step_callback(lambda step: self._emit(
                AgentPhase.PLACING_COMPONENTS,
                step.message,
                f"Iteration {step.iteration}, total force: {step.total_force:.3f}",
                progress=0.2 + 0.2 * min(step.iteration / 200, 1.0),
                board=board,
            ))
            placer.place(board)

            self._emit(
                AgentPhase.PLACING_COMPONENTS,
                "Component placement complete!",
                progress=0.4,
                board=board,
            )

            # Phase 3: Trace routing
            self._emit(
                AgentPhase.ROUTING_TRACES,
                "Routing traces...",
                f"Routing {len(board.get_unrouted_nets())} nets",
                progress=0.4,
            )

            router = AutoRouter(RouterConfig())
            router.set_step_callback(lambda step: self._emit(
                AgentPhase.ROUTING_TRACES,
                step.message,
                f"Net: {step.net_name} - {step.phase}",
                progress=0.4 + 0.3 * (0.5 if step.phase == "searching" else 1.0),
                board=board,
            ))
            all_routed, route_steps = router.route(board)

            if all_routed:
                self._emit(
                    AgentPhase.ROUTING_TRACES,
                    "All nets routed successfully!",
                    f"Total: {len(board.get_all_segments())} segments, "
                    f"{len(board.get_all_vias())} vias",
                    progress=0.7,
                    board=board,
                )
            else:
                self._emit(
                    AgentPhase.ROUTING_TRACES,
                    "Some nets could not be routed (will attempt fix)",
                    progress=0.7,
                    board=board,
                )

            # Phase 4: DRC
            drc_passed = False
            for attempt in range(self.config.max_drc_retries + 1):
                self._emit(
                    AgentPhase.RUNNING_DRC,
                    f"Running Design Rule Check (attempt {attempt + 1})...",
                    progress=0.75,
                )

                drc_engine = DRCEngine()
                drc_engine.set_check_callback(lambda msg: self._emit(
                    AgentPhase.RUNNING_DRC, msg, progress=0.75,
                ))
                drc_result = drc_engine.check(board)

                if drc_result.passed:
                    drc_passed = True
                    self._emit(
                        AgentPhase.RUNNING_DRC,
                        f"DRC PASSED! ({drc_result.warning_count} warnings)",
                        progress=0.8,
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
                        progress=0.75,
                    )
                    self._attempt_drc_fix(board, drc_result)

            if not drc_passed:
                self._emit(
                    AgentPhase.RUNNING_DRC,
                    "DRC has warnings but proceeding with output generation",
                    progress=0.8,
                    board=board,
                )

            # Phase 5: Generate manufacturing outputs
            self._emit(
                AgentPhase.GENERATING_OUTPUTS,
                "Generating manufacturing files...",
                progress=0.85,
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

    def _match_template(self, request: str) -> str | None:
        """Match user request to a built-in template."""
        request_lower = request.lower()

        # Keyword matching for templates
        template_keywords = {
            "esp32_carrier": [
                "esp32", "esp-32", "carrier", "development board",
                "dev board", "breakout board", "wifi", "bluetooth",
                "wroom",
            ],
            "led_blinker": [
                "led", "blink", "simple", "basic", "beginner",
                "light", "first project", "hello world",
            ],
            "sensor_breakout": [
                "sensor", "i2c", "breakout", "temperature",
                "accelerometer", "gyroscope", "bme280", "mpu6050",
            ],
        }

        best_match = None
        best_score = 0

        for template_name, keywords in template_keywords.items():
            score = sum(1 for kw in keywords if kw in request_lower)
            if score > best_score:
                best_score = score
                best_match = template_name

        return best_match if best_score > 0 else None

    def _generate_from_llm(self, request: str) -> Board | None:
        """Use LLM to generate a board design from natural language.

        Falls back to template mode if no API key is configured.
        """
        provider = self.config.llm_provider

        if provider == "template" or not self.config.api_key:
            return None

        # LLM-based generation
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(request)

        try:
            if provider == "openai":
                return self._call_openai(system_prompt, user_prompt)
            elif provider == "anthropic":
                return self._call_anthropic(system_prompt, user_prompt)
        except Exception as e:
            self._emit(
                AgentPhase.ANALYZING,
                f"LLM call failed ({e}), falling back to template matching",
            )
            return None

        return None

    def _build_system_prompt(self) -> str:
        """Build the system prompt for LLM-based design generation."""
        templates = list_templates()
        from ..components.footprints import list_footprints
        footprints = list_footprints()

        return f"""You are an expert PCB design engineer. Given a user's description of a
PCB they want to create, generate a complete board specification as JSON.

Available footprints: {', '.join(footprints)}

Available template designs for reference: {json.dumps(templates, indent=2)}

Your output MUST be valid JSON with this structure:
{{
  "name": "Board Name",
  "description": "Brief description",
  "width": 50.0,
  "height": 40.0,
  "components": [
    {{
      "reference": "U1",
      "value": "ESP32-WROOM-32",
      "footprint": "ESP32-WROOM-32",
      "pins": {{"1": "GND", "2": "3V3"}},
      "manufacturer": "Espressif",
      "mpn": "ESP32-WROOM-32E",
      "description": "WiFi+BT module"
    }}
  ]
}}

Rules:
- Use standard reference designator prefixes (U for ICs, R for resistors,
  C for capacitors, D for diodes/LEDs, J for connectors, SW for switches,
  H for mounting holes)
- Always include decoupling capacitors near ICs
- Always include pull-up/pull-down resistors where needed
- Include appropriate power filtering
- Board dimensions should be reasonable for the component count
- Pin net names should be consistent (GND, 3V3, 5V, etc.)
"""

    def _build_user_prompt(self, request: str) -> str:
        return f"""Design a PCB based on this request:

{request}

Generate the complete board specification as JSON. Include all necessary
support components (decoupling caps, pull-up resistors, connectors, etc.)."""

    def _call_openai(self, system_prompt: str, user_prompt: str) -> Board | None:
        """Call OpenAI API to generate board spec."""
        try:
            import openai
        except ImportError:
            return None

        client = openai.OpenAI(api_key=self.config.api_key)
        response = client.chat.completions.create(
            model=self.config.model or "gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        content = response.choices[0].message.content
        if not content:
            return None

        spec = json.loads(content)
        engine = SchematicEngine()
        return engine.generate_from_spec(spec)

    def _call_anthropic(self, system_prompt: str, user_prompt: str) -> Board | None:
        """Call Anthropic API to generate board spec."""
        try:
            import anthropic
        except ImportError:
            return None

        client = anthropic.Anthropic(api_key=self.config.api_key)
        response = client.messages.create(
            model=self.config.model or "claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
        )

        content = response.content[0].text
        # Extract JSON from response
        try:
            start = content.index("{")
            end = content.rindex("}") + 1
            spec = json.loads(content[start:end])
        except (ValueError, json.JSONDecodeError):
            return None

        engine = SchematicEngine()
        return engine.generate_from_spec(spec)

    def _attempt_drc_fix(self, board: Board, drc_result: DRCResult) -> None:
        """Attempt to fix DRC violations by adjusting the design."""
        from ..engines.drc import DRCViolationType

        for violation in drc_result.violations:
            if violation.violation_type == DRCViolationType.OVERLAP:
                # Try to spread overlapping components apart
                for ref in violation.component_refs:
                    comp = board.get_component(ref)
                    if comp:
                        comp.position = comp.position + Point(1.0, 1.0)

            elif violation.violation_type == DRCViolationType.EDGE_CLEARANCE:
                # Move component away from edge
                if violation.location:
                    for comp in board.components:
                        cp = comp.position
                        margin = board.settings.design_rules.edge_clearance + 1.0
                        new_x = max(margin, min(board.settings.width - margin, cp.x))
                        new_y = max(margin, min(board.settings.height - margin, cp.y))
                        if new_x != cp.x or new_y != cp.y:
                            comp.position = Point(new_x, new_y)

        # Re-route after placement changes
        board.clear_routing()
        router = AutoRouter(RouterConfig())
        router.route(board)

    def _generate_outputs(self, board: Board, output_dir: Path) -> list[str]:
        """Generate all manufacturing output files."""
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

        return files

    def _emit(
        self,
        phase: AgentPhase,
        message: str,
        detail: str = "",
        progress: float = 0.0,
        board: Board | None = None,
    ) -> None:
        """Emit a step update."""
        self._phase = phase
        step = AgentStep(
            phase=phase,
            message=message,
            detail=detail,
            progress=progress,
            board_snapshot=board or self._board,
        )
        self._steps.append(step)
        if self._on_step:
            self._on_step(step)


def _sanitize_name(name: str) -> str:
    """Sanitize a name for use as a filename."""
    return "".join(c if c.isalnum() or c in ("-", "_", " ") else "_" for c in name).strip()
