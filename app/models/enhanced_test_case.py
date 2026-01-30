"""
Enhanced Test Case Models - Rich structure for Playwright test generation.
Includes selector hints, assertions, test data, and common selectors.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class Assertion(BaseModel):
    """Individual assertion for a test step."""
    type: str  # url, text, heading, toast, status, element, etc.
    expected_value: str
    playwright_assertion: str  # e.g., "expect(page).toHaveURL()"


class SelectorHints(BaseModel):
    """Hints for finding elements on the page."""
    element_name: Optional[str] = None
    element_type: Optional[str] = None  # input, button, heading, link, etc.
    suggested_selectors: List[str] = Field(default_factory=list)


class ActionInfo(BaseModel):
    """Information about the action to perform."""
    type: str  # goto, click, fill, assert, wait, select, upload, capture, etc.
    playwright_method: str  # e.g., "page.goto()", "page.click()"


class TestStep(BaseModel):
    """A single test step with all metadata."""
    step_number: int
    instruction: str  # Human-readable description
    action: ActionInfo
    selector_hints: SelectorHints = Field(default_factory=SelectorHints)
    test_data: Optional[Dict[str, Any]] = None
    assertions: Optional[List[Assertion]] = None


class EnhancedTestCase(BaseModel):
    """A complete test case with steps and expected results."""
    id: str
    name: str
    steps: List[TestStep]
    expected_results: List[str] = Field(default_factory=list)


class LoginSelectors(BaseModel):
    """Common login-related selectors."""
    email_field: Optional[str] = None
    password_field: Optional[str] = None
    login_button: Optional[str] = None


class NavigationSelectors(BaseModel):
    """Common navigation-related selectors."""
    sidebar: Optional[str] = None
    dashboard_heading: Optional[str] = None


class CommonElements(BaseModel):
    """Common UI element selectors."""
    toast_message: Optional[str] = None
    loader: Optional[str] = None
    popup: Optional[str] = None
    continue_button: Optional[str] = None
    submit_button: Optional[str] = None
    add_button: Optional[str] = None


class CommonSelectors(BaseModel):
    """All common selectors grouped by category."""
    login: LoginSelectors = Field(default_factory=LoginSelectors)
    navigation: NavigationSelectors = Field(default_factory=NavigationSelectors)
    common_elements: CommonElements = Field(default_factory=CommonElements)


class DefaultCredentials(BaseModel):
    """Default login credentials for testing."""
    email: str
    password: str


class SampleClient(BaseModel):
    """Sample client data for testing."""
    name: str
    industry: str
    location: str


class SampleProject(BaseModel):
    """Sample project data for testing."""
    name: str
    location: str
    work_site: str
    description: str


class TestData(BaseModel):
    """Test data definitions."""
    default_credentials: Optional[DefaultCredentials] = None
    sample_incident_text: Optional[str] = None
    sample_client: Optional[SampleClient] = None
    sample_project: Optional[SampleProject] = None


class EnhancedTestSuite(BaseModel):
    """
    Complete test suite with project metadata, common selectors, test data, and test cases.
    This is the main output structure from the enhanced JSON parser.
    """
    project: str
    base_url: str
    common_selectors: CommonSelectors = Field(default_factory=CommonSelectors)
    test_data: TestData = Field(default_factory=TestData)
    test_cases: List[EnhancedTestCase]


# Input models for API endpoints
class EnhancedTestSuiteInput(BaseModel):
    """Input model for enhanced test suite data."""
    data: List[Dict[str, Any]]  # Raw test case data from Excel/JSON
    project_name: Optional[str] = "Automation Project"
    base_url: Optional[str] = None


class EnhancedParseResult(BaseModel):
    """Result of enhanced parsing."""
    success: bool
    project: str
    base_url: str
    total_test_cases: int
    total_steps: int
    common_selectors: Dict[str, Any]
    test_data: Dict[str, Any]
    test_cases: List[Dict[str, Any]]
    errors: List[str] = Field(default_factory=list)
