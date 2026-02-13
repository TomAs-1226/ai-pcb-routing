"""Tests for core data model and design pipeline."""

import sys
from pathlib import Path

# Add src to path for testing
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_pcb_designer.core.datatypes import Point, Rect, Layer
from ai_pcb_designer.core.board import Board, BoardSettings, DesignRules
from ai_pcb_designer.core.component import Component, Footprint, Pad
from ai_pcb_designer.core.net import Net, NetClass
from ai_pcb_designer.core.trace import Trace, TraceSegment, Via


def test_point_arithmetic():
    p1 = Point(1.0, 2.0)
    p2 = Point(3.0, 4.0)
    result = p1 + p2
    assert result.x == 4.0
    assert result.y == 6.0

    diff = p2 - p1
    assert diff.x == 2.0
    assert diff.y == 2.0

    scaled = p1 * 3.0
    assert scaled.x == 3.0
    assert scaled.y == 6.0


def test_point_distance():
    p1 = Point(0, 0)
    p2 = Point(3, 4)
    assert abs(p1.distance_to(p2) - 5.0) < 1e-10


def test_point_rotate():
    p = Point(1, 0)
    rotated = p.rotate(90)
    assert abs(rotated.x) < 1e-10
    assert abs(rotated.y - 1.0) < 1e-10


def test_rect_contains():
    r = Rect(0, 0, 10, 10)
    assert r.contains(Point(5, 5))
    assert not r.contains(Point(15, 5))


def test_rect_overlaps():
    r1 = Rect(0, 0, 10, 10)
    r2 = Rect(5, 5, 10, 10)
    r3 = Rect(20, 20, 5, 5)
    assert r1.overlaps(r2)
    assert not r1.overlaps(r3)


def test_board_creation():
    board = Board(name="Test Board")
    assert board.name == "Test Board"
    assert len(board.components) == 0
    assert len(board.nets) == 0


def test_board_add_net():
    board = Board()
    net = board.add_net("GND")
    assert net.id == 1
    assert net.name == "GND"
    assert net.is_ground

    net2 = board.add_net("3V3")
    assert net2.id == 2
    assert net2.is_power


def test_net_properties():
    net = Net(1, "GND")
    assert net.is_ground
    assert not net.is_power

    net2 = Net(2, "VCC")
    assert not net2.is_ground
    assert net2.is_power


def test_trace_length():
    trace = Trace(net_id=1)
    trace.add_segment(Point(0, 0), Point(10, 0), 0.25, Layer.F_CU)
    trace.add_segment(Point(10, 0), Point(10, 10), 0.25, Layer.F_CU)
    assert abs(trace.total_length - 20.0) < 1e-10


def test_board_summary():
    board = Board(name="Test")
    board.add_net("GND")
    summary = board.summary()
    assert summary["name"] == "Test"
    assert summary["nets"] == 1
    assert summary["components"] == 0


if __name__ == "__main__":
    test_point_arithmetic()
    test_point_distance()
    test_point_rotate()
    test_rect_contains()
    test_rect_overlaps()
    test_board_creation()
    test_board_add_net()
    test_net_properties()
    test_trace_length()
    test_board_summary()
    print("All core tests passed!")
