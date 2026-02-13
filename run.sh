#!/usr/bin/env bash
# AI PCB Designer launcher - auto-detects correct Python with PySide6
#
# Usage:
#   ./run.sh              # GUI mode
#   ./run.sh --cli        # CLI mode
#   ./run.sh --cli --template esp32_carrier

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Try to find a Python with PySide6 installed
find_python() {
    # Check common Python commands
    for cmd in python3.13 python3.12 python3.11 python3.10 python3 python; do
        if command -v "$cmd" &>/dev/null; then
            if "$cmd" -c "import PySide6" 2>/dev/null; then
                echo "$cmd"
                return 0
            fi
        fi
    done

    # Check if any python exists at all
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            echo "$cmd"
            return 0
        fi
    done

    echo ""
    return 1
}

PYTHON=$(find_python)

if [ -z "$PYTHON" ]; then
    echo "ERROR: No Python installation found."
    echo "Please install Python 3.10+ from https://www.python.org/downloads/"
    exit 1
fi

# Check if running in CLI mode (no PySide6 needed)
CLI_MODE=false
for arg in "$@"; do
    if [ "$arg" = "--cli" ] || [ "$arg" = "--list-templates" ]; then
        CLI_MODE=true
        break
    fi
done

# Check PySide6 for GUI mode
if [ "$CLI_MODE" = false ]; then
    if ! "$PYTHON" -c "import PySide6" 2>/dev/null; then
        echo "PySide6 not found. Installing..."
        "$PYTHON" -m pip install PySide6 numpy shapely
        echo ""
    fi
fi

# Check core deps
if ! "$PYTHON" -c "import numpy" 2>/dev/null; then
    echo "Installing core dependencies..."
    "$PYTHON" -m pip install numpy shapely
fi

# Run the application
export PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"
exec "$PYTHON" -m ai_pcb_designer "$@"
