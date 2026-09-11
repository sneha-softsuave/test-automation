"""
Deep Agent State Definition

Defines the TypedDict that flows through the LangGraph state machine.
All nodes read from and write to this shared state.
"""

from typing import TypedDict, List, Dict, Any, Optional, Literal


class TestAutomationState(TypedDict, total=False):
    """
    State that flows through the Deep Agent graph.

    All fields are optional (total=False) to allow incremental updates.
    Each node reads what it needs and writes its outputs.
    """

    # ===== Input Data =====
    raw_data: List[Dict[str, Any]]
    """Raw test case data extracted from Excel/JSON upload"""

    project_name: str
    """Name of the test project"""

    base_url: Optional[str]
    """Base URL for test execution"""

    # ===== LLM Configuration =====
    llm_provider: str
    """LLM provider: 'anthropic', 'openai', or 'groq'"""

    model: str
    """Model name to use for parsing"""

    # ===== Session Configuration =====
    session_id: str
    """Unique session ID for SSE updates"""

    headless: bool
    """Whether to run browser in headless mode"""

    keep_browser_open: bool
    """Whether to keep the browser open across all test cases (False = close/reopen per test case)"""

    timeout: int
    """Timeout in milliseconds for Playwright actions"""

    # ===== Processing Results =====
    parsed_suite: Optional[Dict[str, Any]]
    """Parsed test suite from EnhancedJsonParserAgent"""

    execution_results: Optional[Dict[str, Any]]
    """Results from Playwright test execution"""

    # ===== Validation State =====
    validation_status: Literal["pending", "passed", "failed", "needs_retry"]
    """Current validation status"""

    validation_errors: List[str]
    """List of validation error messages"""

    failed_tests: List[Dict[str, Any]]
    """Test cases that failed and may need retry"""

    # ===== Retry Tracking =====
    retry_count: int
    """Current retry attempt number"""

    max_retries: int
    """Maximum number of retry attempts"""

    # ===== Output =====
    report_data: Optional[Dict[str, Any]]
    """Final report data"""

    generated_script: Optional[str]
    """Generated Playwright Python script"""

    # ===== Progress Tracking =====
    current_step: str
    """Current step in the pipeline for UI display"""

    errors: List[str]
    """List of error messages encountered"""

    # ===== SSE Broadcasting =====
    broadcast_func: Any
    """Function to broadcast SSE events (injected at runtime)"""

    # ===== Step Control =====
    step_control_file: Optional[str]
    """Path to temp signal file for next/skip signals from the frontend (injected at runtime)"""

    stop_event: Any
    """threading.Event to signal executor to stop (injected at runtime)"""


def create_initial_state(
    raw_data: List[Dict[str, Any]],
    project_name: str,
    session_id: str,
    base_url: Optional[str] = None,
    llm_provider: str = "groq",
    model: str = "llama-3.1-8b-instant",
    headless: bool = True,
    keep_browser_open: bool = True,
    timeout: int = 30000,
    max_retries: int = 2,
    broadcast_func: Any = None
) -> TestAutomationState:
    """
    Create initial state for the Deep Agent graph.

    Args:
        raw_data: Raw test case data from Excel/JSON
        project_name: Name of the test project
        session_id: Unique session ID for SSE
        base_url: Base URL for tests
        llm_provider: LLM provider to use
        model: Model name
        headless: Run browser headless
        timeout: Playwright timeout in ms
        max_retries: Max retry attempts
        broadcast_func: SSE broadcast function

    Returns:
        Initial TestAutomationState
    """
    return TestAutomationState(
        # Input
        raw_data=raw_data,
        project_name=project_name,
        base_url=base_url,

        # LLM Config
        llm_provider=llm_provider,
        model=model,

        # Session Config
        session_id=session_id,
        headless=headless,
        keep_browser_open=keep_browser_open,
        timeout=timeout,

        # Processing Results (initially None)
        parsed_suite=None,
        execution_results=None,

        # Validation (initially pending)
        validation_status="pending",
        validation_errors=[],
        failed_tests=[],

        # Retry Tracking
        retry_count=0,
        max_retries=max_retries,

        # Output (initially None)
        report_data=None,
        generated_script=None,

        # Progress
        current_step="initializing",
        errors=[],

        # SSE
        broadcast_func=broadcast_func,

        # Step Control
        step_control_file=None,
        stop_event=None,
    )
