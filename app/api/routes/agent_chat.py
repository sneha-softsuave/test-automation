"""
Agent Chat API Routes

Provides conversational interface for the test automation agent.
Users can ask questions about uploaded test cases or give commands.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import re
import json

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
    execute_tests: Optional[List[str]] = None  # If intent is 'execute', which test IDs to run


# Primary prompt: instructs LLM to return structured JSON for intent detection + response
STRUCTURED_CHAT_PROMPT = """You are a Test Automation Assistant. Analyze the user's message and respond ONLY with a valid JSON object.

AVAILABLE TEST CASES:
{test_context}

USER MESSAGE: {user_message}

Return ONLY this JSON structure, no other text:
{{
  "intent": "<one of: execute, execute_all, question, list, help, view, unknown>",
  "execute_tests": <array of test ID strings exactly as they appear in the test list, or null>,
  "response": "<your helpful response text>"
}}

INTENT RULES:

- "execute": User explicitly wants to RUN / START / LAUNCH a specific test.
  The message MUST contain an action verb OR "let's/lets" + test reference.
  Action verbs: run, execute (and typos like execte/executete/exeucte), start, launch, perform,
  complete, finish, begin, kick off, trigger. Also "go" + test reference.
  Examples: "run test 1", "execute test case 2", "start test 3", "run TC_1",
  "can you run case 2", "lets complete test 2", "finish test 3", "begin test 1",
  "lets go with test 2", "kick off test 4", "lets run test case 3",
  "execte test case 1,2", "executete case 1", "go test 1 and 2"

  NOT execute (these are questions): "compare test 4 and 5", "what is test 2?",
  "explain test 3", "difference between test 1 and 2", "show me what test 4 does",
  "describe test 5", "what are the steps in test 1", "tell me about test 3"

- "execute_all": User wants to run ALL tests at once.
  Examples: "run all", "execute everything", "run all tests", "start all test cases"

- "question": User is asking a question or wants information. Use this whenever the message
  contains: what, how, why, explain, compare, difference, describe, show me, tell me, steps,
  which, does, is, are — even if test numbers are mentioned.
  Examples: "what does test 1 do?", "compare test 4 and 5", "explain the login test",
  "what are the steps in test 3?", "difference between test 1 and test 2",
  "how many tests are there?", "what is test case 4 about?", "show me test 5 steps"

- "list": User wants to see all available tests listed.
  Examples: "list tests", "show all tests", "what tests do I have?"

- "help": User needs help or asks what you can do.
  Examples: "help", "what can you do?", "show commands"

- "view": User wants to switch views.
  Examples: "view results", "show results", "view suite"

- "unknown": Does not fit any category. Ask the user to clarify.

DECISION RULE — when in doubt between "execute" and "question":
  If the message does NOT contain an explicit run/execute/start verb → use "question".
  Numbers alone do not make it "execute". "compare test 4 and 5" is a QUESTION, not execute.

RESPONSE RULES:
1. For "execute"/"execute_all": response = "I'll execute [description]. Starting now..."
2. For "question": provide a concise answer based on the test context above.
3. For "list": list available test cases from the context.
4. For "help": explain available commands and that natural language is understood.
5. For "unknown": ask the user to clarify what they need.
6. If no test data is available and user wants to execute: set intent to "question", response = "Please upload a test file first."
7. For "execute": extract ALL test IDs mentioned using the EXACT ID string from the test list (e.g. "T.C.01", "T.C.11").
   Map user shorthand to exact IDs: "test 1" -> "T.C.01", "TC_01" -> "T.C.01", "T.C.01" -> "T.C.01".
   IMPORTANT: treat each comma/space-separated number as a separate test. "1,2,11" means THREE tests: 1, 2, and 11.
   Examples:
   - "run test 1 and 3" -> execute_tests: ["T.C.01", "T.C.03"]
   - "execute 1,2,11" -> execute_tests: ["T.C.01", "T.C.02", "T.C.11"]
   - "run tests 1, 2, 12" -> execute_tests: ["T.C.01", "T.C.02", "T.C.12"]
8. Use markdown formatting (bold, lists) in response for readability.

CRITICAL: Return ONLY the JSON object. No markdown code blocks, no explanation text.
Start your response with {{ and end with }}"""


# Fallback prompt (plain-text, used only when structured LLM call fails)
CHAT_SYSTEM_PROMPT_FALLBACK = """You are a helpful Test Automation Assistant. You help users understand and work with their test cases.

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


