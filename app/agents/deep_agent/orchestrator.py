"""
Deep Agent Orchestrator - True AI Agent Orchestration

This uses an LLM to decide what actions to take, rather than following
a predefined workflow graph. The AI reasons about each step and decides
which tool to call next.

Architecture:
- LLM (Brain): Decides what to do next
- Tools: parse_tests, execute_tests, validate_results, generate_report
- State: Shared context that persists across tool calls
"""

import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime

from app.agents.base_agent import LLMProvider
from app.agents.enhanced_json_parser import EnhancedJsonParserAgent
from app.tools.enhanced_executor import execute_enhanced
from app.tools.script_generator import generate_enhanced_pytest_script
from app.core.config import settings


class OrchestratorLLM:
    """Simple LLM wrapper for orchestrator decision-making."""

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
            print(f"[OrchestratorLLM] Error calling LLM: {e}")
            raise


@dataclass
class AgentState:
    """Shared state for the orchestrator agent."""
    raw_data: List[Dict] = field(default_factory=list)
    project_name: str = "Test Project"
    base_url: Optional[str] = None

    # Results from each step
    parsed_suite: Optional[Dict] = None
    execution_results: Optional[Dict] = None
    validation_status: str = "pending"  # pending, passed, failed, needs_retry
    generated_script: Optional[str] = None
    report: Optional[Dict] = None

    # Control
    retry_count: int = 0
    max_retries: int = 2
    errors: List[str] = field(default_factory=list)
    action_history: List[str] = field(default_factory=list)

    # Config
    headless: bool = True
    timeout: int = 30000
    llm_provider: str = "groq"
    model: Optional[str] = None

    # Broadcast function for SSE
    broadcast_func: Optional[Callable] = None

    def to_context(self) -> str:
        """Convert state to context string for LLM."""
        context = f"""
CURRENT STATE:
- Project: {self.project_name}
- Base URL: {self.base_url or 'Not set'}
- Raw test cases: {len(self.raw_data)} uploaded
- Parsed suite: {'Yes' if self.parsed_suite else 'No'}
- Execution results: {'Yes' if self.execution_results else 'No'}
- Validation status: {self.validation_status}
- Retry count: {self.retry_count}/{self.max_retries}
- Errors: {', '.join(self.errors) if self.errors else 'None'}
- Actions taken: {' -> '.join(self.action_history) if self.action_history else 'None'}
"""
        if self.execution_results:
            results = self.execution_results
            context += f"""
EXECUTION RESULTS:
- Total tests: {results.get('total', 0)}
- Passed: {results.get('passed', 0)}
- Failed: {results.get('failed', 0)}
"""
        return context


ORCHESTRATOR_SYSTEM_PROMPT = """You are an intelligent Test Automation Orchestrator Agent. Your job is to orchestrate the test automation pipeline by deciding which action to take next.

AVAILABLE ACTIONS:
1. PARSE - Parse raw test cases into structured format with selectors (requires: raw_data, not yet parsed)
2. EXECUTE - Run the parsed tests in a browser (requires: parsed_suite exists)
3. VALIDATE - Check execution results and decide if retry is needed (requires: execution_results exists)
4. RETRY - Retry failed tests (requires: validation_status is 'needs_retry' and retry_count < max_retries)
5. REPORT - Generate final report and script (requires: validation complete)
6. DONE - Pipeline complete, no more actions needed

DECISION RULES:
- Always PARSE first if raw_data exists but parsed_suite is None
- After PARSE succeeds, EXECUTE the tests
- After EXECUTE completes, VALIDATE the results
- If VALIDATE shows failures that are retryable (timeouts, element not found) and retry_count < max_retries, choose RETRY
- If VALIDATE shows all passed OR failures are not retryable OR max retries reached, choose REPORT
- After REPORT, choose DONE

RETRYABLE FAILURES (should retry):
- Timeout errors
- Element not found
- Network errors
- Navigation errors

NON-RETRYABLE FAILURES (go to report):
- Assertion failures (expected value doesn't match)
- Test data errors
- Configuration errors

{context}

Based on the current state, what is the SINGLE next action to take?
Respond with ONLY the action name: PARSE, EXECUTE, VALIDATE, RETRY, REPORT, or DONE
"""


