"""
Workstream W3: Context & Reasoning
Synthetic Context Fixtures & Mock Screen Frames

Author: Amruta A J (Team SDE 3)
Module: src.context.fixtures
Description:
    Provides deterministic synthetic context fixtures representing user workspaces.
    Safety Guarantees:
    - Screen capture is explicitly DISABLED by default (`capture_enabled=False`).
    - Uses 100% fictional data (fictional errors, mock code snippets, synthetic OCR).
    - No real user files, personal data, or external camera/screen APIs are ever invoked.
"""

from datetime import datetime, timezone
from typing import List
from src.context.schemas import ContextItem, ContextType, ScreenContext, SourceReference


def create_synthetic_screen_frame(
    frame_id: str = "frame-syn-001",
    active_app: str = "VS Code",
    window_title: str = "calculator.py - DemoProject - Visual Studio Code",
    visible_text: str = "def divide(a: float, b: float) -> float:\n    return a / b  # Line 14: ZeroDivisionError",
    width: int = 1920,
    height: int = 1080,
) -> ScreenContext:
    """
    Generate a synthetic screen frame fixture with screen capture disabled by default.

    Parameters:
        frame_id: Unique string for the synthetic frame.
        active_app: Fictional active application name.
        window_title: Synthetic active window title.
        visible_text: Synthetic OCR/screen text.
        width: Screen width in pixels.
        height: Screen height in pixels.

    Returns:
        Validated ScreenContext instance (capture_enabled=False, is_synthetic=True).
    """
    return ScreenContext(
        capture_enabled=False,
        is_synthetic=True,
        frame_id=frame_id,
        width=width,
        height=height,
        active_window_title=window_title,
        active_application=active_app,
        visible_text=visible_text,
        captured_at=datetime.now(timezone.utc),
        metadata={"generator": "synthetic_fixtures_v1", "source": "unit_test_mock"}
    )


def get_synthetic_error_scenario() -> List[ContextItem]:
    """
    Fixture 1 (UC-02: Explain Technical Error).
    Fictional Python ZeroDivisionError in a sample math module.
    """
    screen = create_synthetic_screen_frame(
        frame_id="frame-err-001",
        active_app="VS Code",
        window_title="math_operations.py - SampleApp",
        visible_text="def calculate_ratio(num: int, den: int):\n    return num / den",
    )

    item_code = ContextItem(
        item_id="ctx-code-001",
        context_type=ContextType.CODE,
        source="src/math_operations.py",
        content=(
            "def calculate_ratio(numerator: int, denominator: int) -> float:\n"
            "    # Missing check for denominator == 0\n"
            "    return numerator / denominator\n"
        ),
        metadata={"language": "python", "lines": "1-3"},
    )

    item_terminal = ContextItem(
        item_id="ctx-term-001",
        context_type=ContextType.TERMINAL,
        source="Integrated Terminal",
        content=(
            "Traceback (most recent call last):\n"
            '  File "main.py", line 12, in <module>\n'
            "    result = calculate_ratio(10, 0)\n"
            '  File "src/math_operations.py", line 3, in calculate_ratio\n'
            "    return numerator / denominator\n"
            "ZeroDivisionError: division by zero"
        ),
        metadata={"exit_code": 1},
    )

    item_screen = ContextItem(
        item_id="ctx-screen-001",
        context_type=ContextType.SCREEN,
        source="Primary Display",
        content="Active editor showing calculate_ratio with error breakpoint at line 3.",
        screen_context=screen,
        metadata={"capture_status": "disabled_default"},
    )

    return [item_code, item_terminal, item_screen]


def get_synthetic_document_scenario() -> List[ContextItem]:
    """
    Fixture 2 (UC-03: Explain Document / Research Paper).
    Fictional research abstract on distributed indexing.
    """
    doc_content = (
        "Project Nimbus: Efficient Distributed Indexing Architecture.\n"
        "Abstract: We introduce Nimbus, an inverted index partitioning scheme "
        "that reduces query latency by 42% across clusters of heterogeneous nodes. "
        "The core mechanism uses deterministic consistent hashing combined with "
        "bounded token buffering."
    )

    item_doc = ContextItem(
        item_id="ctx-doc-001",
        context_type=ContextType.DOCUMENT,
        source="nimbus_paper.pdf",
        content=doc_content,
        metadata={"page": 1, "section": "Abstract"},
    )

    item_app = ContextItem(
        item_id="ctx-app-001",
        context_type=ContextType.APPLICATION,
        source="PDF Reader",
        content="Current document: nimbus_paper.pdf (Page 1 of 12). Zoom: 125%",
        metadata={"window": "PDF Reader - Nimbus Paper"},
    )

    return [item_doc, item_app]


def get_synthetic_file_action_scenario() -> List[ContextItem]:
    """
    Fixture 3 (UC-08: Controlled File Operation / Action).
    Fictional file reorganization task requiring sensitive confirmation.
    """
    item_file = ContextItem(
        item_id="ctx-file-001",
        context_type=ContextType.RETRIEVAL,
        source="File System",
        content="Found 3 report files: ['report_q1.pdf', 'report_q2.pdf', 'report_summary.docx']. Target folder: 'archive/2026/'.",
        metadata={"action_candidate": "move_files", "destination": "archive/2026/"},
    )

    return [item_file]
