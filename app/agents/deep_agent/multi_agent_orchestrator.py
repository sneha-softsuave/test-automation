"""
Multi-Agent Orchestrator - Supervisor Pattern

The Deep Agent supervises specialized sub-agents:
- ParserAgent: Parses test cases
- ExecutorAgent: Runs tests in browser
- ValidatorAgent: Analyzes results, decides retry
- ReporterAgent: Generates reports

The supervisor LLM decides which sub-agent to delegate to and
coordinates the overall workflow based on sub-agent outputs.
"""

import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime

from app.agents.base_agent import LLMProvider
from app.core.config import settings

from .sub_agents import (
    ParserAgent,
    ExecutorAgent,
    ValidatorAgent,
    ReporterAgent
)


class SupervisorLLM:
    """Simple LLM wrapper for supervisor decision-making."""

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
        elif provider == LLMProvider.WAYMORE:
            import openai
            self.client = openai.OpenAI(
                api_key=settings.WAYMORE_API_KEY,
                base_url=settings.WAYMORE_BASE_URL
            )

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

            elif self.provider in (LLMProvider.OPENAI, LLMProvider.GROQ, LLMProvider.WAYMORE):
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.choices[0].message.content.strip()

        except Exception as e:
            print(f"[SupervisorLLM] Error calling LLM: {e}")
            raise


@dataclass
class MultiAgentState:
    """Shared state across all agents."""
    # Input
    raw_data: List[Dict] = field(default_factory=list)
    project_name: str = "Test Project"
    base_url: Optional[str] = None

    # Results from sub-agents
    parsed_suite: Optional[Dict] = None
    parse_stats: Optional[Dict] = None
    execution_results: Optional[Dict] = None
    validation_result: Optional[Dict] = None
    report_data: Optional[Dict] = None
    generated_script: Optional[str] = None

    # Control
    validation_status: str = "pending"
    retry_count: int = 0
    max_retries: int = 2
    current_phase: str = "init"

    # Sequential test processing - process one test at a time
    current_test_index: int = 0  # Which test case we're currently processing
    all_test_results: List[Dict] = field(default_factory=list)  # Accumulated results from all tests
    current_test_retry_count: int = 0  # Retry count for current test only

    # Retry tracking - store failed test IDs and passed results
    failed_test_ids: List[str] = field(default_factory=list)
    passed_results: List[Dict] = field(default_factory=list)  # Store results of passed tests

    # Config
    headless: bool = True
    keep_browser_open: bool = True
    timeout: int = 30000
    llm_provider: str = "groq"
    model: Optional[str] = None

    # Tracking
    errors: List[str] = field(default_factory=list)
    action_history: List[Dict] = field(default_factory=list)
    sub_agent_logs: List[Dict] = field(default_factory=list)

    # SSE
    broadcast_func: Optional[Callable] = None

    # Auth state carry-forward (cookies + localStorage) across test runs
    shared_storage_state: Optional[Dict] = None


SUPERVISOR_PROMPT = """You are the Deep Agent Supervisor, coordinating a team of specialized sub-agents for test automation.

YOUR TEAM:
1. ParserAgent - Parses raw test cases into structured format
2. ExecutorAgent - Runs tests in a real browser using Playwright
3. ValidatorAgent - Analyzes results, categorizes failures, decides retries
4. ReporterAgent - Generates reports and Playwright scripts

CURRENT STATE:
{state_summary}

WORKFLOW RULES:
1. START: Always delegate to ParserAgent first to parse raw test cases
2. After parsing: Delegate to ExecutorAgent to run tests
3. After execution: Delegate to ValidatorAgent to analyze results
4. If ValidatorAgent says "needs_retry" and retry_count < max_retries: Go back to ExecutorAgent
5. When validated (passed or failed with no retry): Delegate to ReporterAgent
6. After report: DONE

RECENT ACTIONS:
{recent_actions}

Based on the current state and workflow rules, decide the next action.
Respond in JSON format:
{{
    "thinking": "Your reasoning about what to do next",
    "delegate_to": "ParserAgent|ExecutorAgent|ValidatorAgent|ReporterAgent|DONE",
    "reason": "Why this sub-agent should handle the next step"
}}
"""


