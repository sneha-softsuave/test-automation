"""
Parse Node - Calls the same function as /api/v1/parse-enhanced

Uses EnhancedJsonParserAgent.parse_to_enhanced_structure() exactly like the API.
"""

from typing import Dict, Any

from app.agents.deep_agent.state import TestAutomationState
from app.agents.enhanced_json_parser import EnhancedJsonParserAgent
from app.agents.base_agent import LLMProvider
from app.core.config import settings


def parse_node(state: TestAutomationState) -> Dict[str, Any]:
    """
    Parse raw test data into enhanced test suite structure.

    This calls the EXACT same code as /api/v1/parse-enhanced endpoint.
    """
    broadcast = state.get("broadcast_func")

    if broadcast:
        broadcast({
            "type": "node_started",
            "node": "parse",
            "message": "Parsing test cases with LLM..."
        })

    try:
        # Get configuration (same as API endpoint)
        provider_str = state.get("llm_provider", "groq").lower()
        model = state.get("model")

        # Map provider string to enum (same as API)
        provider = LLMProvider(provider_str)

        # Get model from settings if not provided (same as API)
        if not model:
            model_map = {
                "openai": settings.OPENAI_MODEL,
                "anthropic": settings.ANTHROPIC_MODEL,
                "groq": settings.GROQ_MODEL
            }
            model = model_map.get(provider_str, settings.GROQ_MODEL)

        raw_data = state.get("raw_data", [])
        project_name = state.get("project_name", "Test Suite")
        base_url = state.get("base_url")

        print(f"[Parse Node] Provider: {provider_str}, Model: {model}")
        print(f"[Parse Node] Project: {project_name}, Raw data items: {len(raw_data)}")

        # Validate raw_data has content
        if not raw_data:
            error_msg = "No raw test data provided - raw_data is empty"
            print(f"[Parse Node] ERROR: {error_msg}")
            if broadcast:
                broadcast({
                    "type": "node_completed",
                    "node": "parse",
                    "status": "error",
                    "message": error_msg
                })
            errors = state.get("errors", [])
            errors.append(error_msg)
            return {
                "parsed_suite": None,
                "current_step": "parse_failed",
                "errors": errors
            }

        # Log first test case for debugging
        print(f"[Parse Node] First test case keys: {list(raw_data[0].keys()) if raw_data else 'N/A'}")
        print(f"[Parse Node] First test case: {raw_data[0] if raw_data else 'N/A'}")

        if broadcast:
            broadcast({
                "type": "thoughts",
                "message": f"Processing {len(raw_data)} test case(s) with {provider_str}/{model}..."
            })

        # Retry configuration (same as API endpoint)
        max_retries = 3
        last_error = None
        parsed_suite = None

        for attempt in range(1, max_retries + 1):
            try:
                print(f"[Parse Node] Attempt {attempt}/{max_retries}")

                if attempt > 1 and broadcast:
                    broadcast({
                        "type": "thoughts",
                        "message": f"Retrying parse... (attempt {attempt}/{max_retries})"
                    })

                # Initialize parser (SAME as API endpoint)
                parser = EnhancedJsonParserAgent(provider=provider, model=model)

                # Parse to enhanced structure (SAME as API endpoint)
                parsed_suite = parser.parse_to_enhanced_structure(
                    raw_data=raw_data,
                    project_name=project_name,
                    base_url=base_url
                )

                # Success - break out of retry loop
                break

            except ValueError as e:
                last_error = e
                print(f"[Parse Node] Attempt {attempt} failed: {str(e)}")
                if attempt < max_retries:
                    import time
                    time.sleep(1)  # Brief delay before retry
                continue

        # Check if parsing succeeded
        if parsed_suite is None:
            raise ValueError(f"Failed after {max_retries} attempts: {str(last_error)}")

        # Get statistics (SAME as API endpoint)
        stats = parser.get_statistics(parsed_suite)

        print(f"[Parse Node] Parsed {stats['total_test_cases']} test cases with {stats['total_steps']} steps")

        if broadcast:
            broadcast({
                "type": "node_completed",
                "node": "parse",
                "message": f"Parsed {stats['total_test_cases']} test cases with {stats['total_steps']} steps",
                "data": stats
            })

        return {
            "parsed_suite": parsed_suite,
            "current_step": "parsing_complete",
            "errors": state.get("errors", [])
        }

    except Exception as e:
        import traceback
        error_msg = f"Parse error: {str(e)}"
        print(f"[Parse Node] ERROR: {error_msg}")
        print(traceback.format_exc())

        errors = state.get("errors", [])
        errors.append(error_msg)

        if broadcast:
            broadcast({
                "type": "node_completed",
                "node": "parse",
                "status": "error",
                "message": error_msg
            })

        return {
            "parsed_suite": None,
            "current_step": "parse_failed",
            "errors": errors
        }
