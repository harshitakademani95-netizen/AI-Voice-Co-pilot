"""
Exactly Two Harmless Mock Tools for the Agentic Workflow Engine (W4).

Per project requirements:
1. Tool 1: Mock Task Checker (`mock_task_checker`)
   - Accepts sample task data.
   - Returns a simulated task status.
   - Non-consequential (safe, informational).
   - Performs no real external operations.

2. Tool 2: Mock Report Generator (`mock_report_generator`)
   - Accepts sample data or task-checker output.
   - Generates a simulated report in mock memory.
   - Consequential action (`is_consequential=True`, `risk_level=RiskLevel.SENSITIVE`).
   - Requires explicit human approval before execution.

Strict Boundaries:
- Runs strictly in mock mode using in-memory objects.
- Exactly two registered mock tools exist.
- No real APIs, no external network transmission, and no unrestricted computer control.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional
import uuid

from agentic_workflow.schemas import RiskLevel, ToolSpec


class ToolExecutionError(Exception):
    """Raised when a mock tool fails validation or execution."""
    pass


# Local in-memory sample database and storage for mock execution
_MOCK_TASK_DATABASE: Dict[str, Dict[str, Any]] = {
    "task-audit-101": {
        "task_id": "task-audit-101",
        "name": "Quarterly Codebase Audit",
        "status": "completed",
        "items_analyzed": 142,
        "anomalies": 0,
    },
    "task-sync-202": {
        "task_id": "task-sync-202",
        "name": "Dependency Vulnerability Scan",
        "status": "completed",
        "items_analyzed": 58,
        "anomalies": 1,
    },
}

_MOCK_GENERATED_REPORTS: Dict[str, Dict[str, Any]] = {}


def mock_task_checker(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tool 1: Mock Task Checker
    Accepts sample task data and returns a simulated status.
    Informational and non-consequential.
    """
    task_id = inputs.get("task_id")
    if not task_id or not isinstance(task_id, str):
        raise ToolExecutionError("Parameter 'task_id' is required and must be a non-empty string.")

    # Retrieve from local mock database or return default simulated status
    if task_id in _MOCK_TASK_DATABASE:
        data = _MOCK_TASK_DATABASE[task_id]
        return {
            "status": "success",
            "task_id": task_id,
            "task_status": data["status"],
            "details": data,
            "simulated": True,
        }

    # For unknown task_id in mock mode, return standard simulated task status
    return {
        "status": "success",
        "task_id": task_id,
        "task_status": "in_progress",
        "details": {"items_analyzed": 10, "anomalies": 0},
        "simulated": True,
    }


def mock_report_generator(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tool 2: Mock Report Generator
    Accepts sample data or task-checker output and generates a simulated report.
    Consequential action requiring explicit approval before execution.
    """
    title = inputs.get("title") or inputs.get("report_title")
    sample_data = inputs.get("sample_data") or inputs.get("details")

    if not title or not isinstance(title, str) or not title.strip():
        raise ToolExecutionError("Parameter 'title' (or 'report_title') is required and must be a non-empty string.")

    report_id = f"rep-{uuid.uuid4().hex[:8]}"
    report_entry = {
        "report_id": report_id,
        "title": title,
        "data_summary": sample_data or "Standard simulated report body",
        "generated_by": "mock_report_generator",
        "simulated": True,
    }
    _MOCK_GENERATED_REPORTS[report_id] = report_entry

    return {
        "status": "success",
        "report_id": report_id,
        "title": title,
        "summary": f"Simulated report '{title}' generated successfully.",
        "simulated": True,
    }


# Formal Tool Specifications
TASK_CHECKER_SPEC = ToolSpec(
    name="mock_task_checker",
    description="Accepts sample task data and returns a simulated task status (harmless, informational).",
    input_requirements={
        "task_id": {"type": "string", "description": "Identifier of the task to inspect"}
    },
    is_consequential=False,
    risk_level=RiskLevel.INFORMATIONAL,
)

REPORT_GENERATOR_SPEC = ToolSpec(
    name="mock_report_generator",
    description="Accepts sample data or task-checker output and generates a simulated report (consequential).",
    input_requirements={
        "title": {"type": "string", "description": "Title of the report to generate"},
        "sample_data": {"type": "object", "description": "Optional payload or task checker metrics to summarize"}
    },
    is_consequential=True,
    risk_level=RiskLevel.SENSITIVE,
)


class ToolRegistry:
    """
    Registry strictly containing ONLY the two permitted harmless mock tools.
    Rejects any unapproved or foreign tool invocations.
    """

    def __init__(self):
        self._tools: Dict[str, Callable[[Dict[str, Any]], Any]] = {}
        self._specs: Dict[str, ToolSpec] = {}

        # Register exclusively the two harmless mock tools
        self._register(TASK_CHECKER_SPEC, mock_task_checker)
        self._register(REPORT_GENERATOR_SPEC, mock_report_generator)

    def _register(self, spec: ToolSpec, func: Callable[[Dict[str, Any]], Any]) -> None:
        self._specs[spec.name] = spec
        self._tools[spec.name] = func

    def get_spec(self, name: str) -> Optional[ToolSpec]:
        """Retrieve specification for a tool."""
        return self._specs.get(name)

    def is_registered(self, name: str) -> bool:
        """Check if tool name is registered."""
        return name in self._tools

    def is_consequential(self, name: str) -> bool:
        """Check if tool is classified as consequential."""
        spec = self.get_spec(name)
        if spec is None:
            raise ToolExecutionError(f"Tool '{name}' is not registered.")
        return spec.is_consequential

    def execute(self, name: str, inputs: Dict[str, Any]) -> Any:
        """
        Execute tool strictly within mock mode.

        Raises:
            ToolExecutionError: If tool is unknown or arguments are invalid.
        """
        if name not in self._tools:
            raise ToolExecutionError(
                f"Security violation: Tool '{name}' is not in the permitted harmless mock tools registry."
            )
        func = self._tools[name]
        return func(inputs)

    @property
    def available_tools(self) -> Dict[str, ToolSpec]:
        """Return read-only dictionary of registered tools."""
        return dict(self._specs)


def reset_mock_tools_state() -> None:
    """Reset simulated storage for test isolation."""
    global _MOCK_GENERATED_REPORTS
    _MOCK_GENERATED_REPORTS.clear()
