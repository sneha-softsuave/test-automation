import json
from typing import Dict, Any, List, Optional

from app.core.config import settings
from app.services.excel_service import ExcelService
from app.agents.json_parser_agent import JsonParserAgent, LLMProvider


class TestCaseService:
    """Service for handling test case parsing and generation."""

    def __init__(self):
        self.excel_service = ExcelService()

    def parse_excel_to_test_cases(
        self,
        content: bytes,
        filename: str,
        provider: LLMProvider
    ) -> Dict[str, Any]:
        """
        Parse Excel content to structured test cases using LLM agent.

        Args:
            content: Excel file content as bytes
            filename: Name of the file
            provider: LLM provider to use

        Returns:
            Dictionary with parsed test cases and metadata
        """
        print(f"\n{'='*50}")
        print(f"JSON Parser Agent - Processing: {filename}")
        print(f"LLM Provider: {provider.value}")
        print(f"{'='*50}\n")

        # Read Excel with headers
        headers, rows_data = self.excel_service.read_excel_with_headers(content, filename)

        # Initialize JSON Parser Agent with selected provider
        print(f"Initializing JSON Parser Agent with {provider.value}...")
        agent = JsonParserAgent(
            provider=provider,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
            openai_api_key=settings.OPENAI_API_KEY,
            groq_api_key=settings.GROQ_API_KEY
        )

        # Parse Excel data to test cases
        print("Parsing Excel data to test cases...")
        test_cases = agent.parse_excel_to_test_cases(rows_data, headers)

        # Validate test cases
        print("Validating test cases...")
        validated_test_cases = agent.validate_test_cases(test_cases)

        print(f"\n{'='*50}")
        print(f"Successfully parsed {len(validated_test_cases)} test cases")
        print(f"{'='*50}\n")

        # Print parsed JSON to terminal
        print("\nGenerated Test Cases JSON:")
        print(json.dumps(test_cases, indent=2))

        # Get model name for response
        model_map = {
            LLMProvider.ANTHROPIC: settings.ANTHROPIC_MODEL,
            LLMProvider.OPENAI: settings.OPENAI_MODEL,
            LLMProvider.GROQ: settings.GROQ_MODEL,
        }

        return {
            "message": "Test cases parsed successfully",
            "filename": filename,
            "llm_provider": provider.value,
            "model": model_map[provider],
            "total_test_cases": len(test_cases),
            "test_cases": test_cases
        }

    def parse_json_to_test_cases(
        self,
        raw_data: List[Dict[str, Any]],
        provider: LLMProvider,
        model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Parse raw JSON test case data to structured test cases using LLM agent.

        Args:
            raw_data: List of raw test case dictionaries
            provider: LLM provider to use
            model: Optional model override

        Returns:
            Dictionary with parsed test cases and metadata
        """
        # Get default model for provider if not specified
        default_model_map = {
            LLMProvider.ANTHROPIC: settings.ANTHROPIC_MODEL,
            LLMProvider.OPENAI: settings.OPENAI_MODEL,
            LLMProvider.GROQ: settings.GROQ_MODEL,
        }

        used_model = model or default_model_map[provider]

        print(f"\n{'='*50}")
        print(f"JSON Parser Agent - Processing JSON Data")
        print(f"LLM Provider: {provider.value}")
        print(f"Model: {used_model}")
        print(f"Total raw test cases: {len(raw_data)}")
        print(f"{'='*50}\n")

        # Initialize JSON Parser Agent with selected provider and model
        print(f"Initializing JSON Parser Agent with {provider.value} - {used_model}...")

        agent_kwargs = {
            "provider": provider,
            "anthropic_api_key": settings.ANTHROPIC_API_KEY,
            "openai_api_key": settings.OPENAI_API_KEY,
            "groq_api_key": settings.GROQ_API_KEY,
        }

        # Override model if specified
        if model:
            if provider == LLMProvider.ANTHROPIC:
                agent_kwargs["anthropic_model"] = model
            elif provider == LLMProvider.OPENAI:
                agent_kwargs["openai_model"] = model
            elif provider == LLMProvider.GROQ:
                agent_kwargs["groq_model"] = model

        agent = JsonParserAgent(**agent_kwargs)

        # Parse JSON data to structured test cases
        print("Parsing JSON data to structured test cases...")
        test_cases = agent.parse_raw_json_to_test_cases(raw_data)

        # Validate test cases
        print("Validating test cases...")
        validated_test_cases = agent.validate_test_cases(test_cases)

        print(f"\n{'='*50}")
        print(f"Successfully parsed {len(validated_test_cases)} test cases")
        print(f"{'='*50}\n")

        # Print parsed JSON to terminal
        print("\nGenerated Test Cases JSON:")
        print(json.dumps(test_cases, indent=2))

        return {
            "message": "Test cases parsed successfully",
            "llm_provider": provider.value,
            "model": used_model,
            "total_test_cases": len(test_cases),
            "test_cases": test_cases
        }
