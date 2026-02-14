"""Main application window for AI PCB Designer - Phase 5 (Chat-First Agentic UI).

Chat-first interface inspired by Claude Code:
- Central chat panel showing agent's thinking and progress
- Real-time task list with status indicators
- User can intervene mid-design by typing in the chat
- PCB renderer updates live as the AI works
- Modern dark theme with clean typography

All previous features preserved:
- Template quick-select
- Board size configuration
- LLM provider selection
- Layer visibility controls
- Export (Gerber, KiCad, BOM, PnP)
- 3D viewer
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal, QObject, Slot, QTimer, QSize
from PySide6.QtGui import QFont, QAction, QIcon, QColor, QPalette, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDockWidget,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QMessageBox,
)

from ..ai.agent import (
    AgentConfig, AgentPhase, AgentStep, ChatMessage, PCBDesignAgent,
)
from ..components.templates import list_templates
from .renderer import PCBGraphicsView


# ── Theme Colors ─────────────────────────────────────────────────────────────

_COLORS = {
    "bg": "#0d1117",
    "bg_secondary": "#161b22",
    "bg_chat": "#0d1117",
    "bg_input": "#21262d",
    "bg_task": "#161b22",
    "border": "#30363d",
    "text": "#e6edf3",
    "text_dim": "#8b949e",
    "text_bright": "#f0f6fc",
    "accent": "#58a6ff",
    "accent_hover": "#79c0ff",
    "green": "#3fb950",
    "green_dim": "#238636",
    "red": "#f85149",
    "red_dim": "#da3633",
    "yellow": "#d29922",
    "orange": "#db6d28",
    "purple": "#bc8cff",
    "agent_msg": "#1f2937",
    "user_msg": "#0c2d48",
    "system_msg": "#1c1917",
}


class StepSignal(QObject):
    """Signal bridge for cross-thread step updates."""
    step_received = Signal(object)  # AgentStep
    chat_received = Signal(object)  # ChatMessage
    design_finished = Signal(object)  # Board or None


class MainWindow(QMainWindow):
    """Chat-first main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AI PCB Designer")
        self.setMinimumSize(1200, 800)
        self.resize(1500, 950)

        self._agent: PCBDesignAgent | None = None
        self._design_thread: threading.Thread | None = None
        self._step_signal = StepSignal()
        self._step_signal.step_received.connect(self._on_agent_step)
        self._step_signal.chat_received.connect(self._on_chat_message)
        self._step_signal.design_finished.connect(self._on_design_finished)

        self._apply_theme()
        self._setup_ui()
        self._setup_menubar()
        self._update_status("Ready")

    # ─── Theme ───────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        """Apply a modern dark theme."""
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {_COLORS['bg']};
                color: {_COLORS['text']};
            }}
            QWidget {{
                background-color: {_COLORS['bg']};
                color: {_COLORS['text']};
                font-family: 'Segoe UI', 'SF Pro Display', 'Inter', sans-serif;
                font-size: 13px;
            }}
            QMenuBar {{
                background-color: {_COLORS['bg_secondary']};
                color: {_COLORS['text']};
                border-bottom: 1px solid {_COLORS['border']};
                padding: 4px;
            }}
            QMenuBar::item:selected {{
                background-color: {_COLORS['bg_input']};
                border-radius: 4px;
            }}
            QMenu {{
                background-color: {_COLORS['bg_secondary']};
                color: {_COLORS['text']};
                border: 1px solid {_COLORS['border']};
                border-radius: 8px;
                padding: 4px;
            }}
            QMenu::item:selected {{
                background-color: {_COLORS['accent']};
                color: {_COLORS['bg']};
                border-radius: 4px;
            }}
            QSplitter::handle {{
                background-color: {_COLORS['border']};
                width: 1px;
            }}
            QStatusBar {{
                background-color: {_COLORS['bg_secondary']};
                color: {_COLORS['text_dim']};
                border-top: 1px solid {_COLORS['border']};
                font-size: 12px;
                padding: 2px 8px;
            }}
            QTabWidget::pane {{
                border: 1px solid {_COLORS['border']};
                border-radius: 4px;
                background-color: {_COLORS['bg']};
            }}
            QTabBar::tab {{
                background-color: {_COLORS['bg_secondary']};
                color: {_COLORS['text_dim']};
                padding: 8px 16px;
                border: 1px solid {_COLORS['border']};
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background-color: {_COLORS['bg']};
                color: {_COLORS['text_bright']};
                border-bottom: 2px solid {_COLORS['accent']};
            }}
            QScrollBar:vertical {{
                background-color: {_COLORS['bg']};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {_COLORS['border']};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {_COLORS['text_dim']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar:horizontal {{
                background-color: {_COLORS['bg']};
                height: 8px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {_COLORS['border']};
                border-radius: 4px;
                min-width: 20px;
            }}
            QComboBox {{
                background-color: {_COLORS['bg_input']};
                color: {_COLORS['text']};
                border: 1px solid {_COLORS['border']};
                border-radius: 6px;
                padding: 6px 10px;
            }}
            QComboBox::drop-down {{
                border: none;
                padding-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {_COLORS['bg_secondary']};
                color: {_COLORS['text']};
                border: 1px solid {_COLORS['border']};
                selection-background-color: {_COLORS['accent']};
            }}
            QLineEdit {{
                background-color: {_COLORS['bg_input']};
                color: {_COLORS['text']};
                border: 1px solid {_COLORS['border']};
                border-radius: 6px;
                padding: 8px 12px;
            }}
            QLineEdit:focus {{
                border-color: {_COLORS['accent']};
            }}
            QTextEdit {{
                background-color: {_COLORS['bg_input']};
                color: {_COLORS['text']};
                border: 1px solid {_COLORS['border']};
                border-radius: 6px;
                padding: 8px;
            }}
            QTextEdit:focus {{
                border-color: {_COLORS['accent']};
            }}
            QDoubleSpinBox {{
                background-color: {_COLORS['bg_input']};
                color: {_COLORS['text']};
                border: 1px solid {_COLORS['border']};
                border-radius: 6px;
                padding: 4px 8px;
            }}
            QCheckBox {{
                color: {_COLORS['text']};
                spacing: 6px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid {_COLORS['border']};
                background-color: {_COLORS['bg_input']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {_COLORS['accent']};
                border-color: {_COLORS['accent']};
            }}
            QGroupBox {{
                color: {_COLORS['text_dim']};
                border: 1px solid {_COLORS['border']};
                border-radius: 8px;
                margin-top: 12px;
                padding: 16px 8px 8px 8px;
                font-weight: bold;
                font-size: 11px;
                text-transform: uppercase;
                letter-spacing: 1px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }}
            QProgressBar {{
                background-color: {_COLORS['bg_input']};
                border: 1px solid {_COLORS['border']};
                border-radius: 6px;
                text-align: center;
                color: {_COLORS['text']};
                font-size: 11px;
                height: 20px;
            }}
            QProgressBar::chunk {{
                background-color: {_COLORS['accent']};
                border-radius: 5px;
            }}
            QLabel {{
                background-color: transparent;
            }}
        """)

    # ─── UI Setup ────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Main splitter: left (chat+tasks) | right (PCB viewer)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # ── Left Panel: Chat + Tasks + Controls ──
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet(f"""
            background-color: {_COLORS['bg_secondary']};
            border-bottom: 1px solid {_COLORS['border']};
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)

        title_label = QLabel("AI PCB Designer")
        title_label.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {_COLORS['text_bright']};
            background-color: transparent;
        """)
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        # Settings toggle
        self._settings_btn = QPushButton("Settings")
        self._settings_btn.setFixedHeight(32)
        self._settings_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_COLORS['bg_input']};
                color: {_COLORS['text_dim']};
                border: 1px solid {_COLORS['border']};
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {_COLORS['border']};
                color: {_COLORS['text']};
            }}
        """)
        self._settings_btn.clicked.connect(self._toggle_settings)
        header_layout.addWidget(self._settings_btn)

        left_layout.addWidget(header)

        # Settings panel (collapsible)
        self._settings_panel = QWidget()
        self._settings_panel.setVisible(False)
        self._settings_panel.setStyleSheet(f"""
            background-color: {_COLORS['bg_secondary']};
            border-bottom: 1px solid {_COLORS['border']};
        """)
        settings_layout = QVBoxLayout(self._settings_panel)
        settings_layout.setContentsMargins(16, 12, 16, 12)
        settings_layout.setSpacing(8)

        # Template row
        tmpl_row = QHBoxLayout()
        tmpl_label = QLabel("Template:")
        tmpl_label.setFixedWidth(80)
        tmpl_row.addWidget(tmpl_label)
        self._template_combo = QComboBox()
        self._template_combo.addItem("Auto-detect", "")
        for tmpl in list_templates():
            self._template_combo.addItem(tmpl["name"], tmpl["name"])
        tmpl_row.addWidget(self._template_combo)
        settings_layout.addLayout(tmpl_row)

        # Board size row
        size_row = QHBoxLayout()
        size_label = QLabel("Board size:")
        size_label.setFixedWidth(80)
        size_row.addWidget(size_label)
        self._width_spin = QDoubleSpinBox()
        self._width_spin.setRange(0, 500)
        self._width_spin.setValue(0)
        self._width_spin.setSuffix(" mm")
        self._width_spin.setSpecialValueText("Auto")
        size_row.addWidget(self._width_spin)
        size_row.addWidget(QLabel("x"))
        self._height_spin = QDoubleSpinBox()
        self._height_spin.setRange(0, 500)
        self._height_spin.setValue(0)
        self._height_spin.setSuffix(" mm")
        self._height_spin.setSpecialValueText("Auto")
        size_row.addWidget(self._height_spin)
        settings_layout.addLayout(size_row)

        # LLM row
        llm_row = QHBoxLayout()
        llm_label = QLabel("LLM:")
        llm_label.setFixedWidth(80)
        llm_row.addWidget(llm_label)
        self._llm_combo = QComboBox()
        self._llm_combo.addItems([
            "Template Mode (no API)",
            "OpenAI (o4-mini)",
            "Anthropic (Claude)",
        ])
        llm_row.addWidget(self._llm_combo)
        settings_layout.addLayout(llm_row)

        # API key row
        key_row = QHBoxLayout()
        key_label = QLabel("API Key:")
        key_label.setFixedWidth(80)
        key_row.addWidget(key_label)
        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("Enter API key or set env var")
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        key_row.addWidget(self._api_key_input)
        settings_layout.addLayout(key_row)

        left_layout.addWidget(self._settings_panel)

        # Task list panel
        self._task_panel = QWidget()
        self._task_panel.setStyleSheet(f"""
            background-color: {_COLORS['bg_secondary']};
            border-bottom: 1px solid {_COLORS['border']};
        """)
        task_layout = QVBoxLayout(self._task_panel)
        task_layout.setContentsMargins(16, 8, 16, 8)
        task_layout.setSpacing(4)

        task_header = QLabel("Tasks")
        task_header.setStyleSheet(f"""
            font-size: 11px;
            font-weight: bold;
            color: {_COLORS['text_dim']};
            text-transform: uppercase;
            letter-spacing: 1px;
            background-color: transparent;
        """)
        task_layout.addWidget(task_header)

        self._task_container = QVBoxLayout()
        self._task_container.setSpacing(2)
        task_layout.addLayout(self._task_container)
        self._task_widgets: dict[str, QLabel] = {}

        self._task_panel.setVisible(False)
        left_layout.addWidget(self._task_panel)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {_COLORS['bg_secondary']};
                border: none;
                border-radius: 0px;
                height: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {_COLORS['accent']};
                border-radius: 0px;
            }}
        """)
        left_layout.addWidget(self._progress_bar)

        # Chat area (main content)
        self._chat_browser = QTextBrowser()
        self._chat_browser.setOpenExternalLinks(False)
        self._chat_browser.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {_COLORS['bg_chat']};
                color: {_COLORS['text']};
                border: none;
                padding: 16px;
                font-size: 13px;
                line-height: 1.5;
            }}
        """)
        self._chat_browser.setFont(QFont("Segoe UI", 13))
        self._append_chat_html(
            f'<div style="color: {_COLORS["text_dim"]}; text-align: center; '
            f'padding: 40px 20px;">'
            f'<div style="font-size: 24px; margin-bottom: 12px;">AI PCB Designer</div>'
            f'<div style="font-size: 14px;">Describe the PCB you want to create.</div>'
            f'<div style="font-size: 12px; margin-top: 8px; color: {_COLORS["text_dim"]};">'
            f'Examples: "ESP32 board with USB-C and OLED display" or '
            f'"Motor driver board with relay and current sensing"</div>'
            f'</div>'
        )
        left_layout.addWidget(self._chat_browser, 1)

        # Input area at bottom
        input_container = QWidget()
        input_container.setStyleSheet(f"""
            background-color: {_COLORS['bg_secondary']};
            border-top: 1px solid {_COLORS['border']};
        """)
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(16, 12, 16, 12)
        input_layout.setSpacing(8)

        # Text input
        self._input_text = QTextEdit()
        self._input_text.setPlaceholderText(
            "Describe the PCB you want, or send feedback to the AI..."
        )
        self._input_text.setMaximumHeight(80)
        self._input_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {_COLORS['bg_input']};
                color: {_COLORS['text']};
                border: 1px solid {_COLORS['border']};
                border-radius: 8px;
                padding: 10px 14px;
                font-size: 14px;
            }}
            QTextEdit:focus {{
                border-color: {_COLORS['accent']};
            }}
        """)
        input_layout.addWidget(self._input_text)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._design_btn = QPushButton("Design")
        self._design_btn.setFixedHeight(36)
        self._design_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._design_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_COLORS['green_dim']};
                color: white;
                font-size: 13px;
                font-weight: 600;
                border: none;
                border-radius: 8px;
                padding: 0 20px;
            }}
            QPushButton:hover {{
                background-color: {_COLORS['green']};
            }}
            QPushButton:disabled {{
                background-color: {_COLORS['bg_input']};
                color: {_COLORS['text_dim']};
            }}
        """)
        self._design_btn.clicked.connect(self._on_design_clicked)
        btn_row.addWidget(self._design_btn)

        self._send_btn = QPushButton("Send")
        self._send_btn.setFixedHeight(36)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_COLORS['bg_input']};
                color: {_COLORS['accent']};
                font-size: 13px;
                font-weight: 600;
                border: 1px solid {_COLORS['border']};
                border-radius: 8px;
                padding: 0 20px;
            }}
            QPushButton:hover {{
                background-color: {_COLORS['border']};
            }}
            QPushButton:disabled {{
                background-color: {_COLORS['bg_input']};
                color: {_COLORS['text_dim']};
                border-color: {_COLORS['bg_input']};
            }}
        """)
        self._send_btn.setEnabled(False)
        self._send_btn.clicked.connect(self._on_send_clicked)
        btn_row.addWidget(self._send_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setFixedHeight(36)
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_COLORS['red_dim']};
                color: white;
                font-size: 13px;
                font-weight: 600;
                border: none;
                border-radius: 8px;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                background-color: {_COLORS['red']};
            }}
            QPushButton:disabled {{
                background-color: {_COLORS['bg_input']};
                color: {_COLORS['text_dim']};
            }}
        """)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        btn_row.addWidget(self._stop_btn)

        btn_row.addStretch()
        input_layout.addLayout(btn_row)

        left_layout.addWidget(input_container)
        splitter.addWidget(left_panel)

        # ── Right Panel: PCB Viewer + Board Info ──
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # PCB Renderer tabs
        self._view_tabs = QTabWidget()
        self._renderer = PCBGraphicsView()
        self._view_tabs.addTab(self._renderer, "PCB View")

        self._3d_placeholder = QLabel("3D view available after design")
        self._3d_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._3d_placeholder.setStyleSheet(f"color: {_COLORS['text_dim']};")
        self._view_tabs.addTab(self._3d_placeholder, "3D")

        right_layout.addWidget(self._view_tabs, 1)

        # Board info panel
        info_panel = QWidget()
        info_panel.setFixedHeight(140)
        info_panel.setStyleSheet(f"""
            background-color: {_COLORS['bg_secondary']};
            border-top: 1px solid {_COLORS['border']};
        """)
        info_layout = QVBoxLayout(info_panel)
        info_layout.setContentsMargins(12, 8, 12, 8)

        info_header_row = QHBoxLayout()
        info_header = QLabel("Board Info")
        info_header.setStyleSheet(f"""
            font-size: 11px; font-weight: bold;
            color: {_COLORS['text_dim']};
            text-transform: uppercase; letter-spacing: 1px;
            background-color: transparent;
        """)
        info_header_row.addWidget(info_header)
        info_header_row.addStretch()

        # Layer visibility button
        self._layers_btn = QPushButton("Layers")
        self._layers_btn.setFixedHeight(24)
        self._layers_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_COLORS['bg_input']};
                color: {_COLORS['text_dim']};
                border: 1px solid {_COLORS['border']};
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
            }}
            QPushButton:hover {{ color: {_COLORS['text']}; }}
        """)
        self._layers_btn.clicked.connect(self._toggle_layers)
        info_header_row.addWidget(self._layers_btn)

        info_layout.addLayout(info_header_row)

        self._board_info = QLabel("No board designed yet")
        self._board_info.setWordWrap(True)
        self._board_info.setStyleSheet(f"""
            color: {_COLORS['text_dim']};
            font-size: 12px;
            background-color: transparent;
        """)
        info_layout.addWidget(self._board_info)

        # Layer controls (hidden by default)
        self._layer_panel = QWidget()
        self._layer_panel.setVisible(False)
        layer_layout = QHBoxLayout(self._layer_panel)
        layer_layout.setContentsMargins(0, 4, 0, 0)
        layer_layout.setSpacing(8)
        self._layer_checkboxes: dict[str, QCheckBox] = {}

        layer_names = {
            "board": "Board", "f_cu": "F.Cu", "b_cu": "B.Cu",
            "f_silk": "Silk", "pads": "Pads", "vias": "Vias",
            "traces": "Traces", "ratsnest": "Rats", "refs": "Refs",
        }
        for key, label in layer_names.items():
            cb = QCheckBox(label)
            cb.setChecked(self._renderer.layer_visibility.get(key, True))
            cb.setStyleSheet(f"font-size: 11px; color: {_COLORS['text_dim']};")
            cb.toggled.connect(lambda c, k=key: self._on_layer_toggled(k, c))
            layer_layout.addWidget(cb)
            self._layer_checkboxes[key] = cb
        layer_layout.addStretch()

        info_layout.addWidget(self._layer_panel)
        right_layout.addWidget(info_panel)

        splitter.addWidget(right_panel)
        splitter.setSizes([550, 950])

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

    def _setup_menubar(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        file_menu.addAction("Export Gerbers...", self._export_gerbers)
        file_menu.addAction("Export KiCad...", self._export_kicad)
        file_menu.addAction("Export All...", self._export_all)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        view_menu = menubar.addMenu("View")
        view_menu.addAction("Fit Board", self._renderer.fit_board)
        view_menu.addAction("Reset View", self._reset_view)
        view_menu.addAction("Toggle Settings", self._toggle_settings)

        help_menu = menubar.addMenu("Help")
        help_menu.addAction("About", self._show_about)

    # ─── Chat Helpers ────────────────────────────────────────────────────

    def _append_chat_html(self, html: str) -> None:
        """Append HTML to the chat browser."""
        self._chat_browser.append(html)
        QTimer.singleShot(10, self._scroll_chat_bottom)

    def _scroll_chat_bottom(self) -> None:
        sb = self._chat_browser.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _add_chat_msg(self, role: str, content: str, detail: str = "",
                      task_status: str = "") -> None:
        """Add a formatted message to the chat."""
        if role == "agent":
            icon = "&#x1F916;"
            bg = _COLORS["agent_msg"]
            border_color = _COLORS["accent"]
        elif role == "user":
            icon = "&#x1F464;"
            bg = _COLORS["user_msg"]
            border_color = _COLORS["green"]
        elif role == "task":
            # Task status messages are compact
            status_icon = {
                "running": f'<span style="color:{_COLORS["yellow"]};">&#x25CF;</span>',
                "done": f'<span style="color:{_COLORS["green"]};">&#x2714;</span>',
                "failed": f'<span style="color:{_COLORS["red"]};">&#x2718;</span>',
            }.get(task_status, "&#x25CB;")
            self._append_chat_html(
                f'<div style="padding: 2px 0; font-size: 12px; '
                f'color: {_COLORS["text_dim"]};">'
                f'  {status_icon} {content}'
                f'</div>'
            )
            return
        else:
            icon = "&#x2699;"
            bg = _COLORS["system_msg"]
            border_color = _COLORS["text_dim"]

        detail_html = ""
        if detail:
            escaped = detail.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            detail_html = (
                f'<div style="margin-top: 6px; padding: 8px; '
                f'background-color: {_COLORS["bg"]}; border-radius: 4px; '
                f'font-size: 12px; color: {_COLORS["text_dim"]}; '
                f'font-family: monospace; white-space: pre-wrap;">'
                f'{escaped}</div>'
            )

        escaped_content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._append_chat_html(
            f'<div style="margin: 8px 0; padding: 10px 14px; '
            f'background-color: {bg}; border-left: 3px solid {border_color}; '
            f'border-radius: 0 8px 8px 0;">'
            f'  <div style="font-size: 13px; color: {_COLORS["text"]};">'
            f'{escaped_content}</div>'
            f'  {detail_html}'
            f'</div>'
        )

    def _update_task_display(self, tasks: list[dict]) -> None:
        """Update the task list panel."""
        # Clear existing widgets
        for w in self._task_widgets.values():
            w.deleteLater()
        self._task_widgets.clear()

        for task in tasks:
            name = task["name"]
            status = task["status"]

            if status == "running":
                icon = f'<span style="color:{_COLORS["yellow"]};">&#x25B6;</span>'
                color = _COLORS["text"]
                weight = "bold"
            elif status == "done":
                icon = f'<span style="color:{_COLORS["green"]};">&#x2714;</span>'
                color = _COLORS["text_dim"]
                weight = "normal"
            elif status == "failed":
                icon = f'<span style="color:{_COLORS["red"]};">&#x2718;</span>'
                color = _COLORS["red"]
                weight = "normal"
            else:  # pending
                icon = f'<span style="color:{_COLORS["text_dim"]};">&#x25CB;</span>'
                color = _COLORS["text_dim"]
                weight = "normal"

            label = QLabel(f'{icon} {name}')
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setStyleSheet(f"""
                font-size: 12px;
                color: {color};
                font-weight: {weight};
                padding: 2px 0;
                background-color: transparent;
            """)
            self._task_container.addWidget(label)
            self._task_widgets[name] = label

    # ─── Event Handlers ──────────────────────────────────────────────────

    def _on_design_clicked(self) -> None:
        """Start the autonomous design process."""
        description = self._input_text.toPlainText().strip()
        if not description:
            template_name = self._template_combo.currentData()
            if template_name:
                description = template_name
            else:
                self._add_chat_msg("system",
                    "Please enter a description of the PCB you want to create.")
                return

        # Show user message in chat
        self._add_chat_msg("user", description)
        self._input_text.clear()

        # Update UI state
        self._progress_bar.setValue(0)
        self._design_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._send_btn.setEnabled(True)  # Allow interventions
        self._task_panel.setVisible(True)

        # Configure agent
        llm_idx = self._llm_combo.currentIndex()
        providers = ["template", "openai", "anthropic"]
        config = AgentConfig(
            llm_provider=providers[llm_idx],
            api_key=self._api_key_input.text().strip(),
            output_dir="./output",
            user_width=self._width_spin.value(),
            user_height=self._height_spin.value(),
        )

        self._agent = PCBDesignAgent(config)
        self._agent.set_step_callback(
            lambda step: self._step_signal.step_received.emit(step)
        )
        self._agent.set_chat_callback(
            lambda msg: self._step_signal.chat_received.emit(msg)
        )

        # Run design in background thread
        def run_design():
            board = self._agent.design(description) if self._agent else None
            self._step_signal.design_finished.emit(board)

        self._design_thread = threading.Thread(target=run_design, daemon=True)
        self._design_thread.start()

    def _on_send_clicked(self) -> None:
        """Send user feedback/intervention to the running agent."""
        text = self._input_text.toPlainText().strip()
        if not text:
            return

        self._add_chat_msg("user", text)
        self._input_text.clear()

        if self._agent:
            if self._agent.phase in (AgentPhase.COMPLETE, AgentPhase.FAILED,
                                     AgentPhase.IDLE):
                # Agent is done - start an edit
                self._on_edit_send(text)
            else:
                # Agent is running - queue as intervention
                self._agent.send_user_message(text)
                self._add_chat_msg("system",
                    "Feedback queued - the AI will incorporate it in the next iteration.")

    def _on_edit_send(self, edit_text: str) -> None:
        """Send an edit request after design is complete."""
        if not self._agent or not self._agent.board:
            self._add_chat_msg("system",
                "Design a board first before sending edit requests.")
            return

        self._design_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._progress_bar.setValue(0)

        def run_edit():
            board = self._agent.edit(edit_text) if self._agent else None
            self._step_signal.design_finished.emit(board)

        self._design_thread = threading.Thread(target=run_edit, daemon=True)
        self._design_thread.start()

    def _on_stop_clicked(self) -> None:
        """Cancel the running design."""
        if self._agent:
            self._agent.cancel()
            self._add_chat_msg("system", "Design cancelled by user.")
            self._update_status("Cancelled")
            self._design_btn.setEnabled(True)
            self._stop_btn.setEnabled(False)

    @Slot(object)
    def _on_agent_step(self, step: AgentStep) -> None:
        """Handle agent step update on the main thread."""
        self._progress_bar.setValue(int(step.progress * 100))

        # Update renderer if board snapshot available
        if step.board_snapshot:
            self._renderer.render_board(step.board_snapshot)
            if step.phase in (AgentPhase.CREATING_SCHEMATIC, AgentPhase.SIZING_BOARD):
                QTimer.singleShot(100, self._renderer.fit_board)

            summary = step.board_snapshot.summary()
            info_lines = [f"{k}: {v}" for k, v in summary.items()]
            self._board_info.setText("\n".join(info_lines))

        # Update task list from agent
        if self._agent:
            self._update_task_display(self._agent.tasks)

        self._update_status(step.message)

    @Slot(object)
    def _on_chat_message(self, msg: ChatMessage) -> None:
        """Handle chat message from agent on the main thread."""
        self._add_chat_msg(msg.role, msg.content, msg.detail, msg.task_status)

    @Slot(object)
    def _on_design_finished(self, board) -> None:
        """Called when the design thread completes."""
        self._design_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._send_btn.setEnabled(True)

        if board is not None:
            self._renderer.render_board(board)
            QTimer.singleShot(200, self._renderer.fit_board)
            self._show_3d_view(board)

            summary = board.summary()
            info_lines = [f"{k}: {v}" for k, v in summary.items()]
            self._board_info.setText("\n".join(info_lines))

            self._add_chat_msg("agent",
                "Design complete! You can now:",
                "- Send feedback to modify the board\n"
                "- Export via File menu (Gerber, KiCad, BOM)\n"
                "- Toggle layers in the Board Info panel\n"
                "- View in 3D via the 3D tab")

        if self._agent:
            self._update_task_display(self._agent.tasks)

    def _show_3d_view(self, board) -> None:
        """Create and show the 3D board view in the tab."""
        try:
            from .viewer3d import Board3DWidget
            viewer = Board3DWidget()
            viewer.set_board(board)
            self._view_tabs.removeTab(1)
            self._view_tabs.insertTab(1, viewer, "3D")
        except Exception as e:
            error_label = QLabel(f"3D unavailable: {e}")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error_label.setStyleSheet(f"color: {_COLORS['red']};")
            error_label.setWordWrap(True)
            self._view_tabs.removeTab(1)
            self._view_tabs.insertTab(1, error_label, "3D")

    def _toggle_settings(self) -> None:
        self._settings_panel.setVisible(not self._settings_panel.isVisible())

    def _toggle_layers(self) -> None:
        self._layer_panel.setVisible(not self._layer_panel.isVisible())

    def _on_layer_toggled(self, layer_name: str, checked: bool) -> None:
        self._renderer.set_layer_visible(layer_name, checked)

    def _reset_view(self) -> None:
        self._renderer.resetTransform()
        self._renderer.fit_board()

    # ─── Export ──────────────────────────────────────────────────────────

    def _export_gerbers(self) -> None:
        if not self._agent or not self._agent.board:
            QMessageBox.information(self, "No Board", "Design a board first.")
            return
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            from ..exporters.gerber import GerberExporter
            files = GerberExporter(self._agent.board).export(dir_path)
            self._add_chat_msg("system",
                f"Exported {len(files)} Gerber files to {dir_path}")

    def _export_kicad(self) -> None:
        if not self._agent or not self._agent.board:
            QMessageBox.information(self, "No Board", "Design a board first.")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save KiCad File", "", "KiCad PCB (*.kicad_pcb)")
        if file_path:
            from ..exporters.kicad import KiCadExporter
            KiCadExporter(self._agent.board).export(file_path)
            self._add_chat_msg("system", f"Exported KiCad file to {file_path}")

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
                PickAndPlaceExporter(board).export(Path(dir_path) / "PickAndPlace.csv"))
            files.append(
                KiCadExporter(board).export(Path(dir_path) / f"{board.name}.kicad_pcb"))
            self._add_chat_msg("system",
                f"Exported {len(files)} manufacturing files to {dir_path}")

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About AI PCB Designer",
            "AI PCB Designer v0.5.0\n\n"
            "Autonomous agentic PCB design tool.\n\n"
            "Features:\n"
            "- Multi-iteration AI design loop\n"
            "- Physics-aware design validation\n"
            "- Dynamic component discovery (100+ packages)\n"
            "- Chat-based interface with live interventions\n"
            "- Force-directed placement with escape strategies\n"
            "- A* autorouting with progressive optimization\n"
            "- DRC with auto-fix (5 retry passes)\n"
            "- AI self-notes / memory system\n\n"
            "Outputs:\n"
            "- Gerber files (RS-274X)\n"
            "- KiCad .kicad_pcb\n"
            "- Bill of Materials (BOM)\n"
            "- Pick-and-Place (PnP)\n"
            "- Assembly drawings (SVG)",
        )

    def _update_status(self, message: str) -> None:
        self._status_bar.showMessage(message)
