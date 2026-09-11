"""State management for agentic load testing."""

from typing import TypedDict, List, Dict, Any, Optional
from datetime import datetime


class AgenticLoadTestState(TypedDict, total=False):
    """
    State machine for agentic load testing workflow.

    Workflow:
    1. raw_config: Excel input
    2. parsed_config: ConfigParserAgent analyzes API
    3. generated_data: DataGeneratorAgent creates test data
    4. locustfile: LocustGeneratorAgent creates optimized file
    5. execution_metrics: ExecutorAgent runs and monitors
    6. analysis: AnalyzerAgent provides insights
    7. report: ReporterAgent generates final report
    """

    # Input
    raw_config: Dict[str, Any]  # Parsed Excel data
    excel_filename: str
    custom_suggestions: Optional[str]  # User-provided suggestions for AI analysis
    validated_suggestions: Optional[str]  # AI-validated suggestions (filtered)

    # ConfigParserAgent output
    parsed_config: Dict[str, Any]
    api_type: str  # authentication, crud, search, transaction, etc.
    required_fields: List[str]  # Fields needed in test_data
    recommended_users: int
    recommended_spawn_rate: float
    recommended_think_time: Dict[str, float]  # {"min": 1.0, "max": 3.0}
    recommended_data_mode: str

    # DataGeneratorAgent output
    generated_data: List[Dict[str, Any]]  # Test data array
    data_generation_method: str  # "ai", "faker", "hybrid"

    # LocustGeneratorAgent output
    locustfile_path: str
    locustfile_content: str

    # ExecutorAgent output
    execution_metrics: Dict[str, Any]
    test_id: str
    test_status: str  # running, completed, stopped, error

    # AnalyzerAgent output
    analysis: Dict[str, Any]
    bottlenecks: List[str]
    recommendations: List[str]
    sla_compliance: Dict[str, Any]

    # ReporterAgent output
    report_path: str
    report_summary: str

    # Metadata
    session_id: str
    started_at: datetime
    completed_at: Optional[datetime]
    current_agent: str
    agent_phase: str  # parsing, generating_data, creating_locustfile, executing, analyzing, reporting

    # Agent thoughts (for SSE streaming)
    agent_thoughts: List[Dict[str, Any]]  # [{"agent": "ConfigParserAgent", "thought": "...", "timestamp": ...}]

    # Errors
    errors: List[str]


class AgentThought(TypedDict):
    """Represents a thought/action from an agent."""
    agent: str
    thought: str
    reasoning: str
    timestamp: datetime
    phase: str


class AgentDelegation(TypedDict):
    """Represents delegation from one agent to another."""
    from_agent: str
    to_agent: str
    reason: str
    timestamp: datetime


class AgentProgress(TypedDict):
    """Represents progress through the agentic workflow."""
    current_step: int
    total_steps: int
    step_name: str
    progress_percent: float
    status: str  # in_progress, completed, error
