"""Pydantic models for load testing functionality."""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class AuthType(str, Enum):
    """Authentication types supported."""
    BEARER = "bearer"
    BASIC = "basic"
    API_KEY = "api_key"
    NONE = "none"


class DataMode(str, Enum):
    """Data cycling modes for multi-user test data."""
    SEQUENTIAL = "sequential"  # User 0 gets row 0, user 1 gets row 1, etc.
    RANDOM = "random"  # Each user gets random row
    ROUND_ROBIN = "round_robin"  # Cycle through rows (default)


class AuthConfig(BaseModel):
    """Authentication configuration."""
    auth_type: AuthType = Field(default=AuthType.NONE)
    token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    api_key_name: Optional[str] = None  # Header name for API key
    api_key_value: Optional[str] = None


class APIConfig(BaseModel):
    """API endpoint configuration parsed from Excel."""
    name: str = Field(..., description="API test name")
    base_url: str = Field(..., description="Base URL of the API")
    endpoint: str = Field(..., description="API endpoint path")
    method: str = Field(default="GET", description="HTTP method")
    headers: Optional[Dict[str, str]] = Field(default_factory=dict, description="Request headers")
    payload: Optional[Dict[str, Any]] = Field(default=None, description="Request body")
    query_params: Optional[Dict[str, Any]] = Field(default=None, description="Query parameters")
    auth_config: AuthConfig = Field(default_factory=AuthConfig, description="Authentication config")
    description: Optional[str] = Field(default=None, description="API description")
    # Load test configuration (from Excel)
    users: Optional[int] = Field(default=None, description="Number of users for this API")
    spawn_rate: Optional[float] = Field(default=None, description="Spawn rate for this API")
    run_time: Optional[str] = Field(default=None, description="Run time for this API")

    # NEW: Multi-user data support (Phase 1)
    test_data: Optional[List[Dict[str, Any]]] = Field(default=None, description="Array of test data sets for multi-user scenarios")
    data_mode: Optional[str] = Field(default="round_robin", description="How to cycle through test data: sequential, random, round_robin")

    # NEW: Configurable think-time
    think_time_min: Optional[float] = Field(default=1.0, description="Minimum wait time between requests in seconds")
    think_time_max: Optional[float] = Field(default=3.0, description="Maximum wait time between requests in seconds")

    # NEW: User journey support (for sequential flows)
    user_journey: Optional[str] = Field(default=None, description="Comma-separated list of API names for sequential execution")

    # NEW: Variable mapping for payload substitution
    variable_mapping: Optional[Dict[str, str]] = Field(default=None, description="Maps {{var}} placeholders to test_data fields")


class LoadTestConfig(BaseModel):
    """Load test execution configuration."""
    users: int = Field(default=10, ge=1, le=10000, description="Number of concurrent users")
    spawn_rate: float = Field(default=1, ge=0.1, le=1000, description="Users spawned per second")
    run_time: str = Field(default="5m", description="Test duration (e.g., 5m, 1h, 30s)")
    host: Optional[str] = Field(default=None, description="Override base URL")


class LoadTestRequest(BaseModel):
    """Request to start a load test."""
    upload_id: str = Field(..., description="Upload session ID")
    selected_api_name: str = Field(..., description="Name of API to test")
    selected_api: Optional[APIConfig] = Field(None, description="Full API configuration (overrides uploaded config)")
    config: LoadTestConfig = Field(..., description="Load test configuration")
    session_id: str = Field(..., description="SSE session ID for streaming")
    llm_provider: Optional[str] = Field(default="groq", description="LLM provider for AI insights")


class MultiAPILoadTestRequest(BaseModel):
    """Request to test multiple APIs."""
    upload_id: str
    selected_api_names: List[str]
    config: LoadTestConfig
    session_id: str


