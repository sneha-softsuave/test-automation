"""
Parser Sub-Agent

Specialized agent for parsing raw test cases into structured format.
Uses the ParserTool which wraps the EnhancedJsonParserAgent.
"""

from typing import Dict, Any, List, Optional, Callable

from .base_sub_agent import BaseSubAgent
from ..tools import ParserTool


class ParserAgent(BaseSubAgent):
    """
    Parser Agent - Specializes in parsing test cases.

    Uses ParserTool to:
    - Parse raw Excel test data
    - Generate Playwright selectors using LLM
    - Structure test cases for execution
    """

    def __init__(
        self,
        llm_provider: str = "groq",
        model: Optional[str] = None,
        broadcast_func: Optional[Callable] = None
    ):
        super().__init__(
            name="ParserAgent",
            role="Test Parser - I convert raw test cases into structured format",
            llm_provider=llm_provider,
            model=model,
            broadcast_func=broadcast_func
        )

        # Initialize the parser tool
        self.parser_tool = ParserTool(
            llm_provider=llm_provider,
            model=model
        )

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse raw test cases using the ParserTool.

        Args:
            task: {
                "raw_data": List of raw test cases from Excel,
                "project_name": Optional project name,
                "base_url": Optional base URL
            }

        Returns:
            {
                "success": bool,
                "parsed_suite": Parsed test suite,
                "statistics": Parsing statistics,
                "error": Error message if failed
            }
        """
        raw_data = task.get("raw_data", [])
        project_name = task.get("project_name", "Test Project")
        base_url = task.get("base_url")

        self.broadcast({
            "type": "sub_agent_started",
            "node": "parse",
            "message": f"ParserAgent parsing {len(raw_data)} test cases..."
        })

        self.log(f"Starting to parse {len(raw_data)} test cases")

        # Validate input
        if not raw_data:
            error_msg = "No raw test data provided"
            self.log(error_msg, level="error")
            self.broadcast({
                "type": "sub_agent_completed",
                "node": "parse",
                "status": "error",
                "message": error_msg
            })
            return {
                "success": False,
                "parsed_suite": None,
                "statistics": None,
                "error": error_msg
            }

        # Use the parser tool
        result = self.parser_tool.execute(
            raw_data=raw_data,
            project_name=project_name,
            base_url=base_url
        )

        if result["success"]:
            stats = result["statistics"]
            self.log(f"Parsed {stats['total_test_cases']} test cases with {stats['total_steps']} steps")
            self.broadcast({
                "type": "sub_agent_completed",
                "node": "parse",
                "message": f"Parsed {stats['total_test_cases']} test cases with {stats['total_steps']} steps",
                "data": stats
            })
        else:
            self.log(f"Parsing failed: {result['error']}", level="error")
            self.broadcast({
                "type": "sub_agent_completed",
                "node": "parse",
                "status": "error",
                "message": f"Parsing failed: {result['error']}"
            })

        return result

    def analyze_test_complexity(self, raw_data: List[Dict]) -> Dict[str, Any]:
        """
        Analyze the complexity of test cases before parsing.

        Uses LLM to provide insights about the test suite.
        """
        if not raw_data:
            return {"complexity": "unknown", "insights": []}

        # Build summary for LLM
        test_summary = []
        for tc in raw_data[:5]:  # Sample first 5
            test_summary.append(f"- {tc.get('Test Case', 'Unnamed')}")

        prompt = f"""Analyze these test cases and provide complexity assessment:

Test Cases:
{chr(10).join(test_summary)}

Provide:
1. Overall complexity (simple/moderate/complex)
2. Key insights (2-3 bullet points)
3. Potential challenges

Respond in 3-4 sentences."""

        try:
            analysis = self.think(prompt)
            return {
                "complexity": "moderate",
                "insights": analysis,
                "test_count": len(raw_data)
            }
        except Exception as e:
            self.log(f"Complexity analysis failed: {e}", level="warning")
            return {
                "complexity": "unknown",
                "insights": str(e),
                "test_count": len(raw_data)
            }
