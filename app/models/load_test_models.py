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
    headers: Dict[str, str] = Field(default_factory=dict, description="Request headers")
    payload: Optional[Dict[str, Any]] = Field(default=None, description="Request body")
    query_params: Optional[Dict[str, Any]] = Field(default=None, description="Query parameters")
    auth_config: AuthConfig = Field(default_factory=AuthConfig, description="Authentication config")
    description: Optional[str] = Field(default=None, description="API description")
    # Load test configuration (from Excel)
    users: Optional[int] = Field(default=None, description="Number of users for this API")
    spawn_rate: Optional[float] = Field(default=None, description="Spawn rate for this API")
    run_time: Optional[str] = Field(default=None, description="Run time for this API")


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
    config: LoadTestConfig = Field(..., description="Load test configuration")
    session_id: str = Field(..., description="SSE session ID for streaming")


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
    session_id: str = Field(..., description="SSE session ID for streaming")