HELP_TEXT = """**I can help you with:**

**Execute tests (any natural phrasing works):**
- "execute test 1" / "run test case 1" / "please run the first test"
- "execute tests 1, 2, 3" / "run case 1 and 3 for me"
- "execute all" / "run everything"

**Ask questions:**
- "What does test 1 do?"
- "Explain the login test"
- "How many tests are there?"

**Other commands:**
- "list tests" - Show all available tests
- "view results" - See execution results
- "view suite" - See parsed test suite"""


VALID_INTENTS = {"execute", "execute_all", "question", "list", "help", "view", "unknown"}

# Fuzzy recovery map for common LLM typos / variations
INTENT_ALIASES = {
    "run": "execute",
    "start": "execute",
    "launch": "execute",
    "run_all": "execute_all",
    "execute_all_tests": "execute_all",
    "ask": "question",
    "query": "question",
    "show": "list",
    "display": "list",
}


def _normalize_test_id(raw: str) -> str:
    """Convert shorthand like '1', '01', 'TC_1', 'T.C.1' -> 'T.C.01'."""
    # Already in correct format
    if re.match(r'^T\.C\.\d+$', raw, re.IGNORECASE):
        num = int(re.search(r'\d+', raw).group())
        return f"T.C.{num:02d}"
    # Pure number or zero-padded number
    if re.match(r'^\d+$', raw):
        return f"T.C.{int(raw):02d}"
    # TC_1, TC01, tc_01, etc.
    m = re.match(r'^tc[_]?(\d+)$', raw, re.IGNORECASE)
    if m:
        return f"T.C.{int(m.group(1)):02d}"
    return raw.upper()


def detect_intent(message: str) -> tuple[str, Optional[List[str]]]:
    """Detect user intent from message using regex (used as fallback)."""
    msg_lower = message.lower().strip()

    # Execute/Run commands — also handles common typos (execte, executete, exeucte)
    _exec = r'(?:execu?t[ei]?e?|run|start|go)'
    execute_patterns = [
        rf'({_exec}|test)\s+(all|everything)',
        rf'{_exec}\s+test\s*case\s*(\d+)',
        rf'{_exec}\s+test\s*(\d+)',
        rf'{_exec}\s+tests?\s*([\d,\s]+)',
        r'run\s+tc[_]?(\d+)',
        rf'{_exec}\s+[tT]\.?[cC]\.?\d+',
        r'[tT]\.?[cC]\.?\d+',  # bare "T.C.01" or "TC1" is almost always execute intent
    ]

    for pattern in execute_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            if 'all' in msg_lower or 'everything' in msg_lower:
                return 'execute', None  # None means all

            numbers = re.findall(r'\d+', message)
            if numbers:
                return 'execute', [_normalize_test_id(n) for n in numbers]

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


def _parse_llm_chat_response(response_text: str) -> Optional[dict]:
    """
    Parse structured JSON from LLM response.
    Handles markdown code blocks and extracts the outermost JSON object.
    Returns None if parsing fails.
    """
    if not response_text:
        return None

    text = response_text.strip()

    # Strip markdown code blocks (```json ... ``` or ``` ... ```)
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    # Find outermost JSON object by brace counting
    start = text.find('{')
    if start == -1:
        return None

    depth = 0
    end = -1
    for i, ch in enumerate(text[start:], start=start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        return None

    json_str = text[start:end + 1]

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"[AgentChat] JSON parse error: {e} | Raw: {json_str[:200]}")
        return None


def _validate_chat_json(data: dict) -> Optional[dict]:
    """
    Validate and normalize the parsed LLM JSON response.
    Applies fuzzy recovery for intent typos.
    Returns normalized dict or None if unrecoverable.
    """
    if not isinstance(data, dict):
        return None

    # Validate / recover intent
    intent = data.get("intent", "")
    if not isinstance(intent, str):
        return None

    intent = intent.lower().strip()

    if intent not in VALID_INTENTS:
        intent = INTENT_ALIASES.get(intent)
        if intent is None:
            print(f"[AgentChat] Unrecoverable intent value: {data.get('intent')}")
            return None

    # Validate execute_tests — keep as strings (IDs like "T.C.01")
    execute_tests = data.get("execute_tests")
    if execute_tests is not None:
        if not isinstance(execute_tests, list):
            execute_tests = None
        else:
            try:
                execute_tests = [str(n) for n in execute_tests if n is not None]
                if not execute_tests:
                    execute_tests = None
            except (TypeError, ValueError):
                execute_tests = None

    # Validate response text
    response = data.get("response", "")
    if not isinstance(response, str) or not response.strip():
        return None

    return {
        "intent": intent,
        "execute_tests": execute_tests,
        "response": response.strip(),
    }


def _build_execute_response(test_numbers: Optional[List[str]], test_cases: Optional[List[Dict]]) -> str:
    if not test_cases:
        return "Please upload a test file first."
    if test_numbers is None:
        return f"I'll execute all {len(test_cases)} test case(s). Starting now..."
    return f"I'll execute test case(s): {test_numbers}. Starting now..."


