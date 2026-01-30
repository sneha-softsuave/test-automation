from pydantic import BaseModel
from typing import List, Optional, Any, Dict


class TestAction(BaseModel):
    step: int
    action: str
    selector: Optional[str] = None
    value: Optional[str] = None
    description: str


class TestCase(BaseModel):
    test_id: str
    test_name: str
    base_url: str
    actions: List[TestAction]


class TestCaseCollection(BaseModel):
    test_cases: List[TestCase]


class RawTestCaseInput(BaseModel):
    """Input model for raw test case data from Excel/JSON."""
    data: List[Dict[str, Any]]


class ParsedTestCaseInput(BaseModel):
    """Input model for parsed test cases (output from JSON parser)."""
    test_cases: List[Dict[str, Any]]


class ScriptExecutionInput(BaseModel):
    """Input model for script execution."""
    script: str
    test_id: Optional[str] = "TC_01"


class TestCaseExecutionInput(BaseModel):
    """Input model for executing test cases directly."""
    test_cases: List[Dict[str, Any]]
