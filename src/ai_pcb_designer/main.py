"""Main entry point for AI PCB Designer.

Supports two modes:
1. GUI mode (default): Opens the graphical application
2. CLI mode: Runs headless design from command line

Usage:
    # GUI mode
    python -m ai_pcb_designer

    # CLI mode
    python -m ai_pcb_designer --cli "Make me an ESP32 carrier board"
    python -m ai_pcb_designer --cli --template esp32_carrier
    python -m ai_pcb_designer --cli --template led_blinker --output ./my_output
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="AI PCB Designer - Autonomous PCB design tool",
    )
    parser.add_argument(
        "--cli",
        nargs="?",
        const="",
        default=None,
        metavar="DESCRIPTION",
        help="Run in CLI mode with optional board description",
    )
    parser.add_argument(
        "--template",
        type=str,
        default="",
        help="Use a specific template (esp32_carrier, led_blinker, sensor_breakout)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./output",
        help="Output directory for generated files (default: ./output)",
    )
    parser.add_argument(
        "--llm",
        type=str,
        choices=["template", "openai", "anthropic"],
        default="template",
        help="LLM provider for AI-driven design (default: template)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default="",
        help="API key for the selected LLM provider",
    )
    parser.add_argument(
        "--list-templates",
        action="store_true",
        help="List available board templates and exit",
    )

    args = parser.parse_args()

    if args.list_templates:
        _list_templates()
        return

    if args.cli is not None:
        _run_cli(args)
    else:
        _run_gui()


def _run_gui() -> None:
    """Launch the GUI application."""
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
    except ImportError:
        print("ERROR: PySide6 is not installed for this Python interpreter.")
        print(f"  Python executable: {sys.executable}")
        print(f"  Python version:    {sys.version}")
        print()
        print("Fix: install PySide6 for THIS Python version:")
        print(f"  {sys.executable} -m pip install PySide6")
        print()
        print("Or run in CLI mode (no GUI needed):")
        print("  python -m ai_pcb_designer --cli --template esp32_carrier")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("AI PCB Designer")
    app.setOrganizationName("AI-PCB-Designer")

    # Set dark theme
    app.setStyleSheet(_dark_stylesheet())

    from .gui.main_window import MainWindow
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def _run_cli(args: argparse.Namespace) -> None:
    """Run in CLI (headless) mode."""
    from .ai.agent import AgentConfig, AgentPhase, PCBDesignAgent

    description = args.cli or args.template or "led_blinker"

    print(f"AI PCB Designer v0.1.0 - CLI Mode")
    print(f"=" * 50)
    print(f"Description: {description}")
    print(f"Output dir:  {args.output}")
    print()

    config = AgentConfig(
        llm_provider=args.llm,
        api_key=args.api_key,
        output_dir=args.output,
    )

    agent = PCBDesignAgent(config)

    def on_step(step):
        phase_name = step.phase.name.ljust(20)
        bar = "=" * int(step.progress * 30) + "-" * (30 - int(step.progress * 30))
        print(f"  [{bar}] {phase_name} {step.message}")
        if step.detail:
            for line in step.detail.split("\n")[:3]:
                print(f"  {'':>35} {line}")

    agent.set_step_callback(on_step)
    board = agent.design(description)

    if board:
        print()
        print(f"Design complete!")
        print(f"Board summary:")
        for k, v in board.summary().items():
            print(f"  {k}: {v}")
    else:
        print("Design failed.")
        sys.exit(1)


def _list_templates() -> None:
    """Print available templates."""
    from .components.templates import list_templates

    print("Available board templates:")
    print()
    for tmpl in list_templates():
        print(f"  {tmpl['name']}")
        print(f"    {tmpl['description']}")
        print()


def _dark_stylesheet() -> str:
    """Dark theme stylesheet for the application."""
    return """
    QMainWindow {
        background-color: #1e1e2e;
    }
    QWidget {
        background-color: #1e1e2e;
        color: #cdd6f4;
        font-family: "Segoe UI", "SF Pro", "Ubuntu", sans-serif;
    }
    QGroupBox {
        border: 1px solid #45475a;
        border-radius: 6px;
        margin-top: 8px;
        padding-top: 16px;
        font-weight: bold;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px;
    }
    QTextEdit, QPlainTextEdit {
        background-color: #181825;
        border: 1px solid #45475a;
        border-radius: 4px;
        padding: 4px;
        color: #cdd6f4;
    }
    QLineEdit {
        background-color: #181825;
        border: 1px solid #45475a;
        border-radius: 4px;
        padding: 4px 8px;
        color: #cdd6f4;
    }
    QComboBox {
        background-color: #181825;
        border: 1px solid #45475a;
        border-radius: 4px;
        padding: 4px 8px;
        color: #cdd6f4;
    }
    QComboBox::drop-down {
        border: none;
    }
    QComboBox QAbstractItemView {
        background-color: #181825;
        color: #cdd6f4;
        selection-background-color: #45475a;
    }
    QPushButton {
        background-color: #45475a;
        color: #cdd6f4;
        border: none;
        border-radius: 4px;
        padding: 6px 16px;
    }
    QPushButton:hover {
        background-color: #585b70;
    }
    QPushButton:disabled {
        background-color: #313244;
        color: #6c7086;
    }
    QProgressBar {
        background-color: #181825;
        border: 1px solid #45475a;
        border-radius: 4px;
        text-align: center;
        color: #cdd6f4;
    }
    QProgressBar::chunk {
        background-color: #a6e3a1;
        border-radius: 3px;
    }
    QCheckBox {
        spacing: 8px;
        color: #cdd6f4;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border: 1px solid #45475a;
        border-radius: 3px;
        background-color: #181825;
    }
    QCheckBox::indicator:checked {
        background-color: #a6e3a1;
        border-color: #a6e3a1;
    }
    QMenuBar {
        background-color: #181825;
        color: #cdd6f4;
    }
    QMenuBar::item:selected {
        background-color: #45475a;
    }
    QMenu {
        background-color: #181825;
        color: #cdd6f4;
        border: 1px solid #45475a;
    }
    QMenu::item:selected {
        background-color: #45475a;
    }
    QToolBar {
        background-color: #181825;
        border-bottom: 1px solid #45475a;
        spacing: 4px;
    }
    QStatusBar {
        background-color: #181825;
        color: #a6adc8;
    }
    QSplitter::handle {
        background-color: #45475a;
    }
    QLabel {
        color: #cdd6f4;
    }
    QDockWidget {
        color: #cdd6f4;
    }
    """


if __name__ == "__main__":
    main()
