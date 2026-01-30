"""
Agent Chat API Routes

Provides conversational interface for the test automation agent.
Users can ask questions about uploaded test cases or give commands.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import re

from app.agents.base_agent import LLMProvider
from app.core.config import settings


class ChatLLM:
    """Simple LLM wrapper for chat responses."""

    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        anthropic_api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        groq_api_key: Optional[str] = None,
    ):
        self.provider = provider
        self.model = model
        self.max_tokens = 4000

        # Initialize client based on provider (lazy imports)
        if provider == LLMProvider.ANTHROPIC:
            import anthropic
            self.client = anthropic.Anthropic(api_key=anthropic_api_key)
        elif provider == LLMProvider.OPENAI:
            import openai
            self.client = openai.OpenAI(api_key=openai_api_key)
        elif provider == LLMProvider.GROQ:
            from groq import Groq
            self.client = Groq(api_key=groq_api_key)

    def call_llm(self, prompt: str) -> str:
        """Call the LLM with the given prompt."""
        try:
            if self.provider == LLMProvider.ANTHROPIC:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.content[0].text.strip()

            elif self.provider == LLMProvider.OPENAI:
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.choices[0].message.content.strip()

            elif self.provider == LLMProvider.GROQ:
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.choices[0].message.content.strip()

        except Exception as e:
            print(f"[ChatLLM] Error calling LLM: {e}")
            raise


router = APIRouter(prefix="/agent", tags=["Agent Chat"])


class ChatRequest(BaseModel):
    message: str
    test_cases: Optional[List[Dict[str, Any]]] = None
    parsed_suite: Optional[Dict[str, Any]] = None
    llm_provider: str = "groq"
    model: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    intent: str  # 'question', 'execute', 'list', 'help', 'unknown'
    execute_tests: Optional[List[int]] = None  # If intent is 'execute', which tests to run


CHAT_SYSTEM_PROMPT = """You are a helpful Test Automation Assistant. You help users understand and work with their test cases.

You have access to the user's uploaded test cases. Answer questions about them clearly and concisely.

IMPORTANT RULES:
1. If the user asks a question about the test cases (what, how, which, explain, describe, etc.), answer based on the test data provided.
2. If the user wants to execute/run tests, respond with: "I'll execute [test description]. Starting now..."
3. Keep responses concise but helpful.
4. Use markdown formatting for clarity (bold, lists, etc.).
5. If no test data is provided and user asks about tests, tell them to upload a file first.

TEST DATA CONTEXT:
{test_context}

USER MESSAGE: {user_message}

Respond naturally and helpfully:"""


def detect_intent(message: str) -> tuple[str, Optional[List[int]]]:
    """Detect user intent from message."""
    msg_lower = message.lower().strip()

    # Execute/Run commands
    execute_patterns = [
        r'(execute|run|start|test)\s+(all|everything)',
        r'(execute|run|start)\s+test\s*(\d+)',
        r'(execute|run|start)\s+tests?\s*([\d,\s]+)',
        r'run\s+tc[_]?(\d+)',
    ]

    for pattern in execute_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            # Extract test numbers
            if 'all' in msg_lower or 'everything' in msg_lower:
                return 'execute', None  # None means all

            numbers = re.findall(r'\d+', message)
            if numbers:
                return 'execute', [int(n) for n in numbers]

    # List commands
    if any(word in msg_lower for word in ['list', 'show all', 'what tests', 'which tests', 'available tests']):
        return 'list', None

    # Help commands
    if msg_lower in ['help', '?', 'commands', 'what can you do']:
        return 'help', None

    # View commands
    if any(phrase in msg_lower for phrase in ['view results', 'show results', 'view suite', 'show suite']):
        return 'view', None

    # Questions (likely need LLM response)
    question_indicators = ['what', 'how', 'why', 'when', 'where', 'which', 'who', 'explain', 'describe', 'tell me', 'can you', '?']
    if any(indicator in msg_lower for indicator in question_indicators):
        return 'question', None

    # Default to question if we have test data, otherwise unknown
    return 'question', None


def format_test_context(test_cases: List[Dict], parsed_suite: Optional[Dict] = None) -> str:
    """Format test cases into context string for LLM."""
    if not test_cases and not parsed_suite:
        return "No test data uploaded yet."

    context_parts = []

    # Raw test cases
    if test_cases:
        context_parts.append(f"UPLOADED TEST CASES ({len(test_cases)} total):")
        for tc in test_cases[:10]:  # Limit to first 10 to avoid token limits
            tc_no = tc.get('T.C.No', 'N/A')
            tc_name = tc.get('Test Case', 'Unnamed')
            tc_steps = tc.get('Test Case Steps', '')[:500]  # Truncate long steps
            tc_expected = tc.get('Expected Result', '')[:200]

            context_parts.append(f"""