class MultiAgentOrchestrator:
    """
    Deep Agent Supervisor that coordinates specialized sub-agents.

    Uses LLM to decide which sub-agent to delegate tasks to,
    creating a true multi-agent system.
    """

    def __init__(
        self,
        llm_provider: str = "groq",
        model: Optional[str] = None
    ):
        self.llm_provider = llm_provider
        self.model = model or self._get_default_model(llm_provider)
        self.state = MultiAgentState()

        # Initialize supervisor LLM
        provider = LLMProvider(llm_provider.lower())
        self.supervisor_llm = SupervisorLLM(
            provider=provider,
            model=self.model,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
            openai_api_key=settings.OPENAI_API_KEY,
            groq_api_key=settings.GROQ_API_KEY,
        )

        # Sub-agents (will be initialized with broadcast_func during run)
        self.parser_agent: Optional[ParserAgent] = None
        self.executor_agent: Optional[ExecutorAgent] = None
        self.validator_agent: Optional[ValidatorAgent] = None
        self.reporter_agent: Optional[ReporterAgent] = None

    def _get_default_model(self, provider: str) -> str:
        """Get default model for provider — all models come from settings (config.py / .env)."""
        return {
            "groq": settings.GROQ_MODEL,
            "openai": settings.OPENAI_MODEL,
            "anthropic": settings.ANTHROPIC_MODEL,
        }.get(provider.lower(), settings.GROQ_MODEL)

    def _init_sub_agents(self, broadcast_func: Optional[Callable] = None):
        """Initialize all sub-agents with shared config."""
        self.parser_agent = ParserAgent(
            llm_provider=self.llm_provider,
            model=self.model,
            broadcast_func=broadcast_func
        )
        self.executor_agent = ExecutorAgent(
            llm_provider=self.llm_provider,
            model=self.model,
            broadcast_func=broadcast_func
        )
        self.validator_agent = ValidatorAgent(
            llm_provider=self.llm_provider,
            model=self.model,
            broadcast_func=broadcast_func
        )
        self.reporter_agent = ReporterAgent(
            llm_provider=self.llm_provider,
            model=self.model,
            broadcast_func=broadcast_func
        )

    def _broadcast(self, message: Dict):
        """Send SSE broadcast."""
        if self.state.broadcast_func:
            message["agent"] = "Supervisor"
            self.state.broadcast_func(message)
        print(f"[Supervisor] {message.get('type', 'info')}: {message.get('message', '')}")

    def _get_state_summary(self) -> str:
        """Generate state summary for supervisor LLM."""
        results = self.state.execution_results or {}
        return f"""
- Project: {self.state.project_name}
- Raw test cases: {len(self.state.raw_data)} loaded
- Parsed: {'Yes - ' + str(len(self.state.parsed_suite.get('test_cases', []))) + ' tests' if self.state.parsed_suite else 'No'}
- Executed: {'Yes - ' + str(results.get('passed', 0)) + '/' + str(results.get('total', 0)) + ' passed' if self.state.execution_results else 'No'}
- Validation status: {self.state.validation_status}
- Retry count: {self.state.retry_count}/{self.state.max_retries}
- Report generated: {'Yes' if self.state.report_data else 'No'}
- Errors: {len(self.state.errors)}
"""

    def _get_recent_actions(self) -> str:
        """Get recent action history for context."""
        if not self.state.action_history:
            return "No actions yet"

        recent = self.state.action_history[-5:]  # Last 5 actions
        return "\n".join([
            f"- {a['agent']}: {a['action']} -> {a.get('result', 'completed')}"
            for a in recent
        ])

    def _decide_next_agent(self) -> Dict[str, str]:
        """Use supervisor LLM to decide which sub-agent to delegate to."""
        # Fast-path rule overrides: avoid unnecessary LLM calls when state is unambiguous
        if self.state.parsed_suite and not self.state.execution_results:
            parsed_count = len(self.state.parsed_suite.get("test_cases", []))
            print(f"[Supervisor] Fast-path: parsed ({parsed_count} tests), not yet executed → ExecutorAgent")
            return {"delegate_to": "ExecutorAgent", "reason": "Tests parsed and ready to execute"}

        prompt = SUPERVISOR_PROMPT.format(
            state_summary=self._get_state_summary(),
            recent_actions=self._get_recent_actions()
        )

        self._broadcast({
            "type": "thoughts",
            "message": "Supervisor analyzing state and deciding next delegation..."
        })

        try:
            response = self.supervisor_llm.call_llm(prompt)

            # Parse JSON response
            # Try to extract JSON from response
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_str = response[json_start:json_end]
                decision = json.loads(json_str)
            else:
                raise ValueError("No JSON found in response")

            self._broadcast({
                "type": "thoughts",
                "message": f"Supervisor decision: Delegate to {decision.get('delegate_to')} - {decision.get('reason', '')}"
            })

            return decision

        except Exception as e:
            print(f"[Supervisor] Decision error: {e}, using fallback logic")
            return self._fallback_decision()

    def _fallback_decision(self) -> Dict[str, str]:
        """Rule-based fallback if LLM decision fails."""
        # STRICT RULE: If report is generated, we're DONE - no more execution
        if self.state.report_data:
            return {
                "thinking": "Report already generated, workflow complete",
                "delegate_to": "DONE",
                "reason": "Workflow complete - report has been generated"
            }

        if not self.state.parsed_suite:
            return {
                "thinking": "No parsed suite, need to parse first",
                "delegate_to": "ParserAgent",
                "reason": "Must parse raw test cases before execution"
            }
        elif not self.state.execution_results:
            return {
                "thinking": "Parsed but not executed, run tests",
                "delegate_to": "ExecutorAgent",
                "reason": "Tests are parsed and ready to execute"
            }
        elif self.state.validation_status == "pending":
            return {
                "thinking": "Results exist but not validated",
                "delegate_to": "ValidatorAgent",
                "reason": "Need to analyze execution results"
            }
        elif self.state.validation_status == "needs_retry" and self.state.retry_count < self.state.max_retries and len(self.state.failed_test_ids) > 0:
            failed_count = len(self.state.failed_test_ids)
            return {
                "thinking": f"Retry needed for {failed_count} failed test(s), attempts remaining",
                "delegate_to": "ExecutorAgent",
                "reason": f"Retrying {failed_count} failed test(s) (attempt {self.state.retry_count}/{self.state.max_retries})"
            }
        elif self.state.validation_status in ["passed", "failed"]:
            # Validation is complete (passed or failed with no more retries)
            return {
                "thinking": "Validation complete, generate report",
                "delegate_to": "ReporterAgent",
                "reason": "Generate final report and script"
            }
        else:
            return {
                "thinking": "All phases complete",
                "delegate_to": "DONE",
                "reason": "Workflow complete"
            }

    def _delegate_to_parser(self) -> Dict[str, Any]:
        """Delegate parsing task to ParserAgent."""
        self.state.current_phase = "parsing"

        self._broadcast({
            "type": "delegation",
            "message": "Supervisor delegating to ParserAgent...",
            "sub_agent": "ParserAgent"
        })

        result = self.parser_agent.execute({
            "raw_data": self.state.raw_data,
            "project_name": self.state.project_name,
            "base_url": self.state.base_url
        })

        # Record action
        self.state.action_history.append({
            "agent": "ParserAgent",
            "action": "parse",
            "result": "success" if result["success"] else "failed",
            "timestamp": datetime.now().isoformat()
        })

        if result["success"]:
            self.state.parsed_suite = result["parsed_suite"]
            self.state.parse_stats = result["statistics"]
        else:
            self.state.errors.append(result.get("error", "Parse failed"))

        return result

    def _delegate_to_executor(self) -> Dict[str, Any]:
        """Delegate execution task to ExecutorAgent."""
        is_retry = self.state.validation_status == "needs_retry" and len(self.state.failed_test_ids) > 0

        # Debug logging
        print(f"[Supervisor] _delegate_to_executor called:")
        print(f"  - validation_status: {self.state.validation_status}")
        print(f"  - failed_test_ids: {self.state.failed_test_ids}")
        print(f"  - retry_count: {self.state.retry_count}")
        print(f"  - is_retry: {is_retry}")

        self.state.current_phase = "executing" if not is_retry else f"retrying_{self.state.retry_count}"

        # Prepare test suite - filter to only failed tests on retry
        test_suite_to_run = self.state.parsed_suite

        if is_retry and self.state.failed_test_ids:
            # Filter to only include failed tests
            original_test_cases = self.state.parsed_suite.get("test_cases", [])

            # Debug: print all test case IDs
            all_test_ids = [tc.get("id") for tc in original_test_cases]
            print(f"[Supervisor] All test case IDs in parsed_suite: {all_test_ids}")
            print(f"[Supervisor] Failed test IDs to retry: {self.state.failed_test_ids}")

            # Try exact match first
            failed_test_cases = [
                tc for tc in original_test_cases
                if tc.get("id") in self.state.failed_test_ids
            ]

            # If no exact match, try flexible matching (case-insensitive, partial match)
            if not failed_test_cases and self.state.failed_test_ids:
                print(f"[Supervisor] No exact ID match, trying flexible matching...")
                failed_ids_lower = [fid.lower() for fid in self.state.failed_test_ids]

                for tc in original_test_cases:
                    tc_id = tc.get("id", "")
                    # Try case-insensitive match
                    if tc_id.lower() in failed_ids_lower:
                        failed_test_cases.append(tc)
                        continue
                    # Try partial match (e.g., "TC_001" matches "TC_1" or "TC_01")
                    for failed_id in self.state.failed_test_ids:
                        # Extract numbers from both IDs and compare
                        tc_nums = ''.join(filter(str.isdigit, tc_id))
                        failed_nums = ''.join(filter(str.isdigit, failed_id))
                        if tc_nums and failed_nums and tc_nums == failed_nums:
                            failed_test_cases.append(tc)
                            print(f"[Supervisor] Matched {tc_id} with {failed_id} via number extraction")
                            break

            print(f"[Supervisor] Filtered to {len(failed_test_cases)} test cases for retry")

            if failed_test_cases:
                test_suite_to_run = {
                    **self.state.parsed_suite,
                    "test_cases": failed_test_cases
                }

                self._broadcast({
                    "type": "delegation",
                    "message": f"Supervisor delegating RETRY {self.state.retry_count} to ExecutorAgent - "
                               f"Re-running {len(failed_test_cases)} failed test(s): {self.state.failed_test_ids}",
                    "sub_agent": "ExecutorAgent",
                    "retry_tests": self.state.failed_test_ids
                })

                # Increase timeout for retry
                self.state.timeout = int(self.state.timeout * 1.5)
            else:
                # No matching test cases found - this shouldn't happen
                print(f"[Supervisor] WARNING: No test cases matched failed_test_ids!")
                self._broadcast({
                    "type": "delegation",
                    "message": "Supervisor delegating to ExecutorAgent (no matching failed tests found)...",
                    "sub_agent": "ExecutorAgent"
                })
        else:
            # First run - execute all tests
            self._broadcast({
                "type": "delegation",
                "message": f"Supervisor delegating to ExecutorAgent - Running {len(test_suite_to_run.get('test_cases', []))} test(s)...",
                "sub_agent": "ExecutorAgent"
            })

        print(f"[Supervisor] Final test_suite_to_run has {len(test_suite_to_run.get('test_cases', []))} test cases")

        result = self.executor_agent.execute({
            "parsed_suite": test_suite_to_run,
            "headless": self.state.headless,
            "keep_browser_open": self.state.keep_browser_open,
            "timeout": self.state.timeout,
            "base_url": self.state.base_url,
            "stop_event": getattr(self, '_stop_event', None),
            "initial_storage_state": self.state.shared_storage_state,
        })

        # Record action
        action_type = f"execute_retry_{self.state.retry_count}" if is_retry else "execute"
        self.state.action_history.append({
            "agent": "ExecutorAgent",
            "action": action_type,
            "result": "success" if result["success"] else "failed",
            "timestamp": datetime.now().isoformat()
        })

        if result["success"]:
            new_execution_results = result.get("execution_results") or {}

            # Carry authentication state forward for next execution (e.g., retry with fresh login)
            next_state = result.get("final_storage_state")
            if next_state is not None:
                self.state.shared_storage_state = next_state
                print(f"[Supervisor] Auth state stored ({len(next_state.get('cookies', []))} cookies)")

            if is_retry and self.state.passed_results:
                # Merge retry results with previously passed results
                new_results = new_execution_results.get("results", []) if isinstance(new_execution_results, dict) else []
                merged_results = self._merge_execution_results(
                    self.state.passed_results,
                    new_results
                )

                # Update execution_results with merged data
                parsed_suite = self.state.parsed_suite or {}
                total_tests = len(parsed_suite.get("test_cases", [])) if isinstance(parsed_suite, dict) else 0
                passed = sum(1 for r in merged_results if r.get("status") == "PASSED")
                failed = total_tests - passed

                self.state.execution_results = {
                    "project": new_execution_results.get("project", self.state.project_name),
                    "base_url": new_execution_results.get("base_url", self.state.base_url or ""),
                    "total": total_tests,
                    "passed": passed,
                    "failed": failed,
                    "results": merged_results
                }

                self._broadcast({
                    "type": "thoughts",
                    "message": f"Merged retry results: {passed}/{total_tests} passed (previously passed: {len(self.state.passed_results)})"
                })
            else:
                self.state.execution_results = new_execution_results

            self.state.validation_status = "pending"  # Reset for re-validation
        else:
            self.state.errors.append(result.get("error", "Execution failed"))

        return result

    def _merge_execution_results(self, passed_results: List[Dict], retry_results: List[Dict]) -> List[Dict]:
        """Merge passed results from previous run with retry results."""
        merged = []

        # Add all previously passed results
        passed_test_ids = set()
        for result in passed_results:
            merged.append(result)
            passed_test_ids.add(result.get("test_id"))

        # Add retry results (these are for previously failed tests)
        for result in retry_results:
            test_id = result.get("test_id")
            if test_id not in passed_test_ids:
                merged.append(result)

        return merged

    def _delegate_to_validator(self) -> Dict[str, Any]:
        """Delegate validation task to ValidatorAgent."""
        self.state.current_phase = "validating"

        self._broadcast({
            "type": "delegation",
            "message": "Supervisor delegating to ValidatorAgent...",
            "sub_agent": "ValidatorAgent"
        })

        result = self.validator_agent.execute({
            "execution_results": self.state.execution_results,
            "retry_count": self.state.retry_count,
            "max_retries": self.state.max_retries
        })

        # Record action
        self.state.action_history.append({
            "agent": "ValidatorAgent",
            "action": "validate",
            "result": result.get("validation_status", "unknown"),
            "timestamp": datetime.now().isoformat()
        })

        if result["success"]:
            self.state.validation_result = result
            self.state.validation_status = result["validation_status"]

            print(f"[Supervisor] Validator result:")
            print(f"  - validation_status: {result['validation_status']}")
            print(f"  - retry_tests from validator: {result.get('retry_tests')}")
            print(f"  - should_retry: {result.get('should_retry')}")

            # If needs retry, store failed test IDs and passed results
            if result["validation_status"] == "needs_retry":
                # Get failed test IDs from validator
                retry_tests = result.get("retry_tests", [])
                print(f"[Supervisor] needs_retry detected, retry_tests: {retry_tests}")

                if retry_tests:
                    self.state.failed_test_ids = retry_tests

                    # Store passed results for later merging
                    execution_results = self.state.execution_results or {}
                    all_results = execution_results.get("results", [])

                    # Debug: show all test results
                    for r in all_results:
                        print(f"[Supervisor] Test result: id={r.get('test_id')}, status={r.get('status')}")

                    self.state.passed_results = [
                        r for r in all_results
                        if r.get("status") == "PASSED"
                    ]

                    print(f"[Supervisor] Stored {len(self.state.passed_results)} passed results")
                    print(f"[Supervisor] Set failed_test_ids to: {self.state.failed_test_ids}")

                    self._broadcast({
                        "type": "thoughts",
                        "message": f"Will retry {len(retry_tests)} failed test(s): {retry_tests}. "
                                   f"Keeping {len(self.state.passed_results)} passed test(s)."
                    })

                    # Increment retry count BEFORE the retry execution
                    self.state.retry_count += 1
                    print(f"[Supervisor] Incremented retry_count to: {self.state.retry_count}")
                else:
                    print(f"[Supervisor] WARNING: needs_retry but no retry_tests provided!")
            else:
                # Reset retry tracking on success or final failure
                self.state.failed_test_ids = []
                self.state.passed_results = []
                print(f"[Supervisor] Reset failed_test_ids and passed_results")
        else:
            self.state.errors.append(result.get("error", "Validation failed"))
            self.state.validation_status = "failed"

        return result

    def _delegate_to_reporter(self) -> Dict[str, Any]:
        """Delegate reporting task to ReporterAgent."""
        self.state.current_phase = "reporting"

        self._broadcast({
            "type": "delegation",
            "message": "Supervisor delegating to ReporterAgent...",
            "sub_agent": "ReporterAgent"
        })

        result = self.reporter_agent.execute({
            "parsed_suite": self.state.parsed_suite,
            "execution_results": self.state.execution_results,
            "validation_analysis": self.state.validation_result,
            "include_script": True
        })

        # Record action
        self.state.action_history.append({
            "agent": "ReporterAgent",
            "action": "report",
            "result": "success" if result["success"] else "failed",
            "timestamp": datetime.now().isoformat()
        })

        if result["success"]:
            self.state.report_data = result["report"]
            self.state.generated_script = result.get("generated_script")
        else:
            self.state.errors.append(result.get("error", "Report generation failed"))

        return result

    def run_sequential(
        self,
        raw_data: List[Dict],
        project_name: str = "Test Project",
        base_url: Optional[str] = None,
        headless: bool = True,
        keep_browser_open: bool = True,
        timeout: int = 30000,
        max_retries: int = 2,
        broadcast_func: Optional[Callable] = None,
        stop_event=None,
    ) -> Dict[str, Any]:
        """
        ALTERNATIVE: Run with TRUE SEQUENTIAL processing (parse one, execute one).
        Use run() for LLM-driven supervisor flow.

        Flow: [For each test: Parse → Execute → Retry if needed] → Report

        This ensures:
        - Each test is PARSED and EXECUTED one at a time
        - Smaller LLM context = more accurate parsing (no hallucination)
        - Passed tests are never re-run
        - Only failed tests are retried
        """
        # Initialize state
        self.state = MultiAgentState(
            raw_data=raw_data,
            project_name=project_name,
            base_url=base_url,
            headless=headless,
            keep_browser_open=keep_browser_open,
            timeout=timeout,
            max_retries=max_retries,
            llm_provider=self.llm_provider,
            model=self.model,
            broadcast_func=broadcast_func
        )
        self._stop_event = stop_event  # Allow sub-agents to check for stop signal

        # Initialize sub-agents
        self._init_sub_agents(broadcast_func)

        total_tests = len(raw_data)

        self._broadcast({
            "type": "agent_phase",
            "phase": "starting",
            "message": f"Deep Agent Supervisor starting TRUE SEQUENTIAL processing for {total_tests} test cases..."
        })

        print(f"[Supervisor] Starting TRUE SEQUENTIAL processing: Parse One → Execute One → Next")
        print(f"[Supervisor] Total raw test cases: {total_tests}")

        # Store all parsed test cases for the final report
        all_parsed_test_cases = []

        # Auth state (cookies + localStorage) carried forward across tests
        shared_storage_state = None

        # PHASE 1: Parse ALL test cases first
        print(f"[Supervisor] Phase 1: Parsing all {total_tests} test cases...")
        for test_index, raw_test_case in enumerate(raw_data):
            if stop_event and stop_event.is_set():
                print(f"[Supervisor] Stop requested during parsing — aborting")
                self._broadcast({"type": "execution_stopped", "message": "Test execution stopped by user"})
                return {"status": "stopped", "errors": ["Stopped by user"], "generated_script": None, "report_data": None}

            test_num = test_index + 1
            raw_test_id = raw_test_case.get("T.C.No", f"TC_{test_num:03d}")
            raw_test_name = raw_test_case.get("Test Case", "Unknown Test")

            self._broadcast({
                "type": "agent_phase",
                "phase": "parsing",
                "message": f"Parsing test {test_num}/{total_tests}: {raw_test_name}"
            })

            print(f"[Supervisor] Parsing test {test_num}/{total_tests}: {raw_test_id}...")
            parse_result = self._parse_single_test(
                raw_test_case=raw_test_case,
                test_index=test_index,
                project_name=project_name,
                base_url=base_url
            )

            if not parse_result["success"]:
                print(f"[Supervisor] Parsing failed for {raw_test_id}")
                self.state.all_test_results.append({
                    "test_id": raw_test_id,
                    "test_name": raw_test_name,
                    "status": "FAILED",
                    "error": f"Parsing failed: {parse_result.get('error', 'Unknown error')}",
                    "steps_results": []
                })
                # Append a placeholder so indices stay aligned
                all_parsed_test_cases.append(None)
                continue

            parsed_test_case = parse_result["parsed_test_case"]
            all_parsed_test_cases.append(parsed_test_case)

            self._broadcast({
                "type": "thoughts",
                "message": f"Parsed {parsed_test_case.get('id', raw_test_id)}: {len(parsed_test_case.get('steps', []))} steps"
            })

        # PHASE 2: Execute — strategy depends on keep_browser_open
        if stop_event and stop_event.is_set():
            print(f"[Supervisor] Stop requested before execution — aborting")
            self._broadcast({"type": "execution_stopped", "message": "Test execution stopped by user"})
            return {"status": "stopped", "errors": ["Stopped by user"], "generated_script": None, "report_data": None}

        valid_parsed = [tc for tc in all_parsed_test_cases if tc is not None]

        if keep_browser_open and len(valid_parsed) > 0:
            # Single execute_enhanced call with all tests → one browser stays open for all
            print(f"[Supervisor] keep_browser_open=True: running all {len(valid_parsed)} tests in one browser session")
            self._broadcast({
                "type": "agent_phase",
                "phase": "execute",
                "message": f"Executing all {len(valid_parsed)} tests in a single browser session..."
            })

            base_suite = self.state.parsed_suite or {}
            full_suite = {
                "project": base_suite.get("project", project_name),
                "base_url": base_suite.get("base_url", base_url or ""),
                "common_selectors": base_suite.get("common_selectors", {}),
                "test_data": base_suite.get("test_data", {}),
                "test_cases": valid_parsed
            }

            exec_result = self.executor_agent.execute({
                "parsed_suite": full_suite,
                "headless": headless,
                "keep_browser_open": True,
                "timeout": timeout,
                "base_url": base_url,
                "initial_storage_state": shared_storage_state,
                "stop_event": stop_event,
            })

            if exec_result["success"]:
                execution_results = exec_result.get("execution_results") or {}
                batch_results = execution_results.get("results", [])
                for test_result in batch_results:
                    self.state.all_test_results.append(test_result)
                    status = "PASSED" if test_result.get("status") == "PASSED" else "FAILED"
                    tid = test_result.get("test_id", "?")
                    print(f"[Supervisor] {tid}: {status}")
                    self._broadcast({
                        "type": "thoughts",
                        "message": f"{tid}: {status}"
                    })
                # Carry forward final auth state
                final_storage = exec_result.get("final_storage_state") or execution_results.get("final_storage_state")
                if final_storage:
                    shared_storage_state = final_storage
            else:
                print(f"[Supervisor] Batch execution error: {exec_result.get('error')}")
                for tc in valid_parsed:
                    self.state.all_test_results.append({
                        "test_id": tc.get("id", "?"),
                        "test_name": tc.get("name", "Unknown"),
                        "status": "FAILED",
                        "error": exec_result.get("error", "Execution failed"),
                        "steps_results": []
                    })

        else:
            # Original sequential behaviour: one browser per test (or keep_browser_open=False)
            print(f"[Supervisor] keep_browser_open=False: running tests sequentially (fresh browser per test)")
            for test_index, raw_test_case in enumerate(raw_data):
                test_num = test_index + 1
                raw_test_id = raw_test_case.get("T.C.No", f"TC_{test_num:03d}")
                raw_test_name = raw_test_case.get("Test Case", "Unknown Test")
                parsed_test_case = all_parsed_test_cases[test_index] if test_index < len(all_parsed_test_cases) else None

                if parsed_test_case is None:
                    # Already recorded as failed during parse phase
                    continue

                test_id = parsed_test_case.get("id", raw_test_id)
                test_name = parsed_test_case.get("name", raw_test_name)

                self.state.current_test_index = test_index
                self.state.current_test_retry_count = 0

                print(f"\n[Supervisor] ========== Test {test_num}/{total_tests}: {test_id} - {test_name} ==========")

                self._broadcast({
                    "type": "agent_phase",
                    "phase": "execute",
                    "message": f"Executing test {test_num}/{total_tests}: {test_name}"
                })

                test_result = self._execute_single_test_with_retry(
                    test_case=parsed_test_case,
                    test_index=test_index,
                    total_tests=total_tests,
                    initial_storage_state=shared_storage_state
                )

                self.state.all_test_results.append(test_result)

                next_state = test_result.get("final_storage_state")
                if next_state is not None:
                    shared_storage_state = next_state
                    print(f"[Supervisor] Auth state carried forward ({len(next_state.get('cookies', []))} cookies)")

                status = "PASSED" if test_result.get("status") == "PASSED" else "FAILED"
                print(f"[Supervisor] Test {test_id} final status: {status}")

                self._broadcast({
                    "type": "thoughts",
                    "message": f"Test {test_num}/{total_tests} ({test_id}): {status}"
                })

        # STEP 3: Build final execution results from all test results
        print(f"\n[Supervisor] ========== Building Final Results ==========")
        passed = sum(1 for r in self.state.all_test_results if r.get("status") == "PASSED")
        failed = total_tests - passed

        # Build parsed_suite for reporter (contains all parsed test cases)
        self.state.parsed_suite = {
            "project": project_name,
            "base_url": base_url or self._extract_base_url_from_raw(raw_data),
            "test_cases": all_parsed_test_cases,
            "common_selectors": {},
            "test_data": {}
        }

        self.state.execution_results = {
            "project": self.state.project_name,
            "base_url": self.state.base_url or "",
            "total": total_tests,
            "passed": passed,
            "failed": failed,
            "results": self.state.all_test_results,
            "executed_at": datetime.now().isoformat()
        }

        self.state.validation_status = "passed" if failed == 0 else "failed"

        self._broadcast({
            "type": "thoughts",
            "message": f"All tests complete: {passed}/{total_tests} passed"
        })

        # STEP 4: Generate report
        print(f"[Supervisor] Step 4: Generating report...")
        self._delegate_to_reporter()

        # Build final result
        final_result = self._build_final_result()

        self._broadcast({
            "type": "deep_agent_complete",
            "status": "success" if self.state.validation_status == "passed" else "completed",
            "message": f"Sequential execution complete: {passed}/{total_tests} passed",
            "data": final_result["summary"],
            "execution_results": final_result["execution_results"],
            "parsed_suite": final_result["parsed_suite"],
            "orchestration": final_result["orchestration"],
        })

        return final_result

    def _parse_single_test(
        self,
        raw_test_case: Dict,
        test_index: int,
        project_name: str,
        base_url: Optional[str]
    ) -> Dict[str, Any]:
        """
        Parse a single test case using the ParserAgent WITH RETRY LOGIC.

        This keeps the LLM context small = more accurate parsing.
        Retries up to max_retries times if parsing fails.
        """
        max_parse_retries = self.state.max_retries
        last_error = ""

        for attempt in range(max_parse_retries + 1):
            attempt_label = "Initial" if attempt == 0 else f"Retry {attempt}"

            try:
                self._broadcast({
                    "type": "delegation",
                    "message": f"{attempt_label} parsing of test case {test_index + 1}...",
                    "sub_agent": "ParserAgent"
                })

                print(f"[Supervisor] {attempt_label} parse attempt for test {test_index + 1}...")

                # Call parser with just this one test case
                result = self.parser_agent.execute({
                    "raw_data": [raw_test_case],  # Single test case in a list
                    "project_name": project_name,
                    "base_url": base_url
                })

                if not result["success"]:
                    last_error = result.get("error", "Parsing failed")
                    print(f"[Supervisor] Parse failed: {last_error[:100]}...")

                    if attempt < max_parse_retries:
                        self._broadcast({
                            "type": "thoughts",
                            "message": f"Parsing failed, retrying ({attempt + 1}/{max_parse_retries})..."
                        })
                        continue
                    else:
                        return {
                            "success": False,
                            "error": last_error
                        }

                # Handle None parsed_suite
                parsed_suite = result.get("parsed_suite")
                if parsed_suite is None:
                    last_error = "Parser returned empty result"
                    print(f"[Supervisor] {last_error}")

                    if attempt < max_parse_retries:
                        self._broadcast({
                            "type": "thoughts",
                            "message": f"Empty parse result, retrying ({attempt + 1}/{max_parse_retries})..."
                        })
                        continue
                    else:
                        return {
                            "success": False,
                            "error": last_error
                        }

                test_cases = parsed_suite.get("test_cases", []) if isinstance(parsed_suite, dict) else []

                if not test_cases:
                    last_error = "No test cases extracted from parsing"
                    print(f"[Supervisor] {last_error}")

                    if attempt < max_parse_retries:
                        self._broadcast({
                            "type": "thoughts",
                            "message": f"No test cases extracted, retrying ({attempt + 1}/{max_parse_retries})..."
                        })
                        continue
                    else:
                        return {
                            "success": False,
                            "error": last_error
                        }

                # SUCCESS! Return the single parsed test case
                parsed_test_case = test_cases[0]

                # Ensure ID is set correctly — prefer the original T.C.No from raw data
                # so TC_011, TC_012 are preserved when running a subset of tests.
                raw_tc_no = raw_test_case.get("T.C.No") or raw_test_case.get("tc_no")
                if raw_tc_no:
                    nums = ''.join(filter(str.isdigit, str(raw_tc_no)))
                    parsed_test_case["id"] = f"TC_{int(nums):03d}" if nums else f"TC_{test_index + 1:03d}"
                elif "id" not in parsed_test_case or not parsed_test_case["id"]:
                    parsed_test_case["id"] = f"TC_{test_index + 1:03d}"

                if attempt > 0:
                    print(f"[Supervisor] Parse succeeded on {attempt_label.lower()}")
                    self._broadcast({
                        "type": "thoughts",
                        "message": f"Parsing succeeded on {attempt_label.lower()}"
                    })

                return {
                    "success": True,
                    "parsed_test_case": parsed_test_case,
                    "common_selectors": parsed_suite.get("common_selectors", {}),
                    "test_data": parsed_suite.get("test_data", {})
                }

            except Exception as e:
                last_error = str(e)
                print(f"[Supervisor] Parse exception: {last_error}")

                if attempt < max_parse_retries:
                    self._broadcast({
                        "type": "thoughts",
                        "message": f"Parse error, retrying ({attempt + 1}/{max_parse_retries})..."
                    })
                    continue

        # All retries exhausted
        return {
            "success": False,
            "error": last_error
        }

    def _extract_base_url_from_raw(self, raw_data: List[Dict]) -> Optional[str]:
        """Extract base URL from raw test data."""
        import re
        for item in raw_data:
            steps = item.get("Test Case Steps", "") or item.get("steps", "")
            if isinstance(steps, str):
                urls = re.findall(r'https?://[^\s<>"]+', steps)
                if urls:
                    url = urls[0].rstrip('/')
                    parts = url.split('/')
                    if len(parts) >= 3:
                        return '/'.join(parts[:3])
        return None

    def _execute_single_test_with_retry(
        self,
        test_case: Dict,
        test_index: int,
        total_tests: int,
        initial_storage_state=None
    ) -> Dict[str, Any]:
        """
        Execute a single test case with retry logic.

        Returns the final result for this test (after retries if any).
        """
        test_id = test_case.get("id", f"TC_{test_index + 1:03d}")
        test_name = test_case.get("name", "Unknown Test")

        # Create a mini test suite with just this one test
        # Note: parsed_suite may be None when processing sequentially
        base_suite = self.state.parsed_suite or {}
        single_test_suite = {
            "project": base_suite.get("project", self.state.project_name),
            "base_url": base_suite.get("base_url", self.state.base_url),
            "common_selectors": base_suite.get("common_selectors", {}),
            "test_data": base_suite.get("test_data", {}),
            "test_cases": [test_case]
        }

        retry_count = 0
        current_timeout = self.state.timeout

        while retry_count <= self.state.max_retries:
            attempt_label = "Initial" if retry_count == 0 else f"Retry {retry_count}"
            print(f"[Supervisor] {attempt_label} attempt for {test_id}...")

            self._broadcast({
                "type": "delegation",
                "message": f"{attempt_label} execution of {test_name}",
                "sub_agent": "ExecutorAgent"
            })

            # Execute this single test
            exec_result = self.executor_agent.execute({
                "parsed_suite": single_test_suite,
                "headless": self.state.headless,
                "keep_browser_open": self.state.keep_browser_open,
                "timeout": current_timeout,
                "base_url": self.state.base_url,
                "initial_storage_state": initial_storage_state,
            })

            if not exec_result["success"]:
                print(f"[Supervisor] Execution error for {test_id}: {exec_result.get('error')}")
                retry_count += 1
                current_timeout = int(current_timeout * 1.5)
                continue

            # Get the result for this test
            execution_results = exec_result.get("execution_results") or {}
            results = execution_results.get("results", []) if isinstance(execution_results, dict) else []
            if not results:
                print(f"[Supervisor] No results returned for {test_id}")
                retry_count += 1
                continue

            test_result = results[0]  # Should be only one result
            status = test_result.get("status", "FAILED")

            if status == "PASSED":
                print(f"[Supervisor] {test_id} PASSED on {attempt_label.lower()} attempt")
                return test_result

            # Test failed - check if we should retry
            error = test_result.get("error", "")
            print(f"[Supervisor] {test_id} FAILED: {error[:100]}...")

            # Check if error is retryable
            is_retryable = self._is_error_retryable(error)

            if is_retryable and retry_count < self.state.max_retries:
                retry_count += 1
                current_timeout = int(current_timeout * 1.5)
                print(f"[Supervisor] Error is retryable, will retry ({retry_count}/{self.state.max_retries})")

                self._broadcast({
                    "type": "thoughts",
                    "message": f"Test {test_id} failed with retryable error. Retrying ({retry_count}/{self.state.max_retries})..."
                })
            else:
                if not is_retryable:
                    print(f"[Supervisor] Error is NOT retryable, marking as failed")
                else:
                    print(f"[Supervisor] Max retries reached for {test_id}")
                return test_result

        # All retries exhausted
        return test_result

    def _is_error_retryable(self, error: str) -> bool:
        """Check if an error is retryable."""
        error_lower = error.lower()

        # Non-retryable errors (test logic issues)
        non_retryable = [
            "assertion", "expected", "not equal", "mismatch",
            "invalid selector", "syntax error", "permission denied",
            "authentication", "unauthorized", "forbidden"
        ]

        for pattern in non_retryable:
            if pattern in error_lower:
                return False

        # Retryable errors (transient issues)
        retryable = [
            "timeout", "element not found", "not found", "navigation",
            "network", "connection", "waiting for", "locator resolved",
            "target closed", "page closed", "context closed"
        ]

        for pattern in retryable:
            if pattern in error_lower:
                return True

        # Default: retry once for unknown errors
        return True

    def run(
        self,
        raw_data: List[Dict],
        project_name: str = "Test Project",
        base_url: Optional[str] = None,
        headless: bool = True,
        keep_browser_open: bool = True,
        timeout: int = 30000,
        max_retries: int = 2,
        broadcast_func: Optional[Callable] = None,
        stop_event=None,
    ) -> Dict[str, Any]:
        """
        Run the multi-agent orchestration with LLM-driven decisions.
        The supervisor LLM decides which agent to call next based on state.
        """
        self._stop_event = stop_event  # Store so sub-agents can access it

        # Initialize state
        self.state = MultiAgentState(
            raw_data=raw_data,
            project_name=project_name,
            base_url=base_url,
            headless=headless,
            keep_browser_open=keep_browser_open,
            timeout=timeout,
            max_retries=max_retries,
            llm_provider=self.llm_provider,
            model=self.model,
            broadcast_func=broadcast_func
        )

        # Initialize sub-agents
        self._init_sub_agents(broadcast_func)

        self._broadcast({
            "type": "agent_phase",
            "phase": "starting",
            "message": "Deep Agent Supervisor starting multi-agent orchestration..."
        })

        max_iterations = 15  # Safety limit
        iteration = 0

        while iteration < max_iterations:
            # Check stop signal at the top of every iteration
            if stop_event and stop_event.is_set():
                print(f"[Supervisor] Stop requested — aborting workflow before iteration {iteration + 1}")
                self._broadcast({
                    "type": "execution_stopped",
                    "message": "Test execution stopped by user"
                })
                # Terminate the Playwright subprocess if it's still running
                self._terminate_playwright_process()
                return {"status": "stopped", "errors": ["Stopped by user"], "generated_script": None, "report_data": None}

            iteration += 1

            # STRICT CHECK: If report is already generated, we're done
            if self.state.report_data:
                print(f"[Supervisor] Report already generated, workflow complete.")
                break

            # Supervisor decides next delegation
            decision = self._decide_next_agent()
            delegate_to = decision.get("delegate_to", "DONE")

            print(f"[Supervisor] Iteration {iteration}: Delegating to {delegate_to}")

            if delegate_to == "DONE":
                break

            # STRICT CHECK: Don't allow re-execution after validation is final (passed or failed without retry)
            if delegate_to == "ExecutorAgent" and self.state.validation_status in ["passed", "failed"] and not self.state.failed_test_ids:
                print(f"[Supervisor] Skipping executor - validation is final ({self.state.validation_status}), moving to report")
                delegate_to = "ReporterAgent"

            # STRICT CHECK: If ExecutorAgent is chosen but tests already ran and not yet validated, force ValidatorAgent
            # This prevents the LLM from skipping validation and re-running tests unnecessarily
            if delegate_to == "ExecutorAgent" and self.state.execution_results and self.state.validation_status == "pending":
                print(f"[Supervisor] Tests already executed, forcing validation before any re-execution")
                delegate_to = "ValidatorAgent"

            # Delegate to chosen sub-agent
            if delegate_to == "ParserAgent":
                # Guard: if we already have a parsed suite (even partial), skip re-parsing
                # This prevents a loop when batch parsing partially failed (e.g. rate limit on batch 2)
                if self.state.parsed_suite:
                    parsed_count = len(self.state.parsed_suite.get("test_cases", []))
                    print(f"[Supervisor] parsed_suite already set ({parsed_count} tests) — skipping re-parse, proceeding to executor")
                    continue
                result = self._delegate_to_parser()
                if not result["success"]:
                    # Let supervisor decide what to do
                    continue

            elif delegate_to == "ExecutorAgent":
                # retry_count is already incremented in _delegate_to_validator when needs_retry
                result = self._delegate_to_executor()
                if not result["success"]:
                    continue

            elif delegate_to == "ValidatorAgent":
                # Don't re-validate if report is already generated
                if self.state.report_data:
                    print(f"[Supervisor] Report already exists, skipping validator.")
                    break
                result = self._delegate_to_validator()

            elif delegate_to == "ReporterAgent":
                # Final stop check: skip report if user stopped
                if stop_event and stop_event.is_set():
                    print(f"[Supervisor] Stop requested — skipping ReporterAgent")
                    self._terminate_playwright_process()
                    return {"status": "stopped", "errors": ["Stopped by user"], "generated_script": None, "report_data": None}
                result = self._delegate_to_reporter()
                # Report generated, workflow is complete - exit immediately
                print(f"[Supervisor] Report generated, workflow complete.")
                break

            else:
                print(f"[Supervisor] Unknown sub-agent: {delegate_to}")
                break

        # Build final result
        final_result = self._build_final_result()

        self._broadcast({
            "type": "deep_agent_complete",
            "status": "success" if self.state.validation_status == "passed" else "completed",
            "message": f"Multi-agent orchestration complete: {final_result['summary']['passed']}/{final_result['summary']['total']} passed",
            "data": final_result["summary"],
            "execution_results": final_result["execution_results"],
            "parsed_suite": final_result["parsed_suite"],
            "orchestration": final_result["orchestration"],
        })

        return final_result

    def _terminate_playwright_process(self):
        """Terminate the Playwright subprocess if it is still alive."""
        try:
            proc = getattr(self, '_playwright_process', None)
            if proc is not None and proc.is_alive():
                print(f"[Supervisor] Terminating Playwright process (pid={proc.pid})")
                proc.terminate()
                proc.join(timeout=5)
        except Exception as e:
            print(f"[Supervisor] Error terminating Playwright process: {e}")

    def _build_final_result(self) -> Dict[str, Any]:
        """Build the final result dictionary."""
        results = self.state.execution_results or {}

        return {
            "status": "success" if self.state.validation_status == "passed" else "completed",
            "validation_status": self.state.validation_status,
            "summary": {
                "total": results.get("total", 0),
                "passed": results.get("passed", 0),
                "failed": results.get("failed", 0),
                "retries": self.state.retry_count
            },
            "execution_results": self.state.execution_results,
            "parsed_suite": self.state.parsed_suite,
            "report": self.state.report_data,
            "generated_script": self.state.generated_script,
            "orchestration": {
                "iterations": len(self.state.action_history),
                "action_history": self.state.action_history,
                "sub_agents_used": list(set(a["agent"] for a in self.state.action_history))
            },
            "errors": self.state.errors
        }


# Convenience function
def run_multi_agent(
    raw_data: List[Dict],
    project_name: str = "Test Project",
    base_url: Optional[str] = None,
    llm_provider: str = "groq",
    model: Optional[str] = None,
    headless: bool = True,
    keep_browser_open: bool = True,
    timeout: int = 30000,
    max_retries: int = 2,
    broadcast_func: Optional[Callable] = None,
    stop_event=None,
) -> Dict[str, Any]:
    """
    Run the multi-agent deep automation system.

    The supervisor coordinates specialized sub-agents:
    - ParserAgent: Parses test cases
    - ExecutorAgent: Runs tests
    - ValidatorAgent: Analyzes results
    - ReporterAgent: Generates reports
    """
    orchestrator = MultiAgentOrchestrator(
        llm_provider=llm_provider,
        model=model
    )

    return orchestrator.run_sequential(
        raw_data=raw_data,
        project_name=project_name,
        base_url=base_url,
        headless=headless,
        keep_browser_open=keep_browser_open,
        timeout=timeout,
        max_retries=max_retries,
        broadcast_func=broadcast_func,
        stop_event=stop_event,
    )