def _build_list_response(test_cases: Optional[List[Dict]]) -> str:
    if not test_cases:
        return "No test cases uploaded. Please upload an Excel file first."
    lines = [
        f"**{tc.get('T.C.No', 'N/A')}** - {tc.get('Test Case', 'Unnamed')}"
        for tc in test_cases
    ]
    return "**Available Test Cases:**\n\n" + "\n".join(lines)


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

    Uses a single structured LLM call for intent detection + response generation.
    Falls back to regex-based detection if the LLM call fails or returns invalid JSON.
    """
    message = request.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # ------------------------------------------------------------------ #
    # 1. Pure-local commands — no LLM needed                              #
    # ------------------------------------------------------------------ #
    msg_lower = message.lower().strip()
    if msg_lower in ('help', '?', 'commands', 'what can you do'):
        return ChatResponse(response=HELP_TEXT, intent='help', execute_tests=None)

    # ------------------------------------------------------------------ #
    # 2. Build LLM client                                                 #
    # ------------------------------------------------------------------ #
    provider_str = request.llm_provider.lower()
    try:
        provider = LLMProvider(provider_str)
    except ValueError:
        provider = LLMProvider("groq")
        provider_str = "groq"

    model = request.model
    if not model:
        model_map = {
            "openai": settings.OPENAI_MODEL,
            "anthropic": settings.ANTHROPIC_MODEL,
            "groq": settings.GROQ_MODEL,
        }
        model = model_map.get(provider_str, settings.GROQ_MODEL)

    llm = ChatLLM(
        provider=provider,
        model=model,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        openai_api_key=settings.OPENAI_API_KEY,
        groq_api_key=settings.GROQ_API_KEY,
    )

    # ------------------------------------------------------------------ #
    # 3. Format test context                                              #
    # ------------------------------------------------------------------ #
    test_context = format_test_context(
        request.test_cases or [],
        request.parsed_suite,
    )

    # ------------------------------------------------------------------ #
    # 4. PRIMARY PATH — single structured LLM call                        #
    # ------------------------------------------------------------------ #
    parsed = None
    try:
        prompt = STRUCTURED_CHAT_PROMPT.format(
            test_context=test_context,
            user_message=message,
        )
        raw_response = llm.call_llm(prompt)
        print(f"[AgentChat] Raw LLM response: {raw_response[:300]}")

        data = _parse_llm_chat_response(raw_response)
        if data is not None:
            parsed = _validate_chat_json(data)

        # Safety override: if LLM says "execute" but the message has NO explicit
        # run/execute/start verb, it's almost certainly a misclassification (common
        # with smaller models like Groq llama). Force it to "question" instead.
        # Uses word-boundary regex so "execute test case 2" matches correctly.
        if parsed and parsed.get("intent") == "execute":
            msg_lower_check = message.lower()

            # Question words — if any are present, it is a question (highest priority)
            question_words = re.compile(
                r'\b(what|how|why|explain|describe|compare|difference|tell me|which|does|is are|'
                r'show me|steps|detail|about|meaning|purpose)\b'
            )
            has_question_word = bool(question_words.search(msg_lower_check))

            # Unambiguous action verbs only (words that can ONLY mean "run this test")
            # exec\w* catches typos: execte, executete, execution, etc.
            # exeu\w* catches transpositions: exeucte, exeuct, etc.
            action_verb_pattern = re.compile(
                r'\b(run|exec\w*|exeu\w*|start|launch|perform|complete|finish|begin|kick.?off|trigger)\b'
            )
            has_action_verb = bool(action_verb_pattern.search(msg_lower_check))

            # "lets"/"let's" + test reference is always execute intent
            lets_pattern = re.compile(r"\blet'?s\b")
            has_lets = bool(lets_pattern.search(msg_lower_check))

            if has_question_word and not has_action_verb:
                # Clear question — override
                print(f"[AgentChat] Overriding LLM 'execute' → 'question' (question word, no action verb)")
                parsed["intent"] = "question"
                parsed["execute_tests"] = None
            elif not has_action_verb and not has_lets and not has_question_word:
                # No clear signal either way — override to question to be safe
                print(f"[AgentChat] Overriding LLM 'execute' → 'question' (no action verb or lets found)")
                parsed["intent"] = "question"
                parsed["execute_tests"] = None
            # else: has_action_verb OR has_lets → trust LLM execute intent

        if parsed is None:
            print("[AgentChat] Structured LLM response invalid — using fallback")

    except Exception as e:
        print(f"[AgentChat] Primary LLM call failed: {e} — using fallback")

    # ------------------------------------------------------------------ #
    # 5. FALLBACK PATH — regex intent detection + optional plain-text LLM #
    # ------------------------------------------------------------------ #
    if parsed is None:
        fallback_intent, fallback_numbers = detect_intent(message)

        if fallback_intent == 'execute':
            parsed = {
                "intent": "execute",
                "execute_tests": fallback_numbers,
                "response": _build_execute_response(fallback_numbers, request.test_cases),
            }

        elif fallback_intent == 'list':
            parsed = {
                "intent": "list",
                "execute_tests": None,
                "response": _build_list_response(request.test_cases),
            }

        elif fallback_intent == 'view':
            parsed = {
                "intent": "view",
                "execute_tests": None,
                "response": "Switching to view...",
            }

        elif fallback_intent == 'question':
            # Second LLM call with old plain-text prompt
            try:
                fallback_prompt = CHAT_SYSTEM_PROMPT_FALLBACK.format(
                    test_context=test_context,
                    user_message=message,
                )
                fallback_text = llm.call_llm(fallback_prompt)
                parsed = {
                    "intent": "question",
                    "execute_tests": None,
                    "response": fallback_text,
                }
            except Exception as e:
                print(f"[AgentChat] Fallback LLM call also failed: {e}")
                parsed = {
                    "intent": "error",
                    "execute_tests": None,
                    "response": f"I encountered an error processing your question. Please try again.\n\nError: {str(e)}",
                }

        else:
            parsed = {
                "intent": "unknown",
                "execute_tests": None,
                "response": (
                    f'I\'m not sure what you mean by "{message}". '
                    'Try asking a question about your tests or say "help" for guidance.'
                ),
            }

    # ------------------------------------------------------------------ #
    # 6. NORMALIZE: execute_all → execute with execute_tests=None         #
    # ------------------------------------------------------------------ #
    if parsed["intent"] == "execute_all":
        parsed["intent"] = "execute"
        parsed["execute_tests"] = None

    # ------------------------------------------------------------------ #
    # 7. GUARDS for execute intent                                        #
    # ------------------------------------------------------------------ #
    if parsed["intent"] == "execute":
        if not request.test_cases:
            return ChatResponse(
                response="Please upload a test file first before executing tests.",
                intent='execute',
                execute_tests=None,
            )

        test_numbers = parsed.get("execute_tests")

        # Merge: always re-extract numbers from the raw user message and union with
        # what the LLM returned. This catches cases where the LLM drops multi-digit
        # numbers (e.g. "1,2,11" → LLM returns only ["T.C.01","T.C.02"]).
        if test_numbers is not None:
            raw_nums = re.findall(r'\d+', message)
            llm_raw_nums = set()
            for t in test_numbers:
                d = re.search(r'\d+', str(t))
                if d:
                    llm_raw_nums.add(int(d.group()))
            merged = list(test_numbers)  # start with LLM result
            for rn in raw_nums:
                if int(rn) not in llm_raw_nums:
                    merged.append(_normalize_test_id(rn))
            if len(merged) > len(test_numbers):
                print(f"[AgentChat] Merged missing test IDs from user message: {test_numbers} -> {merged}")
                test_numbers = merged

        if test_numbers is None:
            # Execute all
            return ChatResponse(
                response=_build_execute_response(None, request.test_cases),
                intent='execute',
                execute_tests=None,
            )
        else:
            # Validate that requested test IDs exist
            available = [str(tc.get('T.C.No', '')) for tc in request.test_cases]
            # Try direct match first, then normalize, then strip to plain integer
            valid_tests = []
            for n in test_numbers:
                if n in available:
                    valid_tests.append(n)
                else:
                    normalized = _normalize_test_id(n)
                    if normalized in available:
                        valid_tests.append(normalized)
                    else:
                        # Last resort: extract digits and match as plain number
                        # Handles LLM returning "TC_001" when available IDs are "1","2","3"
                        digits = re.search(r'\d+', str(n))
                        if digits:
                            plain = str(int(digits.group()))
                            if plain in available:
                                valid_tests.append(plain)

            if not valid_tests:
                return ChatResponse(
                    response=f"Test ID(s) {test_numbers} not found. Available: {available}",
                    intent='error',
                    execute_tests=None,
                )

            return ChatResponse(
                response=f"I'll execute test case(s): {valid_tests}. Starting now...",
                intent='execute',
                execute_tests=valid_tests,
            )

    # ------------------------------------------------------------------ #
    # 8. Return all other intents directly                                 #
    # ------------------------------------------------------------------ #
    return ChatResponse(
        response=parsed["response"],
        intent=parsed["intent"],
        execute_tests=parsed.get("execute_tests"),
    )