Test Case {tc_no}: {tc_name}
Steps: {tc_steps}
Expected: {tc_expected}
---""")

    # Parsed suite (if available)
    if parsed_suite and parsed_suite.get('test_cases'):
        context_parts.append(f"\nPARSED TEST SUITE:")
        context_parts.append(f"Project: {parsed_suite.get('project', 'N/A')}")
        context_parts.append(f"Base URL: {parsed_suite.get('base_url', 'N/A')}")
        context_parts.append(f"Total Test Cases: {len(parsed_suite.get('test_cases', []))}")

        for tc in parsed_suite.get('test_cases', [])[:5]:
            context_parts.append(f"- {tc.get('id', 'N/A')}: {tc.get('name', 'Unnamed')} ({len(tc.get('steps', []))} steps)")

    return "\n".join(context_parts)


@router.post("/chat", response_model=ChatResponse)
async def chat_with_agent(request: ChatRequest):
    """
    Chat with the test automation agent.

    The agent can:
    - Answer questions about uploaded test cases
    - Understand execute commands and return which tests to run
    - Provide help and guidance
    """
    message = request.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Detect intent
    intent, test_numbers = detect_intent(message)

    # Handle non-LLM intents quickly
    if intent == 'execute':
        if not request.test_cases:
            return ChatResponse(
                response="Please upload a test file first before executing tests.",
                intent='execute',
                execute_tests=None
            )

        if test_numbers is None:  # Execute all
            return ChatResponse(
                response=f"I'll execute all {len(request.test_cases)} test case(s). Starting now...",
                intent='execute',
                execute_tests=None  # None means all
            )
        else:
            # Validate test numbers exist
            available = [tc.get('T.C.No') for tc in request.test_cases]
            valid_tests = [n for n in test_numbers if n in available]

            if not valid_tests:
                return ChatResponse(
                    response=f"Test number(s) {test_numbers} not found. Available: {available}",
                    intent='error',
                    execute_tests=None
                )

            return ChatResponse(
                response=f"I'll execute test case(s): {valid_tests}. Starting now...",
                intent='execute',
                execute_tests=valid_tests
            )

    if intent == 'list':
        if not request.test_cases:
            return ChatResponse(
                response="No test cases uploaded yet. Please upload an Excel or JSON file first.",
                intent='list',
                execute_tests=None
            )

        test_list = "\n".join([
            f"**{tc.get('T.C.No', 'N/A')}** - {tc.get('Test Case', 'Unnamed')}"
            for tc in request.test_cases
        ])
        return ChatResponse(
            response=f"**Available Test Cases:**\n\n{test_list}",
            intent='list',
            execute_tests=None
        )

    if intent == 'help':
        return ChatResponse(
            response="""**I can help you with:**

**Commands:**
- **"execute test 1"** - Run a specific test
- **"execute test 1, 2, 3"** - Run multiple tests
- **"execute all"** - Run all tests
- **"list tests"** - Show available tests

**Questions:**
- "What does test 1 do?"
- "Explain the login test steps"
- "What is the expected result for test 2?"
- "How many tests are there?"

Just ask me anything about your test cases!""",
            intent='help',
            execute_tests=None
        )

    if intent == 'view':
        return ChatResponse(
            response="Switching to view...",
            intent='view',
            execute_tests=None
        )

    # For questions, use LLM
    if intent == 'question':
        if not request.test_cases and not request.parsed_suite:
            return ChatResponse(
                response="I don't have any test data to answer questions about. Please upload a test file first!",
                intent='question',
                execute_tests=None
            )

        try:
            # Format context
            test_context = format_test_context(request.test_cases, request.parsed_suite)

            # Build prompt
            prompt = CHAT_SYSTEM_PROMPT.format(
                test_context=test_context,
                user_message=message
            )

            # Get LLM provider
            provider_str = request.llm_provider.lower()
            provider = LLMProvider(provider_str)

            # Get model
            model = request.model
            if not model:
                model_map = {
                    "openai": settings.OPENAI_MODEL or "gpt-4o-mini",
                    "anthropic": settings.ANTHROPIC_MODEL or "claude-3-haiku-20240307",
                    "groq": settings.GROQ_MODEL or "llama-3.1-8b-instant"
                }
                model = model_map.get(provider_str, "llama-3.1-8b-instant")

            # Create LLM wrapper and call
            llm = ChatLLM(
                provider=provider,
                model=model,
                anthropic_api_key=settings.ANTHROPIC_API_KEY,
                openai_api_key=settings.OPENAI_API_KEY,
                groq_api_key=settings.GROQ_API_KEY,
            )

            response_text = llm.call_llm(prompt)

            return ChatResponse(
                response=response_text,
                intent='question',
                execute_tests=None
            )

        except Exception as e:
            print(f"[Agent Chat] LLM Error: {e}")
            return ChatResponse(
                response=f"I encountered an error processing your question. Please try again or rephrase your question.\n\nError: {str(e)}",
                intent='error',
                execute_tests=None
            )

    # Unknown intent
    return ChatResponse(
        response=f"I'm not sure what you mean by \"{message}\". Try asking a question about your tests or use commands like \"execute test 1\" or \"help\".",
        intent='unknown',
        execute_tests=None
    )