class DeepAgentOrchestrator:
    """
    True AI-powered orchestrator that uses LLM to decide actions.

    Instead of a fixed workflow graph, the LLM reasons about the current
    state and decides which tool to call next.
    """

    def __init__(
        self,
        llm_provider: str = "groq",
        model: Optional[str] = None
    ):
        self.llm_provider = llm_provider
        self.model = model or self._get_default_model(llm_provider)
        self.state = AgentState()

        # Initialize LLM agent for decision making
        provider = LLMProvider(llm_provider.lower())
        self.decision_agent = OrchestratorLLM(
            provider=provider,
            model=self.model,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
            openai_api_key=settings.OPENAI_API_KEY,
            groq_api_key=settings.GROQ_API_KEY,
        )

    def _get_default_model(self, provider: str) -> str:
        """Get default model for provider."""
        return {
            "groq": settings.GROQ_MODEL or "llama-3.1-8b-instant",
            "openai": settings.OPENAI_MODEL or "gpt-4o-mini",
            "anthropic": settings.ANTHROPIC_MODEL or "claude-3-haiku-20240307"
        }.get(provider.lower(), "llama-3.1-8b-instant")

    def _broadcast(self, message: Dict):
        """Send SSE broadcast if function is set."""
        if self.state.broadcast_func:
            self.state.broadcast_func(message)
        print(f"[Orchestrator] {message.get('type', 'info')}: {message.get('message', '')}")

    def _decide_next_action(self) -> str:
        """Use LLM to decide the next action based on current state."""
        context = self.state.to_context()
        prompt = ORCHESTRATOR_SYSTEM_PROMPT.format(context=context)

        self._broadcast({
            "type": "thoughts",
            "message": "Analyzing current state and deciding next action..."
        })

        try:
            response = self.decision_agent.call_llm(prompt)
            action = response.strip().upper()

            # Validate action
            valid_actions = ["PARSE", "EXECUTE", "VALIDATE", "RETRY", "REPORT", "DONE"]
            if action not in valid_actions:
                # Try to extract action from response
                for valid in valid_actions:
                    if valid in action:
                        action = valid
                        break
                else:
                    print(f"[Orchestrator] Invalid action '{action}', defaulting to rule-based decision")
                    action = self._fallback_decision()

            self._broadcast({
                "type": "thoughts",
                "message": f"Decision: {action}"
            })

            return action

        except Exception as e:
            print(f"[Orchestrator] LLM decision error: {e}, using fallback")
            return self._fallback_decision()

    def _fallback_decision(self) -> str:
        """Rule-based fallback if LLM fails."""
        if not self.state.parsed_suite and self.state.raw_data:
            return "PARSE"
        elif self.state.parsed_suite and not self.state.execution_results:
            return "EXECUTE"
        elif self.state.execution_results and self.state.validation_status == "pending":
            return "VALIDATE"
        elif self.state.validation_status == "needs_retry" and self.state.retry_count < self.state.max_retries:
            return "RETRY"
        elif self.state.validation_status in ["passed", "failed"] or self.state.retry_count >= self.state.max_retries:
            return "REPORT" if not self.state.report else "DONE"
        else:
            return "DONE"

    # ==================== TOOLS ====================

    def _tool_parse(self) -> bool:
        """Parse raw test cases into structured format."""
        self._broadcast({
            "type": "node_started",
            "node": "parse",
            "message": "AI is parsing test cases..."
        })

        try:
            provider = LLMProvider(self.llm_provider.lower())
            parser = EnhancedJsonParserAgent(provider=provider, model=self.model)

            self.state.parsed_suite = parser.parse_to_enhanced_structure(
                raw_data=self.state.raw_data,
                project_name=self.state.project_name,
                base_url=self.state.base_url
            )

            test_count = len(self.state.parsed_suite.get("test_cases", []))
            step_count = sum(len(tc.get("steps", [])) for tc in self.state.parsed_suite.get("test_cases", []))

            self._broadcast({
                "type": "node_completed",
                "node": "parse",
                "message": f"Parsed {test_count} test cases with {step_count} steps"
            })

            return True

        except Exception as e:
            error_msg = f"Parse error: {str(e)}"
            self.state.errors.append(error_msg)
            self._broadcast({
                "type": "node_completed",
                "node": "parse",
                "status": "error",
                "message": error_msg
            })
            return False

    def _tool_execute(self) -> bool:
        """Execute tests in browser."""
        retry_msg = f" (retry {self.state.retry_count})" if self.state.retry_count > 0 else ""

        self._broadcast({
            "type": "node_started",
            "node": "execute",
            "message": f"Executing tests in browser{retry_msg}..."
        })

        try:
            import asyncio

            # Run async execute_enhanced
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run,
                            execute_enhanced(
                                test_suite=self.state.parsed_suite,
                                headless=self.state.headless,
                                timeout=self.state.timeout
                            )
                        )
                        self.state.execution_results = future.result()
                else:
                    self.state.execution_results = loop.run_until_complete(
                        execute_enhanced(
                            test_suite=self.state.parsed_suite,
                            headless=self.state.headless,
                            timeout=self.state.timeout
                        )
                    )
            except RuntimeError:
                self.state.execution_results = asyncio.run(
                    execute_enhanced(
                        test_suite=self.state.parsed_suite,
                        headless=self.state.headless,
                        timeout=self.state.timeout
                    )
                )

            results = self.state.execution_results
            passed = results.get("passed", 0)
            total = results.get("total", 0)

            self._broadcast({
                "type": "node_completed",
                "node": "execute",
                "message": f"Execution complete: {passed}/{total} passed"
            })

            return True

        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            self.state.errors.append(error_msg)
            self._broadcast({
                "type": "node_completed",
                "node": "execute",
                "status": "error",
                "message": error_msg
            })
            return False

    def _tool_validate(self) -> str:
        """Validate results and decide if retry is needed."""
        self._broadcast({
            "type": "node_started",
            "node": "validate",
            "message": "Validating execution results..."
        })

        if not self.state.execution_results:
            self.state.validation_status = "failed"
            return "failed"

        results = self.state.execution_results
        passed = results.get("passed", 0)
        failed = results.get("failed", 0)
        total = results.get("total", 0)

        # All passed
        if failed == 0 and passed == total:
            self.state.validation_status = "passed"
            self._broadcast({
                "type": "node_completed",
                "node": "validate",
                "message": f"All {total} tests passed!"
            })
            return "passed"

        # Check if failures are retryable
        retryable_errors = ["timeout", "element not found", "not found", "navigation", "network"]
        has_retryable = False

        for result in results.get("results", []):
            error = result.get("error", "") or ""
            if any(err in error.lower() for err in retryable_errors):
                has_retryable = True
                break

        if has_retryable and self.state.retry_count < self.state.max_retries:
            self.state.validation_status = "needs_retry"
            self._broadcast({
                "type": "node_completed",
                "node": "validate",
                "message": f"Found retryable failures. Will retry ({self.state.retry_count + 1}/{self.state.max_retries})"
            })
            return "needs_retry"

        # Not retryable or max retries reached
        self.state.validation_status = "failed"
        self._broadcast({
            "type": "node_completed",
            "node": "validate",
            "message": f"Validation complete: {passed}/{total} passed, {failed} failed"
        })
        return "failed"

    def _tool_retry(self) -> bool:
        """Prepare for retry."""
        self.state.retry_count += 1
        self.state.execution_results = None
        self.state.validation_status = "pending"

        # Increase timeout for retry
        self.state.timeout = int(self.state.timeout * 1.5)

        self._broadcast({
            "type": "thoughts",
            "message": f"Preparing retry {self.state.retry_count}/{self.state.max_retries}, timeout increased to {self.state.timeout}ms"
        })

        return True

    def _tool_report(self) -> bool:
        """Generate final report."""
        self._broadcast({
            "type": "node_started",
            "node": "report",
            "message": "Generating final report..."
        })

        try:
            # Generate Playwright script
            if self.state.parsed_suite:
                script_result = generate_enhanced_pytest_script(self.state.parsed_suite)
                self.state.generated_script = script_result.get("pytest_script", {}).get("script", "")

            # Build report
            results = self.state.execution_results or {}
            self.state.report = {
                "project": self.state.project_name,
                "base_url": self.state.base_url,
                "generated_at": datetime.now().isoformat(),
                "summary": {
                    "validation_status": self.state.validation_status,
                    "total_tests": results.get("total", 0),
                    "passed": results.get("passed", 0),
                    "failed": results.get("failed", 0),
                    "retries": self.state.retry_count,
                    "pass_rate": round((results.get("passed", 0) / max(results.get("total", 1), 1)) * 100, 1)
                },
                "action_history": self.state.action_history,
                "errors": self.state.errors
            }

            self._broadcast({
                "type": "node_completed",
                "node": "report",
                "message": f"Report generated: {results.get('passed', 0)}/{results.get('total', 0)} passed"
            })

            return True

        except Exception as e:
            error_msg = f"Report error: {str(e)}"
            self.state.errors.append(error_msg)
            self._broadcast({
                "type": "node_completed",
                "node": "report",
                "status": "error",
                "message": error_msg
            })
            return False

    # ==================== MAIN RUN ====================

    def run(
        self,
        raw_data: List[Dict],
        project_name: str = "Test Project",
        base_url: Optional[str] = None,
        headless: bool = True,
        timeout: int = 30000,
        max_retries: int = 2,
        broadcast_func: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Run the orchestrator with AI-driven decision making.

        The LLM decides which action to take at each step based on
        the current state, rather than following a fixed workflow.
        """
        # Initialize state
        self.state = AgentState(
            raw_data=raw_data,
            project_name=project_name,
            base_url=base_url,
            headless=headless,
            timeout=timeout,
            max_retries=max_retries,
            llm_provider=self.llm_provider,
            model=self.model,
            broadcast_func=broadcast_func
        )

        self._broadcast({
            "type": "agent_phase",
            "phase": "starting",
            "message": "AI Orchestrator starting..."
        })

        max_iterations = 10  # Safety limit
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # AI decides next action
            action = self._decide_next_action()
            self.state.action_history.append(action)

            print(f"[Orchestrator] Iteration {iteration}: Action = {action}")

            if action == "DONE":
                break

            # Execute the chosen action
            if action == "PARSE":
                success = self._tool_parse()
                if not success:
                    # AI might decide to retry or report error
                    continue

            elif action == "EXECUTE":
                success = self._tool_execute()
                if not success:
                    continue

            elif action == "VALIDATE":
                self._tool_validate()

            elif action == "RETRY":
                self._tool_retry()

            elif action == "REPORT":
                self._tool_report()
                # After report, next iteration should be DONE

            else:
                print(f"[Orchestrator] Unknown action: {action}")
                break

        # Final broadcast
        self._broadcast({
            "type": "deep_agent_complete",
            "status": "success" if self.state.validation_status == "passed" else "completed",
            "message": f"Orchestration complete: {self.state.execution_results.get('passed', 0) if self.state.execution_results else 0}/{self.state.execution_results.get('total', 0) if self.state.execution_results else 0} passed",
            "data": {
                "status": self.state.validation_status,
                "passed": self.state.execution_results.get("passed", 0) if self.state.execution_results else 0,
                "failed": self.state.execution_results.get("failed", 0) if self.state.execution_results else 0,
                "total": self.state.execution_results.get("total", 0) if self.state.execution_results else 0,
                "retries": self.state.retry_count,
                "actions": self.state.action_history
            }
        })

        return {
            "status": "success" if self.state.validation_status == "passed" else "completed",
            "validation_status": self.state.validation_status,
            "summary": {
                "total": self.state.execution_results.get("total", 0) if self.state.execution_results else 0,
                "passed": self.state.execution_results.get("passed", 0) if self.state.execution_results else 0,
                "failed": self.state.execution_results.get("failed", 0) if self.state.execution_results else 0,
                "retries": self.state.retry_count
            },
            "execution_results": self.state.execution_results,
            "report": self.state.report,
            "generated_script": self.state.generated_script,
            "action_history": self.state.action_history,
            "errors": self.state.errors
        }


# Convenience function
def run_orchestrated_agent(
    raw_data: List[Dict],
    project_name: str = "Test Project",
    base_url: Optional[str] = None,
    llm_provider: str = "groq",
    model: Optional[str] = None,
    headless: bool = True,
    timeout: int = 30000,
    max_retries: int = 2,
    broadcast_func: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Run the AI-orchestrated deep agent.

    This uses true agent orchestration where the LLM decides
    which action to take at each step.
    """
    orchestrator = DeepAgentOrchestrator(
        llm_provider=llm_provider,
        model=model
    )

    return orchestrator.run(
        raw_data=raw_data,
        project_name=project_name,
        base_url=base_url,
        headless=headless,
        timeout=timeout,
        max_retries=max_retries,
        broadcast_func=broadcast_func
    )
