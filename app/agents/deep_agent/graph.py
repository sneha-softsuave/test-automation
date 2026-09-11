"""
Deep Agent Graph - LangGraph StateGraph Builder

Builds and runs the test automation state machine:
  START → parse → execute → validate
                              ↓
                [conditional routing]
                ├── passed → report → END
                ├── needs_retry → recover → execute (loop)
                └── failed → report → END
"""

from typing import Dict, Any, Literal
from langgraph.graph import StateGraph, END

from app.agents.deep_agent.state import TestAutomationState, create_initial_state
from app.agents.deep_agent.nodes import (
    parse_node,
    execute_node,
    validate_node,
    report_node,
    error_recovery_node,
)


def create_deep_agent_graph() -> StateGraph:
    """
    Create the Deep Agent state graph.

    Graph structure:
        START
          ↓
        parse (EnhancedJsonParserAgent)
          ↓
        execute (Playwright execution)
          ↓
        validate (Check results)
          ↓
        [conditional]
          ├── "passed" → report → END
          ├── "needs_retry" → error_recovery → execute (loop)
          └── "failed" → report → END

    Returns:
        Compiled StateGraph ready to run
    """
    # Create the graph with our state type
    graph = StateGraph(TestAutomationState)

    # Add all nodes
    graph.add_node("parse", parse_node)
    graph.add_node("execute", execute_node)
    graph.add_node("validate", validate_node)
    graph.add_node("report", report_node)
    graph.add_node("error_recovery", error_recovery_node)

    # Set entry point
    graph.set_entry_point("parse")

    # Add edges for the main flow
    graph.add_edge("parse", "execute")
    graph.add_edge("execute", "validate")

    # Conditional routing after validation
    graph.add_conditional_edges(
        "validate",
        _route_after_validation,
        {
            "report": "report",
            "retry": "error_recovery",
        }
    )

    # Error recovery loops back to execute
    graph.add_edge("error_recovery", "execute")

    # Report is the final node
    graph.add_edge("report", END)

    return graph.compile()


def _route_after_validation(state: TestAutomationState) -> Literal["report", "retry"]:
    """
    Route based on validation status.

    Returns:
        "report" - Go to report node (for passed or final failed)
        "retry" - Go to error recovery (for retryable failures)
    """
    validation_status = state.get("validation_status", "failed")

    if validation_status == "passed":
        return "report"
    elif validation_status == "needs_retry":
        return "retry"
    else:
        # Failed with no retry possible
        return "report"


def run_deep_agent(
    raw_data: list,
    project_name: str,
    session_id: str,
    base_url: str = None,
    llm_provider: str = "groq",
    model: str = "llama-3.1-8b-instant",
    headless: bool = True,
    timeout: int = 30000,
    max_retries: int = 2,
    broadcast_func: callable = None,
    stop_event=None,
    step_control_file: str = None,
) -> Dict[str, Any]:
    """
    Run the Deep Agent workflow.

    Args:
        raw_data: Raw test case data from Excel/JSON
        project_name: Name of the test project
        session_id: Unique session ID for SSE
        base_url: Base URL for tests
        llm_provider: LLM provider ("anthropic", "openai", "groq")
        model: Model name
        headless: Run browser headless
        timeout: Playwright timeout in ms
        max_retries: Maximum retry attempts
        broadcast_func: Function to broadcast SSE events

    Returns:
        Final state with all results
    """
    # Create initial state
    initial_state = create_initial_state(
        raw_data=raw_data,
        project_name=project_name,
        session_id=session_id,
        base_url=base_url,
        llm_provider=llm_provider,
        model=model,
        headless=headless,
        timeout=timeout,
        max_retries=max_retries,
        broadcast_func=broadcast_func
    )
    # Inject step control into state so execute node can pass it down
    initial_state["step_control_file"] = step_control_file
    initial_state["stop_event"] = stop_event

    # Broadcast workflow start
    if broadcast_func:
        broadcast_func({
            "type": "agent_phase",
            "phase": "starting",
            "message": "Deep Agent workflow starting..."
        })

    try:
        # Create and run the graph
        print("[Deep Agent Graph] Creating graph...")
        graph = create_deep_agent_graph()
        print("[Deep Agent Graph] Graph created, starting execution...")

        # Accumulate state from all nodes
        accumulated_state = dict(initial_state)

        for state_update in graph.stream(initial_state):
            # Each update contains the node name and its partial output
            for node_name, node_output in state_update.items():
                print(f"[Deep Agent Graph] Node completed: {node_name}")

                # Broadcast phase transitions
                if broadcast_func:
                    broadcast_func({
                        "type": "agent_phase",
                        "phase": node_name,
                        "message": f"Completed: {node_name}"
                    })

                # Merge node output into accumulated state
                if node_output and isinstance(node_output, dict):
                    accumulated_state.update(node_output)
                    print(f"[Deep Agent Graph] State keys after {node_name}: {list(accumulated_state.keys())}")

        # Broadcast workflow complete
        if broadcast_func:
            broadcast_func({
                "type": "agent_phase",
                "phase": "complete",
                "message": "Deep Agent workflow completed"
            })

        print("[Deep Agent Graph] Workflow completed successfully")
        print(f"[Deep Agent Graph] Final state keys: {list(accumulated_state.keys())}")
        return accumulated_state

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[Deep Agent Graph] ERROR: {str(e)}")
        print(f"[Deep Agent Graph] Traceback:\n{error_trace}")

        if broadcast_func:
            broadcast_func({
                "type": "agent_phase",
                "phase": "error",
                "message": f"Workflow failed: {str(e)}"
            })

        raise


async def run_deep_agent_async(
    raw_data: list,
    project_name: str,
    session_id: str,
    base_url: str = None,
    llm_provider: str = "groq",
    model: str = "llama-3.1-8b-instant",
    headless: bool = True,
    timeout: int = 30000,
    max_retries: int = 2,
    broadcast_func: callable = None
) -> Dict[str, Any]:
    """
    Async version of run_deep_agent for FastAPI integration.

    Uses asyncio.to_thread to run the synchronous graph in a thread pool.
    """
    import asyncio

    return await asyncio.to_thread(
        run_deep_agent,
        raw_data=raw_data,
        project_name=project_name,
        session_id=session_id,
        base_url=base_url,
        llm_provider=llm_provider,
        model=model,
        headless=headless,
        timeout=timeout,
        max_retries=max_retries,
        broadcast_func=broadcast_func
    )
