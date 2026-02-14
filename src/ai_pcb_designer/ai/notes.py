"""AI self-notes / memory system for design rules and lessons learned.

The AI agent can write notes to itself during design iterations.
These notes persist across iterations within a session and are injected
into the LLM prompt so it remembers what worked and what didn't.

Notes are categorized:
- PHYSICS: Electrical/physical rules the AI has learned
- LAYOUT: PCB layout lessons (spacing, routing, placement)
- COMPONENT: Component-specific knowledge (pinouts, packages)
- ERROR: Mistakes to avoid (from failed attempts)
- STRATEGY: Design strategies that worked well
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DesignNote:
    """A single note the AI writes to itself."""
    category: str  # PHYSICS, LAYOUT, COMPONENT, ERROR, STRATEGY
    content: str
    timestamp: float = field(default_factory=time.time)
    priority: int = 1  # 1=normal, 2=important, 3=critical

    def __str__(self) -> str:
        priority_marker = "!" * self.priority if self.priority > 1 else ""
        return f"[{self.category}]{priority_marker} {self.content}"


class DesignMemory:
    """Persistent design memory for the AI agent.

    Stores notes the AI writes to itself about design rules,
    mistakes to avoid, and strategies that work. These are injected
    into the system prompt so the AI learns from its iterations.
    """

    # Built-in physics and design rules the AI should always follow
    _CORE_PHYSICS_RULES: list[str] = [
        "Ohm's Law: V=IR. Always calculate current through LEDs/resistors.",
        "Bypass caps MUST be within 3mm of IC power pins - this is physics, not style.",
        "Power traces (VCC, GND, VBUS) must be wider (0.5mm+) than signal traces (0.25mm).",
        "I2C needs 4.7k pull-ups on SDA/SCL. Without them the bus won't work.",
        "LED forward voltage: Red=1.8V, Green=2.2V, Blue=3.3V, White=3.3V. "
        "Calculate R = (Vcc - Vf) / I_desired.",
        "ESP32 GPIO max current: 12mA per pin, 40mA absolute max. Never drive "
        "relays or motors directly from GPIO.",
        "Relay coils need flyback diodes (1N4148/1N4007) or the voltage spike "
        "WILL destroy your transistor driver.",
        "MOSFET gate needs a resistor (100-470 ohm) to limit ringing and a "
        "pull-down (10k-100k) to keep it off at boot.",
        "USB-C CC pins need 5.1k pull-down resistors to GND for proper "
        "detection as a UFP (device). Without them, no power delivery.",
        "Crystal load capacitors: C_load = 2 * (C_crystal - C_stray). "
        "Typical stray = 3-5pF.",
        "Voltage regulators MUST have input AND output capacitors. "
        "AMS1117 needs min 22uF on output (tantalum or ceramic).",
        "Trace width for current: 1oz copper, 10 degree rise: "
        "1A=0.3mm, 2A=0.7mm, 3A=1.2mm, 5A=2.5mm.",
        "Minimum annular ring: 0.13mm. Via drill + 2*annular = via diameter.",
        "Ground planes improve signal integrity. Use copper pour on B.Cu for GND.",
        "Keep analog and digital grounds separate until the star-point connection.",
        "High-frequency signals (SPI >10MHz, USB) need controlled impedance "
        "and ground plane under traces.",
    ]

    _CORE_LAYOUT_RULES: list[str] = [
        "Place connectors at board edges for accessibility.",
        "Group related components (MCU + bypass caps + crystal form a unit).",
        "Power flows in one direction: connector -> regulator -> loads.",
        "Keep high-current paths short and wide.",
        "Route clock/high-speed signals first, then power, then signals.",
        "Avoid right-angle traces - use 45 degree bends or curves.",
        "Place decoupling caps on the SAME SIDE as the IC, between IC and via.",
        "Board outline should have rounded corners (min 1mm radius) for "
        "manufacturing and handling.",
    ]

    def __init__(self) -> None:
        self._notes: list[DesignNote] = []
        self._session_log: list[str] = []

    def add_note(self, category: str, content: str, priority: int = 1) -> None:
        """Add a design note. Categories: PHYSICS, LAYOUT, COMPONENT, ERROR, STRATEGY."""
        category = category.upper()
        if category not in ("PHYSICS", "LAYOUT", "COMPONENT", "ERROR", "STRATEGY"):
            category = "STRATEGY"
        self._notes.append(DesignNote(category=category, content=content, priority=priority))

    def add_error(self, error_msg: str, lesson: str) -> None:
        """Record a mistake and what was learned from it."""
        self._notes.append(DesignNote(
            category="ERROR",
            content=f"Mistake: {error_msg} | Lesson: {lesson}",
            priority=2,
        ))

    def add_physics_rule(self, rule: str) -> None:
        """Add a physics/electrical rule."""
        self._notes.append(DesignNote(category="PHYSICS", content=rule, priority=2))

    def log_iteration(self, iteration: int, summary: str) -> None:
        """Log a design iteration summary."""
        self._session_log.append(f"Iteration {iteration}: {summary}")

    def get_notes_for_prompt(self) -> str:
        """Format all notes for injection into the LLM system prompt."""
        sections = []

        # Core physics rules (always included)
        sections.append("## PHYSICS RULES (MUST FOLLOW)")
        for rule in self._CORE_PHYSICS_RULES:
            sections.append(f"- {rule}")

        # Core layout rules
        sections.append("\n## LAYOUT RULES")
        for rule in self._CORE_LAYOUT_RULES:
            sections.append(f"- {rule}")

        # Session-specific notes
        if self._notes:
            sections.append("\n## NOTES FROM PREVIOUS ITERATIONS")
            # Sort by priority (highest first), then by time
            sorted_notes = sorted(self._notes, key=lambda n: (-n.priority, n.timestamp))
            for note in sorted_notes[:20]:  # Limit to prevent prompt bloat
                sections.append(f"- {note}")

        # Iteration log
        if self._session_log:
            sections.append("\n## ITERATION HISTORY")
            for entry in self._session_log[-5:]:  # Last 5 iterations
                sections.append(f"- {entry}")

        return "\n".join(sections)

    def get_error_notes(self) -> list[str]:
        """Get all error notes for debugging."""
        return [n.content for n in self._notes if n.category == "ERROR"]

    def clear_session(self) -> None:
        """Clear session-specific notes (keep learned rules)."""
        self._notes = [n for n in self._notes if n.category in ("PHYSICS", "COMPONENT")]
        self._session_log.clear()

    def save(self, path: Path) -> None:
        """Save notes to disk for persistence across sessions."""
        data = {
            "notes": [
                {"category": n.category, "content": n.content,
                 "priority": n.priority, "timestamp": n.timestamp}
                for n in self._notes
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    def load(self, path: Path) -> None:
        """Load notes from disk."""
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            for item in data.get("notes", []):
                self._notes.append(DesignNote(
                    category=item["category"],
                    content=item["content"],
                    priority=item.get("priority", 1),
                    timestamp=item.get("timestamp", time.time()),
                ))
        except (json.JSONDecodeError, KeyError):
            pass  # Corrupt file - start fresh
