"""AI Agent Orchestrator for autonomous PCB design - Phase 5 (Agentic).

Phase 5: Fully agentic AI-driven design with continuous improvement.
- Multi-iteration agentic loop: AI designs → validates → learns → improves
- AI self-notes: agent remembers design rules and lessons across iterations
- Component discovery: AI can use ANY component, not just the built-in library
- Physics enforcement: strict electrical/physical rules in every prompt
- Chat-like workflow: users can intervene at any point
- Web scraping: AI can look up datasheets and component info

Pipeline (agentic loop):
1. Parse user's natural language description
2. AI designs board (LLM or DesignEngine)
3. Validate design → AI reviews score + issues
4. AI writes self-notes about what went wrong
5. AI redesigns with improved approach (repeat up to N iterations)
6. Place components → route traces → DRC → auto-fix
7. If still failing, AI re-thinks placement strategy
8. Generate manufacturing outputs
9. Present results to user with full task list
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
from .notes import DesignMemory


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

      For OpenAI, the default model is ``"o4-mini"`` -- a reasoning
      model that thinks through circuit physics before generating
      code, at an affordable price point.
      Other choices: ``"gpt-4.1"``, ``"gpt-4o"``, ``"o3-mini"``

      For Anthropic, the default model is ``"claude-sonnet-4-5-20250929"``.

    Quick-start example::

        config = AgentConfig(llm_provider="openai")  # uses OPENAI_API_KEY env
        agent = PCBDesignAgent(config)
        board = agent.design("esp32 board with oled and motor driver")
    """
    llm_provider: str = "template"  # "openai", "anthropic", or "template"
    api_key: str = ""
    model: str = ""  # "" = auto-select (o4-mini for OpenAI, claude-sonnet for Anthropic)
    output_dir: str = "./output"
    max_drc_retries: int = 5
    max_agent_iterations: int = 5  # AI self-review iterations
    generate_kicad: bool = True
    generate_gerbers: bool = True
    generate_bom: bool = True
    generate_pnp: bool = True
    user_width: float = 0.0    # User-requested board width (0 = auto)
    user_height: float = 0.0   # User-requested board height (0 = auto)


@dataclass
class ChatMessage:
    """A message in the agent's chat log, visible to the user."""
    role: str  # "agent", "user", "system", "task"
    content: str
    detail: str = ""
    timestamp: float = field(default_factory=time.time)
    task_status: str = ""  # "running", "done", "failed", ""
    iteration: int = 0