class LoadTestMetrics(BaseModel):
    """Real-time load test metrics."""
    test_id: str
    status: str  # running, completed, failed
    current_users: int = 0
    total_requests: int = 0
    total_failures: int = 0
    requests_per_second: float = 0.0
    failures_per_second: float = 0.0
    avg_response_time: float = 0.0
    min_response_time: float = 0.0
    max_response_time: float = 0.0
    median_response_time: float = 0.0
    percentile_95: float = 0.0
    percentile_99: float = 0.0
    failure_rate: float = 0.0
    elapsed_time: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.now)


class EndpointStats(BaseModel):
    """Statistics for a specific endpoint."""
    method: str
    name: str
    num_requests: int = 0
    num_failures: int = 0
    avg_response_time: float = 0.0
    min_response_time: float = 0.0
    max_response_time: float = 0.0
    median_response_time: float = 0.0
    requests_per_second: float = 0.0
    failures_per_second: float = 0.0


class LoadTestResult(BaseModel):
    """Final load test results."""
    test_id: str
    status: str
    api_name: str
    config: LoadTestConfig
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: float = 0.0
    total_requests: int = 0
    total_failures: int = 0
    requests_per_second: float = 0.0
    avg_response_time: float = 0.0
    percentile_95: float = 0.0
    percentile_99: float = 0.0
    failure_rate: float = 0.0
    endpoint_stats: List[EndpointStats] = Field(default_factory=list)
    error_summary: Dict[str, int] = Field(default_factory=dict)


class ExcelUploadResponse(BaseModel):
    """Response after uploading Excel file."""
    upload_id: str
    filename: str
    total_apis: int
    apis: List[APIConfig]
    message: str


class LoadTestStartResponse(BaseModel):
    """Response when starting a load test."""
    test_id: str
    message: str
    locustfile_path: str
    estimated_duration: str


class ValidationResult(BaseModel):
    """Result of API configuration validation."""
    valid: bool
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    error_message: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class SequentialLoadTestRequest(BaseModel):
    """Request to start sequential load testing of multiple APIs."""
    upload_id: str = Field(..., description="Upload session ID")
    selected_api_names: List[str] = Field(..., description="List of API names to test sequentially")
    selected_apis_config: Optional[List[APIConfig]] = Field(default=None, description="Full API configurations with user edits (overrides uploaded config)")
    session_id: str = Field(..., description="SSE session ID for streaming")
    llm_provider: Optional[str] = Field(default="groq", description="LLM provider for AI insights")


class SuggestionMetrics(BaseModel):
    """Metrics associated with a suggestion."""
    current_value: Optional[float] = None
    target_value: Optional[float] = None
    recommended_users: Optional[int] = None
    recommended_spawn_rate: Optional[float] = None
    recommended_duration: Optional[str] = None
    recommended_think_time_min: Optional[float] = None
    recommended_think_time_max: Optional[float] = None
    improvement_needed: Optional[str] = None
    current_users: Optional[int] = None
    current_spawn_rate: Optional[float] = None
    current_duration: Optional[str] = None
    current_error_rate: Optional[float] = None
    target_error_rate: Optional[float] = None
    failed_requests: Optional[int] = None
    total_requests: Optional[int] = None
    current_p95: Optional[float] = None
    target_p95: Optional[float] = None
    current_p99: Optional[float] = None
    target_p99: Optional[float] = None


class TestSuggestion(BaseModel):
    """Test optimization suggestion."""
    id: str
    type: str = "test_optimization"
    severity: str  # critical, warning, good
    title: str
    description: str
    reasoning: str
    metrics: SuggestionMetrics


class APISuggestion(BaseModel):
    """API performance suggestion."""
    id: str
    type: str = "api_performance"
    severity: str  # critical, warning, good
    category: str  # response_time, error_rate, scalability, infrastructure
    title: str
    description: str
    high_level: str
    technical: str
    metrics: SuggestionMetrics


class AIAnalysis(BaseModel):
    """AI-powered test analysis."""
    test_id: str
    performance_score: int  # 0-100
    performance_level: str  # critical, warning, good
    test_suggestions: List[TestSuggestion]
    api_suggestions: List[APISuggestion]
    generated_at: str
