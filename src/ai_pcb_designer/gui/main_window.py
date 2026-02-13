"""Main application window for AI PCB Designer.

Features:
- Natural language input for board description
- Real-time PCB renderer showing the AI's work
- Step-by-step log panel showing agent decisions
- Layer visibility controls
- Template quick-select
- Output file browser
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal, QObject, Slot, QTimer
from PySide6.QtGui import QFont, QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QMessageBox,
)

from ..ai.agent import AgentConfig, AgentPhase, AgentStep, PCBDesignAgent
from ..components.templates import list_templates
from .renderer import PCBGraphicsView


class StepSignal(QObject):
    """Signal bridge for cross-thread step updates."""
    step_received = Signal(object)  # AgentStep


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AI PCB Designer — Autonomous PCB Design Tool")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)

        self._agent: PCBDesignAgent | None = None
        self._design_thread: threading.Thread | None = None
        self._step_signal = StepSignal()
        self._step_signal.step_received.connect(self._on_agent_step)

        self._setup_ui()
        self._setup_menubar()
        self._setup_toolbar()
        self._update_status("Ready. Enter a board description and click 'Design!'")

    # ─── UI Setup ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """Build the main UI layout."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Main splitter: renderer on left, panels on right
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Left: PCB Renderer
        self._renderer = PCBGraphicsView()
        splitter.addWidget(self._renderer)

        # Right: Control panels
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)

        # Input section
        input_group = QGroupBox("Board Description")
        input_layout = QVBoxLayout(input_group)

        self._input_text = QTextEdit()
        self._input_text.setPlaceholderText(
            "Describe the PCB you want to create...\n\n"
            "Examples:\n"
            "• Make me a carrier board for an ESP32 with USB-C, "
            "power LED, and GPIO breakout headers\n"
            "• Create a simple LED blinker circuit\n"
            "• Design an I2C sensor breakout board"
        )
        self._input_text.setMaximumHeight(120)
        input_layout.addWidget(self._input_text)

        # Template quick-select
        template_row = QHBoxLayout()
        template_row.addWidget(QLabel("Template:"))
        self._template_combo = QComboBox()
        self._template_combo.addItem("(Auto-detect from description)", "")
        for tmpl in list_templates():
            self._template_combo.addItem(tmpl["name"], tmpl["name"])
        template_row.addWidget(self._template_combo)
        input_layout.addLayout(template_row)

        # API config row
        api_row = QHBoxLayout()
        api_row.addWidget(QLabel("LLM:"))
        self._llm_combo = QComboBox()
        self._llm_combo.addItems(["Template Mode (no API)", "OpenAI", "Anthropic"])
        api_row.addWidget(self._llm_combo)
        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("API Key (optional)")
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        api_row.addWidget(self._api_key_input)
        input_layout.addLayout(api_row)

        # Design button
        btn_row = QHBoxLayout()
        self._design_btn = QPushButton("🔧  Design PCB")
        self._design_btn.setMinimumHeight(40)
        self._design_btn.setStyleSheet(
            "QPushButton { background-color: #2d8c3c; color: white; "
            "font-size: 14px; font-weight: bold; border-radius: 6px; }"
            "QPushButton:hover { background-color: #3aa64d; }"
            "QPushButton:disabled { background-color: #555; color: #999; }"
        )
        self._design_btn.clicked.connect(self._on_design_clicked)
        btn_row.addWidget(self._design_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.setMinimumHeight(40)
        btn_row.addWidget(self._stop_btn)
        input_layout.addLayout(btn_row)

        right_layout.addWidget(input_group)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        right_layout.addWidget(self._progress_bar)

        # Step log
        log_group = QGroupBox("AI Agent Steps")
        log_layout = QVBoxLayout(log_group)
        self._step_log = QPlainTextEdit()
        self._step_log.setReadOnly(True)
        self._step_log.setFont(QFont("Monospace", 9))
        self._step_log.setStyleSheet(
            "QPlainTextEdit { background-color: #1a1a2e; color: #eee; }"
        )
        log_layout.addWidget(self._step_log)
        right_layout.addWidget(log_group)

        # Layer controls
        layer_group = QGroupBox("Layer Visibility")
        layer_layout = QVBoxLayout(layer_group)
        self._layer_checkboxes: dict[str, QCheckBox] = {}

        layer_names = {
            "board": "Board Outline",
            "f_cu": "Front Copper (red)",
            "b_cu": "Back Copper (blue)",
            "f_silk": "Front Silkscreen",
            "pads": "Pads",
            "vias": "Vias",
            "traces": "Traces",
            "ratsnest": "Ratsnest (unrouted)",
            "refs": "Reference Labels",
            "courtyard": "Courtyards",
            "grid": "Grid",
        }

        for key, label in layer_names.items():
            cb = QCheckBox(label)
            cb.setChecked(self._renderer.layer_visibility.get(key, True))
            cb.toggled.connect(lambda checked, k=key: self._on_layer_toggled(k, checked))
            layer_layout.addWidget(cb)
            self._layer_checkboxes[key] = cb

        right_layout.addWidget(layer_group)

        # Board info
        self._board_info = QLabel("No board loaded")
        self._board_info.setWordWrap(True)
        right_layout.addWidget(self._board_info)

        splitter.addWidget(right_panel)
        splitter.setSizes([900, 500])

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

    def _setup_menubar(self) -> None:
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")
        file_menu.addAction("Export Gerbers...", self._export_gerbers)
        file_menu.addAction("Export KiCad...", self._export_kicad)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        # View menu
        view_menu = menubar.addMenu("View")
        view_menu.addAction("Fit Board", self._renderer.fit_board)
        view_menu.addAction("Reset View", self._reset_view)

        # Help menu
        help_menu = menubar.addMenu("Help")
        help_menu.addAction("About", self._show_about)

    def _setup_toolbar(self) -> None:
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toolbar.addAction("Fit View", self._renderer.fit_board)
        toolbar.addSeparator()
        toolbar.addAction("Export All", self._export_all)

    # ─── Event Handlers ─────────────────────────────────────────────────

    def _on_design_clicked(self) -> None:
        """Start the autonomous design process."""
        description = self._input_text.toPlainText().strip()
        if not description:
            # Check if a template is selected
            template_name = self._template_combo.currentData()
            if template_name:
                description = template_name
            else:
                QMessageBox.information(
                    self, "Input Needed",
                    "Please enter a description of the PCB you want to create."
                )
                return

        # Clear previous state
        self._step_log.clear()
        self._progress_bar.setValue(0)
        self._design_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)

        # Configure agent
        llm_idx = self._llm_combo.currentIndex()
        providers = ["template", "openai", "anthropic"]
        config = AgentConfig(
            llm_provider=providers[llm_idx],
            api_key=self._api_key_input.text().strip(),
            output_dir="./output",
        )

        self._agent = PCBDesignAgent(config)
        self._agent.set_step_callback(
            lambda step: self._step_signal.step_received.emit(step)
        )

        # Run design in background thread
        self._design_thread = threading.Thread(
            target=self._run_design,
            args=(description,),
            daemon=True,
        )
        self._design_thread.start()

    def _run_design(self, description: str) -> None:
        """Run the design pipeline in a background thread."""
        if self._agent:
            self._agent.design(description)

    @Slot(object)
    def _on_agent_step(self, step: AgentStep) -> None:
        """Handle agent step update on the main thread."""
        # Update progress bar
        self._progress_bar.setValue(int(step.progress * 100))

        # Update step log
        phase_icon = {
            AgentPhase.ANALYZING: "[ANALYZE]",
            AgentPhase.SELECTING_COMPONENTS: "[COMPONENTS]",
            AgentPhase.CREATING_SCHEMATIC: "[SCHEMATIC]",
            AgentPhase.PLACING_COMPONENTS: "[PLACEMENT]",
            AgentPhase.ROUTING_TRACES: "[ROUTING]",
            AgentPhase.RUNNING_DRC: "[DRC]",
            AgentPhase.FIXING_ISSUES: "[FIX]",
            AgentPhase.GENERATING_OUTPUTS: "[OUTPUT]",
            AgentPhase.COMPLETE: "[DONE]",
            AgentPhase.FAILED: "[FAIL]",
        }.get(step.phase, "[???]")

        self._step_log.appendPlainText(f"{phase_icon} {step.message}")
        if step.detail:
            for line in step.detail.split("\n")[:5]:
                self._step_log.appendPlainText(f"       {line}")

        # Auto-scroll to bottom
        scrollbar = self._step_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        # Update renderer if board snapshot available
        if step.board_snapshot:
            self._renderer.render_board(step.board_snapshot)
            if step.phase in (AgentPhase.CREATING_SCHEMATIC, AgentPhase.COMPLETE):
                QTimer.singleShot(100, self._renderer.fit_board)

            # Update board info
            summary = step.board_snapshot.summary()
            info = "\n".join(f"{k}: {v}" for k, v in summary.items())
            self._board_info.setText(info)

        # Update status
        self._update_status(step.message)

        # Re-enable button when done
        if step.phase in (AgentPhase.COMPLETE, AgentPhase.FAILED):
            self._design_btn.setEnabled(True)
            self._stop_btn.setEnabled(False)

    def _on_layer_toggled(self, layer_name: str, checked: bool) -> None:
        self._renderer.set_layer_visible(layer_name, checked)

    def _reset_view(self) -> None:
        self._renderer.resetTransform()
        self._renderer.fit_board()

    def _export_gerbers(self) -> None:
        if not self._agent or not self._agent.board:
            QMessageBox.information(self, "No Board", "Design a board first.")
            return
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            from ..exporters.gerber import GerberExporter
            files = GerberExporter(self._agent.board).export(dir_path)
            QMessageBox.information(
                self, "Export Complete",
                f"Generated {len(files)} Gerber files in {dir_path}"
            )

    def _export_kicad(self) -> None:
        if not self._agent or not self._agent.board:
            QMessageBox.information(self, "No Board", "Design a board first.")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save KiCad File", "", "KiCad PCB (*.kicad_pcb)"
        )
        if file_path:
            from ..exporters.kicad import KiCadExporter
            KiCadExporter(self._agent.board).export(file_path)
            QMessageBox.information(self, "Export Complete", f"Saved to {file_path}")

    def _export_all(self) -> None:
        if not self._agent or not self._agent.board:
            QMessageBox.information(self, "No Board", "Design a board first.")
            return
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            from ..exporters.gerber import GerberExporter
            from ..exporters.bom import BOMExporter, PickAndPlaceExporter
            from ..exporters.kicad import KiCadExporter

            board = self._agent.board
            files = []
            files.extend(GerberExporter(board).export(Path(dir_path) / "gerbers"))
            files.append(BOMExporter(board).export(Path(dir_path) / "BOM.csv"))
            files.append(
                PickAndPlaceExporter(board).export(Path(dir_path) / "PickAndPlace.csv")
            )
            files.append(
                KiCadExporter(board).export(Path(dir_path) / f"{board.name}.kicad_pcb")
            )
            QMessageBox.information(
                self, "Export Complete",
                f"Generated {len(files)} files in {dir_path}"
            )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About AI PCB Designer",
            "AI PCB Designer v0.1.0\n\n"
            "Autonomous PCB design tool powered by AI.\n"
            "Designed for people with no PCB experience.\n\n"
            "Phase 1: Simple boards (ESP32 carrier, LED blinker, etc.)\n\n"
            "Generates manufacturing-ready output:\n"
            "- Gerber files (RS-274X)\n"
            "- Excellon drill files\n"
            "- Bill of Materials (BOM)\n"
            "- Pick-and-Place files\n"
            "- KiCad .kicad_pcb files",
        )

    def _update_status(self, message: str) -> None:
        self._status_bar.showMessage(message)