class PCBDesignAgent:
    """Autonomous PCB design agent with continuous improvement.

    Orchestrates the entire design flow from natural language input
    to manufacturing-ready output files. Features:

    - Multi-iteration agentic loop: designs, validates, learns, improves
    - Self-notes: AI remembers design rules and lessons across iterations
    - Component discovery: can use ANY component via dynamic footprints
    - Physics enforcement: strict electrical rules in every LLM prompt
    - Chat interface: real-time messages with task status
    - User intervention: accepts mid-design feedback via message queue
    """

    def __init__(self, config: AgentConfig | None = None) -> None:
        self.config = config or AgentConfig()
        self._steps: list[AgentStep] = []
        self._on_step: Callable[[AgentStep], None] | None = None
        self._on_chat: Callable[[ChatMessage], None] | None = None
        self._phase = AgentPhase.IDLE
        self._board: Board | None = None
        self._component_db = ComponentDatabase()
        self._cancel_event = threading.Event()
        self._progress = 0.0  # monotonically increasing
        self._last_emit_time = 0.0
        self._memory = DesignMemory()
        self._chat_log: list[ChatMessage] = []
        self._user_messages: list[str] = []  # Queue for user interventions
        self._user_msg_lock = threading.Lock()
        self._tasks: list[dict] = []  # {"name": str, "status": str}

    @property
    def board(self) -> Board | None:
        return self._board

    @property
    def phase(self) -> AgentPhase:
        return self._phase

    @property
    def steps(self) -> list[AgentStep]:
        return self._steps

    @property
    def chat_log(self) -> list[ChatMessage]:
        return self._chat_log

    @property
    def memory(self) -> DesignMemory:
        return self._memory

    @property
    def tasks(self) -> list[dict]:
        return self._tasks

    def set_step_callback(self, callback: Callable[[AgentStep], None]) -> None:
        self._on_step = callback

    def set_chat_callback(self, callback: Callable[[ChatMessage], None]) -> None:
        """Set callback for chat messages (for GUI display)."""
        self._on_chat = callback

    def send_user_message(self, message: str) -> None:
        """Queue a user intervention message during design."""
        with self._user_msg_lock:
            self._user_messages.append(message)

    def _get_user_messages(self) -> list[str]:
        """Drain the user message queue."""
        with self._user_msg_lock:
            msgs = self._user_messages[:]
            self._user_messages.clear()
            return msgs

    def _chat(self, role: str, content: str, detail: str = "",
              task_status: str = "", iteration: int = 0) -> None:
        """Add a chat message and notify the callback."""
        msg = ChatMessage(
            role=role, content=content, detail=detail,
            task_status=task_status, iteration=iteration,
        )
        self._chat_log.append(msg)
        if self._on_chat:
            try:
                self._on_chat(msg)
            except Exception:
                pass

    def _update_task(self, name: str, status: str) -> None:
        """Update or add a task in the task list."""
        for task in self._tasks:
            if task["name"] == name:
                task["status"] = status
                return
        self._tasks.append({"name": name, "status": status})

    def cancel(self) -> None:
        """Signal the agent to stop as soon as possible."""
        self._cancel_event.set()

    def _is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def design(self, user_request: str) -> Board | None:
        """Run the full autonomous agentic design pipeline.

        This is a multi-iteration loop where the AI:
        1. Creates an initial design
        2. Validates it (physics, DRC, layout quality)
        3. Learns from issues (writes self-notes)
        4. Improves the design (repeat up to max_agent_iterations)
        5. Places, routes, and generates outputs

        User can intervene at any point via send_user_message().
        """
        try:
            self._cancel_event.clear()
            self._progress = 0.0
            self._tasks.clear()
            self._chat_log.clear()
            self._memory.clear_session()

            # Define task list (visible to user)
            task_names = [
                "Analyze request",
                "Design circuit",
                "Validate physics & rules",
                "Place components",
                "Route traces",
                "Run DRC checks",
                "Generate outputs",
            ]
            for name in task_names:
                self._update_task(name, "pending")

            self._chat("agent", "Starting design...",
                       f"Request: {user_request}")
            self._emit(AgentPhase.ANALYZING, "Analyzing your request...",
                       f"Input: {user_request}", progress=0.02)

            if self._is_cancelled():
                return None

            # ── Task 1: Analyze ──────────────────────────────────
            self._update_task("Analyze request", "running")
            self._chat("task", "Analyzing request...",
                       task_status="running")

            # Check for user interventions
            user_msgs = self._get_user_messages()
            if user_msgs:
                user_request = user_request + "\n\nUser additions: " + " ".join(user_msgs)
                self._chat("system", f"Incorporated user feedback: {user_msgs}")

            self._update_task("Analyze request", "done")

            # ── Task 2: Design (agentic loop) ────────────────────
            self._update_task("Design circuit", "running")
            self._chat("task", "Designing circuit...",
                       task_status="running")

            best_board = None
            best_score = -1
            max_iters = self.config.max_agent_iterations

            for iteration in range(1, max_iters + 1):
                if self._is_cancelled():
                    return None

                self._chat("agent",
                           f"Design iteration {iteration}/{max_iters}",
                           task_status="running", iteration=iteration)

                # Check for user interventions mid-loop
                user_msgs = self._get_user_messages()
                if user_msgs:
                    for msg in user_msgs:
                        self._chat("user", msg)
                        user_request += f"\n\nUser feedback (iter {iteration}): {msg}"
                        self._memory.add_note("STRATEGY",
                                              f"User requested: {msg}", priority=3)

                # Create design (with notes from previous iterations)
                board = self._create_custom_design(user_request, iteration)

                if board is None:
                    # Fallback chain
                    template_name = self._match_template(user_request)
                    if template_name:
                        board = create_board_from_template(template_name)
                        self._chat("agent",
                                   f"Used template: {template_name}")
                    else:
                        try:
                            engine = DesignEngine()
                            request_parsed = parse_request(user_request)
                            pcb = engine.create_design(request_parsed)
                            board = pcb.build()
                            self._chat("agent",
                                       "Created design via algorithmic engine",
                                       detail="\n".join(engine.design_log[-5:]))
                        except Exception as e:
                            self._memory.add_error(
                                str(e),
                                "Design engine failed - simplify component count"
                            )
                            board = None

                    if board is None:
                        if iteration < max_iters:
                            self._chat("agent",
                                       f"Design attempt {iteration} failed, retrying...")
                            self._memory.add_error(
                                "Could not create design",
                                "Try different approach next iteration"
                            )
                            continue
                        board = create_board_from_template("led_blinker")
                        self._chat("agent",
                                   "Falling back to LED blinker starter board")

                # Validate the design
                self._emit(
                    AgentPhase.CREATING_SCHEMATIC,
                    f"Iteration {iteration}: {board.name}",
                    f"{len(board.components)} components, {len(board.nets)} nets",
                    progress=0.05 + (iteration / max_iters) * 0.15,
                    board=board,
                )

                score = self._validate_design(board)
                self._memory.log_iteration(iteration,
                    f"Score={score}, {len(board.components)} comps, "
                    f"{len(board.nets)} nets")

                if score > best_score:
                    best_score = score
                    best_board = copy.deepcopy(board)

                # Physics-aware evaluation
                if score >= 80:
                    self._chat("agent",
                               f"Design quality: {score}/100 - good enough to proceed",
                               iteration=iteration)
                    break
                elif iteration < max_iters:
                    self._chat("agent",
                               f"Design quality: {score}/100 - improving...",
                               detail=f"Issues found, learning and retrying.",
                               iteration=iteration)
                    self._memory.add_note("STRATEGY",
                        f"Iteration {iteration} scored {score}. "
                        "Need to fix validation issues for next attempt.")
                else:
                    self._chat("agent",
                               f"Final design quality: {score}/100",
                               iteration=iteration)

            # Use best design from all iterations
            board = best_board or board
            self._board = board
            self._update_task("Design circuit", "done")

            self._emit(
                AgentPhase.CREATING_SCHEMATIC,
                f"Board finalized: {board.name}",
                f"{len(board.components)} components, {len(board.nets)} nets "
                f"(best score: {best_score})",
                progress=0.20,
                board=board,
            )

            # ── Task 3: Validate physics ──────────────────────────
            self._update_task("Validate physics & rules", "running")
            self._chat("task", "Validating physics and design rules...",
                       task_status="running")

            self._size_board(board)
            self._update_task("Validate physics & rules", "done")

            if self._is_cancelled():
                return None

            # ── Task 4: Place components ──────────────────────────
            self._update_task("Place components", "running")
            self._chat("task", "Placing components...",
                       task_status="running")

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

            self._update_task("Place components", "done")
            self._chat("task", f"Placed {len(board.components)} components",
                       task_status="done")

            if self._is_cancelled():
                return None

            # ── Task 5: Route traces ──────────────────────────────
            self._update_task("Route traces", "running")
            self._chat("task", "Routing traces...",
                       task_status="running")

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
                self._chat("agent", "All nets routed successfully!")
            else:
                # Placement optimisation loop with multiple strategies
                unrouted = board.get_unrouted_nets()
                unrouted_ratio = len(unrouted) / max(total_nets, 1)

                for opt_pass in range(4):  # More passes than before
                    if unrouted_ratio < 0.10 or self._is_cancelled():
                        break

                    self._chat("agent",
                        f"Optimization pass {opt_pass + 1}: "
                        f"{len(unrouted)} unrouted nets, re-placing...")

                    self._emit(
                        AgentPhase.PLACING_COMPONENTS,
                        f"Optimisation pass {opt_pass + 1}: "
                        f"{len(unrouted)} unrouted nets -- "
                        f"re-placing and re-routing...",
                        progress=0.50 + opt_pass * 0.04,
                        board=board,
                    )

                    board.clear_routing()

                    # Progressive optimization strategies
                    strategies = [
                        {"seed": 43, "attraction": 0.30, "repulsion": 12.0},
                        {"seed": 44, "attraction": 0.35, "repulsion": 14.0},
                        {"seed": 45, "attraction": 0.40, "repulsion": 10.0},
                        {"seed": 100, "attraction": 0.45, "repulsion": 8.0},
                    ]
                    strat = strategies[min(opt_pass, len(strategies) - 1)]

                    opt_cfg = PlacementConfig(
                        seed=strat["seed"],
                        attraction_strength=strat["attraction"],
                        repulsion_strength=strat["repulsion"],
                        boundary_strength=6.0,
                        convergence_threshold=0.5,
                        max_iterations=400,  # More iterations
                    )
                    opt_placer = PlacementEngine(opt_cfg)
                    opt_placer.place(board)

                    via_cost = max(10.0, 30.0 - opt_pass * 7)
                    opt_router = AutoRouter(RouterConfig(via_cost=via_cost))
                    all_routed, _ = opt_router.route(board)

                    unrouted = board.get_unrouted_nets()
                    unrouted_ratio = len(unrouted) / max(total_nets, 1)

                    self._emit(
                        AgentPhase.ROUTING_TRACES,
                        f"After optimisation pass {opt_pass + 1}: "
                        f"{len(unrouted)} unrouted "
                        f"({unrouted_ratio:.0%})",
                        progress=0.55 + opt_pass * 0.04,
                        board=board,
                    )

                    self._memory.add_note("LAYOUT",
                        f"Opt pass {opt_pass + 1}: attraction={strat['attraction']}, "
                        f"via_cost={via_cost}, unrouted={len(unrouted)}")

                    if all_routed:
                        self._chat("agent",
                                   "All nets routed after optimization!")
                        self._emit(
                            AgentPhase.ROUTING_TRACES,
                            "All nets routed after optimisation!",
                            progress=0.70,
                            board=board,
                        )
                        break

                if not all_routed:
                    self._memory.add_note("ERROR",
                        f"{len(board.get_unrouted_nets())} nets could not be routed. "
                        "Board may need to be larger or have fewer crossings.")
                    self._chat("agent",
                        f"Routing incomplete: {len(board.get_unrouted_nets())} "
                        f"nets unrouted")
                    self._emit(
                        AgentPhase.ROUTING_TRACES,
                        f"Routing incomplete: {len(board.get_unrouted_nets())} "
                        f"nets unrouted (DRC will flag these)",
                        progress=0.70,
                        board=board,
                    )

            self._update_task("Route traces", "done")

            if self._is_cancelled():
                return None

            # ── Task 6: DRC ───────────────────────────────────────
            self._update_task("Run DRC checks", "running")
            self._chat("task", "Running Design Rule Check...",
                       task_status="running")

            drc_passed = False
            drc_result = None
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
                        f"DRC PASSED! ({drc_result.warning_count} warnings, "
                        f"{drc_result.info_count} recommendations)",
                        progress=0.80,
                        board=board,
                    )
                    self._chat("agent",
                               f"DRC passed! ({drc_result.warning_count} warnings)")
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
                self._memory.add_note("ERROR",
                    f"DRC failed with {drc_result.error_count} errors after "
                    f"{self.config.max_drc_retries} fix attempts")
                self._emit(
                    AgentPhase.RUNNING_DRC,
                    "DRC has warnings but proceeding with output generation",
                    progress=0.80,
                    board=board,
                )

            if drc_result is not None:
                warn_detail = drc_result.warnings_detail()
                if warn_detail:
                    self._emit(
                        AgentPhase.RUNNING_DRC,
                        "Quality review -- issues to check before ordering:",
                        detail=warn_detail,
                        progress=0.81,
                        board=board,
                    )
                    self._chat("agent",
                               "Quality warnings found - see details",
                               detail=warn_detail)

            self._update_task("Run DRC checks", "done")

            # ── Task 7: Generate outputs ──────────────────────────
            self._update_task("Generate outputs", "running")
            self._chat("task", "Generating manufacturing files...",
                       task_status="running")

            self._emit(
                AgentPhase.GENERATING_OUTPUTS,
                "Generating manufacturing files...",
                progress=0.82,
            )

            output_dir = Path(self.config.output_dir) / _sanitize_name(board.name)
            generated_files = self._generate_outputs(board, output_dir)

            self._update_task("Generate outputs", "done")

            summary = board.summary()
            self._chat("agent",
                "Design complete!",
                detail=f"Generated {len(generated_files)} files in {output_dir}\n"
                + "\n".join(f"  {k}: {v}" for k, v in summary.items()))

            self._emit(
                AgentPhase.COMPLETE,
                "Design complete!",
                detail=f"Generated {len(generated_files)} files in {output_dir}\n\n"
                + "\n".join(f"  - {f}" for f in generated_files)
                + f"\n\nBoard summary:\n"
                + "\n".join(f"  {k}: {v}" for k, v in summary.items()),
                progress=1.0,
                board=board,
            )

            return board

        except Exception as e:
            self._chat("agent", f"Design failed: {e}",
                       task_status="failed")
            self._emit(
                AgentPhase.FAILED,
                f"Design failed: {e}",
                detail=str(e),
            )
            return None

    # ─── Helpers ─────────────────────────────────────────────────────────

    def edit(self, edit_request: str) -> Board | None:
        """Apply an incremental edit to the current board via LLM.

        This powers the chat-based editing flow: after the initial design
        is complete, the user can send follow-up requests like "move U1
        to the left", "add a second LED", "remove the debug header", etc.

        The LLM receives the current board state (components, nets,
        board size) and generates modification code that operates on the
        existing PCBDesign.

        Returns the updated board on success, or the original board on
        failure.
        """
        if self._board is None:
            self._emit(AgentPhase.FAILED, "No board to edit -- design one first.")
            return None

        if self.config.llm_provider in ("template", ""):
            self._emit(
                AgentPhase.ANALYZING,
                "Edit requires an LLM provider (OpenAI or Anthropic). "
                "Select one in the LLM dropdown.",
            )
            return self._board

        self._cancel_event.clear()
        self._emit(
            AgentPhase.ANALYZING,
            f"Editing board: {edit_request}",
            progress=0.05,
        )

        try:
            board = self._apply_edit_via_llm(edit_request)
            if board is None:
                self._emit(
                    AgentPhase.ANALYZING,
                    "Edit failed -- keeping original board.",
                )
                return self._board

            # Re-place, re-route, re-DRC
            self._emit(
                AgentPhase.PLACING_COMPONENTS,
                "Re-placing components after edit...",
                progress=0.30,
            )
            placer = PlacementEngine(PlacementConfig(seed=42))
            placer.place(board)

            self._emit(
                AgentPhase.ROUTING_TRACES,
                "Re-routing traces...",
                progress=0.50,
                board=board,
            )
            board.clear_routing()
            router = AutoRouter(RouterConfig(via_cost=30.0))
            all_routed, _ = router.route(board)
            self._emit(
                AgentPhase.ROUTING_TRACES,
                f"Routing {'complete' if all_routed else 'partial'}.",
                progress=0.65,
                board=board,
            )

            # Quick DRC
            drc_engine = DRCEngine()
            drc_result = drc_engine.check(board)
            if not drc_result.passed:
                self._emit(
                    AgentPhase.FIXING_ISSUES,
                    f"DRC: {drc_result.error_count} errors -- attempting fix...",
                    progress=0.75,
                )
                self._attempt_drc_fix(board, drc_result)
                board.clear_routing()
                router2 = AutoRouter(RouterConfig(via_cost=20.0))
                router2.route(board)

            self._board = board
            self._emit(
                AgentPhase.COMPLETE,
                "Edit applied successfully!",
                progress=1.0,
                board=board,
            )
            return board

        except Exception as e:
            self._emit(AgentPhase.FAILED, f"Edit failed: {e}")
            return self._board

    def _apply_edit_via_llm(self, edit_request: str) -> Board | None:
        """Send the current board state + edit request to the LLM."""
        board = self._board
        if board is None:
            return None

        # Build a description of the current board for the LLM
        comp_lines = []
        for c in board.components:
            comp_lines.append(
                f"  {c.reference}: {c.footprint.name} "
                f"value={c.value!r} pos=({c.position.x:.1f}, {c.position.y:.1f})"
            )
        net_lines = []
        for n in board.nets:
            pads = ", ".join(f"({r}, '{p}')" for r, p in n.pad_refs)
            net_lines.append(f"  {n.name}: [{pads}]")

        board_state = (
            f"Current board: {board.name}\n"
            f"Size: {board.settings.width}x{board.settings.height}mm\n"
            f"Components ({len(board.components)}):\n"
            + "\n".join(comp_lines)
            + f"\n\nNets ({len(board.nets)}):\n"
            + "\n".join(net_lines)
        )

        system_prompt = self._build_system_prompt()
        user_prompt = (
            f"You have an EXISTING board. The user wants to EDIT it.\n\n"
            f"{board_state}\n\n"
            f"User's edit request: {edit_request}\n\n"
            f"Generate COMPLETE Python code that recreates the board with "
            f"the requested changes applied. Keep all unchanged components "
            f"and nets. Use the PCBDesign DSL.\n"
            f"Output ONLY Python code ending with: board = pcb.build()"
        )

        provider = self.config.llm_provider
        api_key = self.config.api_key

        self._last_llm_code = ""
        self._last_llm_error = ""

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

                new_board = self._execute_llm_code(code)
                if new_board is not None:
                    return new_board

                # Feed error back
                error_msg = getattr(self, "_last_llm_error", "unknown")
                failed_code = getattr(self, "_last_llm_code", "")[:600]
                user_prompt = (
                    f"Your previous edit code FAILED: {error_msg}\n\n"
                    f"Failed code:\n```python\n{failed_code}\n```\n\n"
                    f"Fix and regenerate. Original edit request: {edit_request}\n"
                    f"Board state:\n{board_state}"
                )
                self._emit(
                    AgentPhase.ANALYZING,
                    f"Edit attempt {attempt + 1} failed: {error_msg}",
                    progress=0.10 + attempt * 0.05,
                )
            except Exception as e:
                self._emit(AgentPhase.ANALYZING, f"Edit attempt {attempt + 1}: {e}")
                continue

        return None

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

        Single-keyword matches are too aggressive -- "esp32" alone should
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

    def _create_custom_design(self, user_request: str,
                              iteration: int = 1) -> Board | None:
        """Use the DesignEngine to compose a custom board from the request.

        If the user explicitly selected an LLM provider (openai / anthropic),
        prefer the LLM path so the AI actually reasons about the design.
        Falls back to the algorithmic DesignEngine only when no LLM is
        configured or the LLM call fails.

        The ``iteration`` parameter tells the LLM which attempt this is,
        and injects self-notes from previous iterations for learning.

        Returns a fully-wired Board on success, or None if the request
        doesn't contain enough actionable detail for the engine.
        """
        # If the user explicitly chose an LLM provider, use it first
        if self.config.llm_provider not in ("template", ""):
            board = self._generate_from_llm(user_request, iteration=iteration)
            if board is not None:
                return board
            # LLM failed -- fall through to DesignEngine as a fallback
            self._emit(
                AgentPhase.ANALYZING,
                "LLM design failed, falling back to algorithmic engine...",
                progress=0.06,
            )
            self._memory.add_error("LLM design failed",
                "Algorithmic engine may produce simpler but more reliable designs")

        try:
            request = parse_request(user_request)

            # If the request is too vague (no features at all), nothing we can do
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

    def _validate_design(self, board: Board) -> int:
        """Run DesignValidator, log the quality score, and learn from issues.

        Returns the score (0-100) for the agentic loop to decide whether
        to iterate or accept.
        """
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

                # Learn from issues: write self-notes for critical problems
                for issue in score.issues:
                    if issue.severity == "critical":
                        self._memory.add_note(
                            "ERROR",
                            f"Critical: {issue.message}",
                            priority=3,
                        )
                    elif issue.severity == "warning":
                        self._memory.add_note(
                            "LAYOUT",
                            f"Warning: {issue.message}",
                            priority=1,
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
            return int(score.total)
        except Exception:
            return 50  # Unknown quality -- don't block the pipeline

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

    def _generate_from_llm(self, request: str,
                           iteration: int = 1) -> Board | None:
        """Use a thinking-capable LLM to design a novel PCB from scratch.

        The LLM receives the full PCBDesign DSL reference, all available
        footprints with pin maps, the subcircuit library, discoverable
        packages, physics rules, and self-notes from previous iterations.

        Supports OpenAI (o4-mini / gpt-4.1 / gpt-4o) and Anthropic.
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
            f"Using AI to design PCB (iteration {iteration})...",
            f"Provider: {provider}, model: {self.config.model or 'o4-mini'}",
            progress=0.04,
        )
        self._chat("agent",
                    f"Calling {provider} LLM for design (iteration {iteration})...")

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(request, iteration=iteration)

        # Try up to 3 iterations: generate → validate → feedback → retry
        self._last_llm_code = ""
        self._last_llm_error = ""
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

                board = self._execute_llm_code(code)
                if board is None:
                    # Code execution failed -- feed the error back to the
                    # LLM so it can self-correct on the next attempt
                    error_msg = getattr(self, "_last_llm_error", "unknown error")
                    failed_code = getattr(self, "_last_llm_code", "")[:600]
                    user_prompt = (
                        f"Your previous code FAILED with this error:\n"
                        f"  {error_msg}\n\n"
                        f"The failing code was:\n```python\n{failed_code}\n```\n\n"
                        f"IMPORTANT RULES:\n"
                        f"- Use pcb.subcircuit('name', pos=(x,y)) to place subcircuits "
                        f"(ldo_3v3, usb_c_power, esp32_minimal, etc.)\n"
                        f"- Reference designators must be STRINGS: 'R1', 'C1', not R + 1\n"
                        f"- Use pcb.place('ref', 'footprint', ...) for individual components\n"
                        f"- Use pcb.net('name', [(comp, 'pin'), ...]) for signal nets\n"
                        f"- Use pcb.power_net('name', [...]) for power nets (GND, 3V3, etc.)\n"
                        f"- The code MUST end with: board = pcb.build()\n\n"
                        f"Please fix the error and regenerate COMPLETE code.\n"
                        f"Original request: {request}"
                    )
                    self._emit(
                        AgentPhase.ANALYZING,
                        f"Code attempt {attempt + 1} failed: {error_msg}. "
                        f"Feeding error back to LLM...",
                        progress=0.04 + attempt * 0.02,
                    )
                    continue

                # Validate the LLM-generated board
                validator = DesignValidator()
                score = validator.validate(board)

                # Accept the design if it's feasible OR scores well enough.
                # LLM-generated designs with minor overlaps (score >= 65)
                # are still usable -- the DRC fix loop will clean them up.
                if score.is_feasible or score.total >= 65:
                    self._emit(
                        AgentPhase.CREATING_SCHEMATIC,
                        f"AI-designed board (score: {score.total:.0f}/100)",
                        detail=score.summary(),
                        progress=0.10,
                        board=board,
                    )
                    return board

                # Poor quality -- feed errors back to the LLM
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

        # Add discoverable packages info
        discovery_info = ""
        try:
            from ..components.discovery import list_discoverable_packages
            discovery_info = (
                "\n\n## Dynamic Component Discovery\n\n"
                "You can use ANY of these packages as footprint names in pcb.place().\n"
                "They will be auto-created at build time:\n\n"
                + list_discoverable_packages()
                + "\n\nYou are NOT limited to the built-in library! If you know a "
                "component's package type, use it directly (e.g., 'SOIC-8', 'QFN-24', "
                "'DIP-16', 'TSSOP-20'). The system will generate the correct footprint.\n"
            )
        except ImportError:
            pass

        # Get subcircuit library info if available
        subcircuit_info = ""
        try:
            from .subcircuits import list_subcircuits
            subcircuit_info = (
                "\n\n## Subcircuit Convenience Method (PREFERRED)\n\n"
                "Use `pcb.subcircuit()` to place pre-built circuit blocks.\n"
                "No imports needed, ref numbering is automatic.\n\n"
                "```python\n"
                "# Place subcircuits -- returns a dict of PlacedComponents\n"
                "pwr = pcb.subcircuit('usb_c_power', pos=(35, 5))\n"
                "# pwr keys: 'usb', 'c_filter1', 'c_filter2'\n"
                "\n"
                "ldo = pcb.subcircuit('ldo_3v3', pos=(55, 10))\n"
                "# ldo keys: 'ldo', 'c_in', 'c_out'\n"
                "\n"
                "mcu = pcb.subcircuit('esp32_minimal', pos=(35, 30))\n"
                "# mcu keys: 'esp32', 'c_byp1', 'c_byp2', 'r_en', 'r_io0', "
                "'btn_reset', 'btn_boot'\n"
                "\n"
                "sensor = pcb.subcircuit('i2c_sensor_breakout', pos=(20, 40))\n"
                "# sensor keys: 'header', 'r_sda', 'r_scl'\n"
                "\n"
                "led1 = pcb.subcircuit('led_with_resistor', pos=(60, 40), color='green')\n"
                "# led1 keys: 'resistor', 'led'\n"
                "\n"
                "dbg = pcb.subcircuit('debug_header', pos=(70, 50))\n"
                "# dbg keys: 'header'\n"
                "\n"
                "holes = pcb.subcircuit('mounting_holes_corners', pos=(0,0))\n"
                "# holes keys: 'hole_tl', 'hole_tr', 'hole_br', 'hole_bl'\n"
                "```\n\n"
                "**CRITICAL: Accessing return dict keys**\n"
                "The dict keys are component NAMES, NOT net names!\n"
                "```python\n"
                "# CORRECT -- use component key names from the dict:\n"
                "pcb.power_net('VBUS', [(pwr['usb'], 'A4'), (ldo['ldo'], '1')])\n"
                "pcb.power_net('3V3', [(ldo['ldo'], '3'), (mcu['esp32'], '2')])\n"
                "pcb.net('SDA', [(mcu['esp32'], '33'), (sensor['header'], '3')])\n"
                "pcb.net('LED_GPIO', [(mcu['esp32'], '8'), (led1['resistor'], '1')])\n"
                "\n"
                "# WRONG -- these are net names, NOT dict keys:\n"
                "# ldo['3V3']  <-- KeyError! Use ldo['ldo'] instead\n"
                "# sensor['sensor']  <-- KeyError! Use sensor['header'] instead\n"
                "# mcu['3V3']  <-- KeyError! Use mcu['esp32'] instead\n"
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

BarrelJack_DC (DC power input):
  1=Tip(VIN+), 2=Sleeve(GND), 3=Switch(NC)

Relay_SPDT (5V relay):
  1=Coil+, 2=Coil-, 3=COM, 4=NO, 5=NC

SOD-123 (diode):
  K=Cathode, A=Anode

DPAK_TO252 (power MOSFET):
  1=Gate, 2=Drain(tab), 3=Source

DIP-8 (through-hole IC):
  1-4=left side (top to bottom), 5-8=right side (bottom to top)

TO-220 (power package):
  1=Pin1, 2=Pin2, 3=Pin3

Sensor_I2C_4pin: 1=VCC, 2=GND, 3=SDA, 4=SCL
Sensor_SPI_6pin: 1=VCC, 2=GND, 3=SCK, 4=MOSI, 5=MISO, 6=CS
{subcircuit_info}
{discovery_info}

## Component Categories -- Use These Directly with pcb.place()

**Passives** (pins: 1, 2):
  R_0402, R_0603, R_0805 - Resistors
  C_0402, C_0603, C_0805 - Capacitors
  L_0805 - Inductor

**LEDs** (pins: 1=Anode, 2=Cathode):
  LED_0603, LED_0805

**Diodes** (pins: K=Cathode, A=Anode):
  SOD-123 - Schottky / signal diode

**Addressable LEDs** (pins: 1=VDD, 2=DOUT, 3=GND, 4=DIN):
  WS2812B

**Transistors / MOSFETs**:
  SOT-23-3 - pins: 1=Base/Gate, 2=Emitter/Source, 3=Collector/Drain
  SOT-89 - pins: 1, 2, 3
  DPAK_TO252 - pins: 1=Gate, 2=Drain(tab), 3=Source
  TO-220 - pins: 1, 2, 3

**Voltage Regulators**:
  SOT-223 - pins: 1=Input, 2=Ground, 3=Output

**ICs**:
  ESP32-WROOM-32 - 39-pin WiFi/BT MCU
  QFP-48 - generic 48-pin IC (STM32, etc.)
  SOIC-8 - 8-pin SPI flash, op-amp, etc. (pins: 1-8)
  DIP-8 - through-hole 8-pin IC (pins: 1-8)

**Connectors**:
  USB_C_16pin - USB-C (A1=GND,A4=VBUS,A6=D+,A7=D-,B1=GND,B4=VBUS,...)
  USB_Micro_B - USB Micro-B (1=VBUS,2=D-,3=D+,4=ID,5=GND)
  BarrelJack_DC - DC jack (1=Tip/VIN, 2=Sleeve/GND, 3=Switch)
  PinHeader_1x02 through PinHeader_1x19 - pin headers (pins: 1,2,3,...)
  PinHeader_2x03, 2x05, 2x10 - dual-row headers
  ScrewTerminal_2P, 3P - screw terminals (pins: 1,2 or 1,2,3)

**Storage / Display**:
  MicroSD_Socket - pins: 1-9 (CS=1, MOSI=2, VSS=3, VDD=4, CLK=5, VSS2=6, DO=7)
  OLED_SSD1306 - 4-pin I2C OLED (1=GND, 2=VCC, 3=SCL, 4=SDA)
  FPC_8pin, FPC_24pin, FPC_40pin - flat-flex connectors

**Switches / Relays**:
  SW_Push_6mm - tactile switch (1,2=side A, 3,4=side B)
  SW_Push_SMD - SMD pushbutton (1,2)
  Relay_SPDT - 5V relay (1=Coil+, 2=Coil-, 3=COM, 4=NO, 5=NC)

**Oscillators**:
  Crystal_3215 - 32.768kHz crystal (1, 2)

**Sensor Headers**:
  Sensor_I2C_4pin -- 1=VCC, 2=GND, 3=SDA, 4=SCL
  Sensor_SPI_6pin -- 1=VCC, 2=GND, 3=SCK, 4=MOSI, 5=MISO, 6=CS

**Mounting**:
  MountingHole_M3, MountingHole_M2.5 -- (pin: 1)

Example -- OLED display with I2C:
```python
oled = pcb.place("U2", "OLED_SSD1306", value="SSD1306", pos=(30, 35))
pcb.power_net("3V3", [(mcu, "2"), (oled, "2")])
pcb.power_net("GND", [(mcu, "1"), (oled, "1")])
pcb.net("I2C_SCL", [(mcu, "36"), (oled, "3")])
pcb.net("I2C_SDA", [(mcu, "33"), (oled, "4")])
```

Example -- MicroSD card reader:
```python
sd = pcb.place("J2", "MicroSD_Socket", value="MicroSD", pos=(50, 30))
pcb.net("SD_CS", [(mcu, "29"), (sd, "1")])
pcb.net("SD_MOSI", [(mcu, "37"), (sd, "2")])
pcb.net("SD_CLK", [(mcu, "30"), (sd, "5")])
pcb.net("SD_MISO", [(mcu, "31"), (sd, "7")])
```

Example -- MOSFET motor driver:
```python
q1 = pcb.place("Q1", "SOT-23-3", value="2N7002", pos=(45, 30))
r_gate = pcb.place("R5", "R_0603", value="100", pos=(42, 28))
r_pull = pcb.place("R6", "R_0603", value="10k", pos=(42, 32))
pcb.net("MOTOR_GATE", [(r_gate, "2"), (q1, "1")])
pcb.net("MOTOR_CTRL", [(mcu, "8"), (r_gate, "1")])
pcb.power_net("GND", [(q1, "2"), (r_pull, "2")])
pcb.net("MOTOR_GATE", [(r_pull, "1"), (q1, "1")])
```

## Design Rules (CRITICAL)

1. EVERY IC must have at least one 100nF bypass cap within 5mm
2. EVERY IC must be connected to power AND ground nets
3. Use power_net() for GND, VCC, 3V3, 5V, VBUS (wider traces)
4. Use net() for signal connections (standard traces)
5. Place USB/barrel jack connectors at board edges (y < 10mm from top)
6. ALL components must fit inside board boundaries with 3mm margin
7. Space components at least 2mm apart to avoid overlaps
8. Include pull-up resistors on EN/RESET pins (10k to 3V3)
9. Include current-limiting resistors for LEDs (330-1k ohm)
10. Include input AND output capacitors for voltage regulators
11. Reference designator prefixes: U=IC, R=Resistor, C=Capacitor,
    D=Diode/LED, J=Connector, SW=Switch, H=Mounting Hole, L=Inductor,
    Q=Transistor/MOSFET, K=Relay
12. For relays: include a flyback diode (SOD-123) and NPN driver
    transistor (SOT-23-3) -- never drive relay coil from GPIO directly
13. For power MOSFETs: include gate resistor (100 ohm) + pull-down (10k)
14. For I2C: include 4.7k pull-ups on SDA and SCL
15. For barrel jacks: include polarity-protection Schottky diode

## Layout Guidelines

- Board origin is top-left (0,0)
- **SIZE THE BOARD COMPACT** -- don't waste space.  Typical boards:
  - Simple sensor board: 40x30mm
  - ESP32 + a few peripherals: 50x40mm
  - Complex multi-feature: 70x55mm
- Connectors go at edges: USB at top center, headers on right
- Main IC centered: pos=(width/2, 20-30)
- Passives within 3mm of their IC (decoupling caps < 3mm!)
- Power section near USB / barrel jack connector
- Leave 3mm margin from all edges

Output ONLY the Python code, no explanations. The code MUST end with:
board = pcb.build()
"""

    def _build_user_prompt(self, request: str,
                           iteration: int = 1) -> str:
        # Include physics rules and self-notes from memory
        notes_section = self._memory.get_notes_for_prompt()

        iteration_context = ""
        if iteration > 1:
            iteration_context = (
                f"\n\n## ITERATION {iteration} - LEARNING FROM PREVIOUS ATTEMPTS\n"
                f"This is attempt #{iteration}. The previous designs had issues.\n"
                f"Review the notes below carefully and AVOID the same mistakes.\n"
                f"Be more creative with component choices and layout.\n"
            )

        return (
            f"Design a complete, manufacturable PCB for this request:\n\n"
            f"{request}\n\n"
            f"{notes_section}\n"
            f"{iteration_context}\n"
            f"Think carefully about:\n"
            f"1. What components are needed (MCU, power, sensors, connectors)\n"
            f"2. Proper power distribution (regulators, decoupling) - FOLLOW PHYSICS\n"
            f"3. Signal connections and pin assignments - VERIFY EACH PIN\n"
            f"4. Physical layout and component spacing (min 2mm between components)\n"
            f"5. Board size that fits everything with routing room\n"
            f"6. Current calculations for LEDs, motors, relays\n"
            f"7. Voltage levels and level-shifting where needed\n"
            f"8. EMI/EMC: bypass caps, ground planes, short return paths\n\n"
            f"You may use ANY component from the dynamic discovery library.\n"
            f"If you know the right part, use it! Don't limit yourself to the\n"
            f"built-in components.\n\n"
            f"Generate complete Python code using the PCBDesign DSL.\n"
            f"Include ALL necessary support components.\n"
            f"Output ONLY the Python code."
        )

    @staticmethod
    def _sanitize_prompt(text: str) -> str:
        """Strip non-ASCII characters that can crash some API clients.

        Replaces em/en dashes, non-breaking spaces, curly quotes, and
        any other non-ASCII codepoints with safe ASCII equivalents.
        """
        replacements = {
            "\u2014": "--",  # em dash
            "\u2013": "-",   # en dash
            "\u00a0": " ",   # non-breaking space
            "\u2018": "'",   # left single quote
            "\u2019": "'",   # right single quote
            "\u201c": '"',   # left double quote
            "\u201d": '"',   # right double quote
            "\u2026": "...", # ellipsis
        }
        for char, replacement in replacements.items():
            text = text.replace(char, replacement)
        # Final pass: replace any remaining non-ASCII with '?'
        return text.encode("ascii", "replace").decode("ascii")

    # Known OpenAI reasoning/thinking model prefixes -- these use a single
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

        Default model: ``o4-mini`` -- an affordable reasoning model
        that thinks through circuit physics before generating code.

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
        model = self.config.model or "o4-mini"

        # Sanitize prompts to avoid UnicodeEncodeError with some API clients
        system_prompt = self._sanitize_prompt(system_prompt)
        user_prompt = self._sanitize_prompt(user_prompt)

        self._emit(
            AgentPhase.ANALYZING,
            f"Calling {model} for PCB design...",
            progress=0.04,
        )

        try:
            if self._is_thinking_model(model):
                # Thinking / reasoning models don't support system messages
                # or temperature -- combine into one user message.
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
                f"OpenAI authentication failed -- check your API key.",
            )
            return None
        except openai.RateLimitError:
            self._emit(
                AgentPhase.ANALYZING,
                f"OpenAI rate limit hit -- try again in a moment.",
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

        # Sanitize prompts to avoid encoding issues
        system_prompt = self._sanitize_prompt(system_prompt)
        user_prompt = self._sanitize_prompt(user_prompt)

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
                "Anthropic authentication failed -- check your API key.",
            )
            return None
        except anthropic.RateLimitError:
            self._emit(
                AgentPhase.ANALYZING,
                "Anthropic rate limit hit -- try again in a moment.",
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

    def _sanitize_llm_code(self, code: str) -> str:
        """Apply common fixes to LLM-generated Python code.

        LLMs frequently make predictable mistakes when writing DSL code.
        This method patches the most common ones so more designs succeed
        on the first attempt.
        """
        import re

        # Extract code from ```python ... ``` fences if present
        fence_match = re.search(
            r"```(?:python)?\s*\n(.*?)```", code, re.DOTALL
        )
        if fence_match:
            code = fence_match.group(1)

        # Strip import lines that would fail inside exec
        code = re.sub(
            r"^\s*from\s+\S*(?:pcb_dsl|subcircuits|ai_pcb_designer)\s+import\s+.*$",
            "",
            code,
            flags=re.MULTILINE,
        )
        code = re.sub(
            r"^\s*import\s+\S*(?:pcb_dsl|subcircuits|ai_pcb_designer)\s*$",
            "",
            code,
            flags=re.MULTILINE,
        )

        # Fix string + int concatenation: "R" + ref_start → f"R{ref_start}"
        # Common pattern: "X" + variable  →  "X" + str(variable)
        code = re.sub(
            r'("[A-Za-z_]+?")\s*\+\s*(\w+)',
            r'\1 + str(\2)',
            code,
        )

        # Fix f-string inside f-string issues: some LLMs double-format
        # Nothing to do here for now

        # Fix pcb.add_component(...) → pcb.place(...)
        code = re.sub(
            r'(\w+)\.add_component\s*\(',
            r'\1.place(',
            code,
        )

        # Fix pcb.add_net(...) → pcb.net(...)
        code = re.sub(
            r'(\w+)\.add_net\s*\(',
            r'\1.net(',
            code,
        )

        # Fix pcb.add_power_net(...) → pcb.power_net(...)
        code = re.sub(
            r'(\w+)\.add_power_net\s*\(',
            r'\1.power_net(',
            code,
        )

        return code

    def _execute_llm_code(self, code: str) -> Board | None:
        """Execute Python DSL code generated by an LLM and return the Board.

        Extracts Python code from markdown fences if present, applies
        common sanitization fixes, then executes it in a clean namespace
        with the PCBDesign class and subcircuit functions available.

        Returns the Board on success, or None on failure.
        """
        from .pcb_dsl import PCBDesign

        code = self._sanitize_llm_code(code)
        self._last_llm_code = code  # save for error feedback

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
            import traceback
            # Extract the line number from the traceback for better feedback
            tb = traceback.extract_tb(exc.__traceback__)
            line_info = ""
            for frame in tb:
                if frame.filename == "<string>":
                    line_info = f" (line {frame.lineno})"
                    break
            error_type = type(exc).__name__
            self._last_llm_error = (
                f"{error_type}: {exc}{line_info}"
            )
            self._emit(
                AgentPhase.ANALYZING,
                f"LLM-generated code execution failed: "
                f"{error_type}: {exc}{line_info}",
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
                self._last_llm_error = str(exc)
                self._emit(
                    AgentPhase.ANALYZING,
                    f"PCBDesign.build() failed: {exc}",
                    detail=code[:500],
                )
                return None

        self._last_llm_error = "Code did not produce 'board' or 'pcb' variable"
        self._emit(
            AgentPhase.ANALYZING,
            "LLM code did not produce a 'board' or 'pcb' variable",
            detail=code[:300],
        )
        return None

    # ─── DRC Fix ─────────────────────────────────────────────────────────

    def _attempt_drc_fix(self, board: Board, drc_result: DRCResult) -> None:
        """Attempt to fix DRC violations with targeted adjustments.

        Handles overlaps, edge clearance, courtyard conflicts, and
        unrouted / partially-routed nets.  When many nets remain
        unrouted, the router is re-run with progressively lower via
        cost so it can use both layers more freely.
        """
        bw = board.settings.width
        bh = board.settings.height
        margin = board.settings.design_rules.edge_clearance + 1.5

        moved = False  # track whether placement was adjusted

        # Count unrouted / partially routed to decide re-route strategy
        unrouted_count = sum(
            1 for v in drc_result.violations
            if v.violation_type in (
                DRCViolationType.UNCONNECTED_NET,
                DRCViolationType.PARTIALLY_ROUTED_NET,
            )
        )

        for violation in drc_result.violations:
            if violation.violation_type == DRCViolationType.OVERLAP:
                refs = violation.component_refs
                if len(refs) == 2:
                    c1 = board.get_component(refs[0])
                    c2 = board.get_component(refs[1])
                    if c1 and c2:
                        dx = c1.position.x - c2.position.x
                        dy = c1.position.y - c2.position.y
                        dist = max(math.hypot(dx, dy), 0.1)
                        push = min(2.5, max(1.0, dist * 0.4))
                        nx, ny = dx / dist, dy / dist
                        c1.position = Point(
                            max(margin, min(bw - margin,
                                c1.position.x + push * nx)),
                            max(margin, min(bh - margin,
                                c1.position.y + push * ny)),
                        )
                        c2.position = Point(
                            max(margin, min(bw - margin,
                                c2.position.x - push * nx)),
                            max(margin, min(bh - margin,
                                c2.position.y - push * ny)),
                        )
                        moved = True

            elif violation.violation_type in (
                DRCViolationType.EDGE_CLEARANCE,
                DRCViolationType.VIA_EDGE_CLEARANCE,
            ):
                for ref in violation.component_refs:
                    comp = board.get_component(ref)
                    if comp:
                        cp = comp.position
                        new_x = max(margin, min(bw - margin, cp.x))
                        new_y = max(margin, min(bh - margin, cp.y))
                        if new_x != cp.x or new_y != cp.y:
                            comp.position = Point(new_x, new_y)
                            moved = True

            elif violation.violation_type == DRCViolationType.COURTYARD_CONFLICT:
                # Push conflicting components apart (same as overlap)
                refs = violation.component_refs
                if len(refs) == 2:
                    c1 = board.get_component(refs[0])
                    c2 = board.get_component(refs[1])
                    if c1 and c2:
                        dx = c1.position.x - c2.position.x
                        dy = c1.position.y - c2.position.y
                        dist = max(math.hypot(dx, dy), 0.1)
                        push = 1.0
                        nx, ny = dx / dist, dy / dist
                        c1.position = Point(
                            max(margin, min(bw - margin,
                                c1.position.x + push * nx)),
                            max(margin, min(bh - margin,
                                c1.position.y + push * ny)),
                        )
                        c2.position = Point(
                            max(margin, min(bw - margin,
                                c2.position.x - push * nx)),
                            max(margin, min(bh - margin,
                                c2.position.y - push * ny)),
                        )
                        moved = True

        # Re-route after placement changes.  If many nets are unrouted
        # lower the via cost progressively so the router can use both
        # layers more aggressively.
        board.clear_routing()

        via_cost = 40.0  # default
        if unrouted_count > 5:
            via_cost = 20.0  # desperate: allow vias freely
        elif unrouted_count > 0:
            via_cost = 30.0  # moderate: ease via restriction

        router_cfg = RouterConfig(via_cost=via_cost)
        router = AutoRouter(router_cfg)
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
