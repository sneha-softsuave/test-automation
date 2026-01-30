"""
Parser Tool - Wraps the parse-enhanced API

This tool allows agents to parse raw test cases into structured format
using the existing EnhancedJsonParserAgent.
"""

from typing import Dict, Any, List, Optional
from app.agents.enhanced_json_parser import EnhancedJsonParserAgent
from app.agents.base_agent import LLMProvider


class ParserTool:
    """
    Tool for parsing raw test cases into structured format.

    Wraps the EnhancedJsonParserAgent which uses LLM to:
    - Extract test steps from natural language
    - Generate Playwright selectors
    - Structure test data for execution
    """

    name = "parse_test_cases"
    description = "Parse raw Excel test cases into structured format with Playwright selectors"

    def __init__(
        self,
        llm_provider: str = "groq",
        model: Optional[str] = None
    ):
        self.llm_provider = llm_provider
        self.model = model

    def execute(
        self,
        raw_data: List[Dict],
        project_name: str = "Test Project",
        base_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Parse raw test cases into structured format.

        Args:
            raw_data: List of raw test cases from Excel
                      [{"T.C.No": 1, "Test Case": "...", "Test Case Steps": "...", "Expected Result": "..."}]
            project_name: Name for the test project
            base_url: Base URL for test execution

        Returns:
            {
                "success": bool,
                "parsed_suite": {
                    "project": str,
                    "base_url": str,
                    "test_cases": [...],
                    ...
                },
                "statistics": {
                    "total_test_cases": int,
                    "total_steps": int,
                    "total_assertions": int
                },
                "error": str or None
            }
        """
        try:
            print(f"[ParserTool] Parsing {len(raw_data)} test cases...")

            # Use the existing EnhancedJsonParserAgent
            provider = LLMProvider(self.llm_provider.lower())
            parser = EnhancedJsonParserAgent(
                provider=provider,
                model=self.model
            )

            # Parse the raw data
            parsed_suite = parser.parse_to_enhanced_structure(
                raw_data=raw_data,
                project_name=project_name,
                base_url=base_url
            )

            # Calculate statistics
            test_cases = parsed_suite.get("test_cases", [])
            total_steps = sum(len(tc.get("steps", [])) for tc in test_cases)
            total_assertions = sum(
                sum(len(step.get("assertions", []) or []) for step in tc.get("steps", []))
                for tc in test_cases
            )

            print(f"[ParserTool] Parsed {len(test_cases)} test cases with {total_steps} steps")

            return {
                "success": True,
                "parsed_suite": parsed_suite,
                "statistics": {
                    "total_test_cases": len(test_cases),
                    "total_steps": total_steps,
                    "total_assertions": total_assertions
                },
                "error": None
            }

        except Exception as e:
            error_msg = str(e)
            print(f"[ParserTool] Error: {error_msg}")
            return {
                "success": False,
                "parsed_suite": None,
                "statistics": None,
                "error": error_msg
            }
