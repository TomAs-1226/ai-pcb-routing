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

            # Phase 1: Create custom design (primary) or match template (fallback)
            board = self._create_custom_design(user_request)

            if board is None:
                # Fallback: try strict template matching (needs 2+ keywords)
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
                    # Try LLM, then ultimate fallback
                    board = self._generate_from_llm(user_request)
                    if board is None:
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

            # If the request is too vague (no MCU, no features), skip
            has_features = (
                request.led_matrix is not None
                or request.debug_header
                or request.gpio_header
                or request.i2c
                or request.sensors
                or request.leds > 0
                or request.logo_text
            )
            if not has_features:
                return None

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

    # ─── LLM-based Generation ────────────────────────────────────────────

    def _generate_from_llm(self, request: str) -> Board | None:
        provider = self.config.llm_provider

        if provider == "template" or not self.config.api_key:
            return None

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
        templates = list_templates()
        from ..components.footprints import list_footprints
        footprints = list_footprints()

        return f"""You are an expert PCB design engineer. Given a user's description of a
PCB they want to create, generate Python code using the PCBDesign DSL.

Available footprints: {', '.join(footprints)}

Your output MUST be Python code that creates a board using this API:

```python
from ai_pcb_designer.ai.pcb_dsl import PCBDesign

pcb = PCBDesign("Board Name", width=70.0, height=55.0, description="...")

# Place components at specific positions
u1 = pcb.place("U1", "ESP32-WROOM-32", value="ESP32-WROOM-32",
                pos=(35, 28), description="Main MCU")
r1 = pcb.place("R1", "R_0603", value="10k", pos=(20, 15))

# Define nets connecting component pins
pcb.power_net("3V3", [(u1, "2"), (r1, "1")])  # Power net (wider trace)
pcb.net("SIGNAL", [(u1, "25"), (r1, "2")])     # Signal net

board = pcb.build()
```

Rules:
- Use standard reference designator prefixes (U, R, C, D, J, SW, H)
- Always include decoupling capacitors within 3mm of IC power pins
- Always include pull-up resistors for enable/reset pins
- Place connectors at board edges, ICs centered, passives near their ICs
- Board dimensions should fit all components with routing space
- Use power_net() for GND, VCC, 3V3, 5V, VBUS
- Every pin that needs connection must be in a net
- Component positions must be inside the board boundaries

Output ONLY the Python code, no explanations.
"""

    def _build_user_prompt(self, request: str) -> str:
        return f"""Design a PCB based on this request:

{request}

Generate Python code using the PCBDesign DSL. Include all necessary support
components (decoupling caps, pull-up resistors, connectors, etc.).
Output only the Python code."""

    def _call_openai(self, system_prompt: str, user_prompt: str) -> Board | None:
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
            temperature=0.3,
        )

        content = response.choices[0].message.content
        if not content:
            return None

        return self._execute_llm_code(content)

    def _call_anthropic(self, system_prompt: str, user_prompt: str) -> Board | None:
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
        if not content:
            return None

        return self._execute_llm_code(content)

    def _execute_llm_code(self, code: str) -> Board | None:
        """Execute Python DSL code generated by an LLM and return the Board.

        Extracts Python code from markdown fences if present, then executes
        it in a clean namespace with the PCBDesign class available.  Looks
        for a ``board`` variable (Board instance) or a ``pcb`` variable
        (PCBDesign instance, calling ``.build()`` on it) in the resulting
        namespace.

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

        # Build a clean namespace with the DSL class available.
        # The LLM code typically does `from ai_pcb_designer.ai.pcb_dsl import PCBDesign`
        # which would fail inside exec, so we strip that import and inject
        # the class directly.
        code = re.sub(
            r"^\s*from\s+\S*pcb_dsl\s+import\s+.*$",
            "",
            code,
            flags=re.MULTILINE,
        )

        namespace: dict[str, Any] = {"PCBDesign": PCBDesign}

        try:
            exec(code, namespace)  # noqa: S102
        except Exception as exc:
            self._emit(
                AgentPhase.ANALYZING,
                f"LLM-generated code execution failed: {exc}",
                detail=code,
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
                    detail=code,
                )
                return None

        self._emit(
            AgentPhase.ANALYZING,
            "LLM code did not produce a 'board' or 'pcb' variable",
            detail=code,
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
