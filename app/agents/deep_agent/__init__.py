"""
Deep Agent - Multi-Agent Test Automation Orchestrator

This module provides intelligent orchestration using the Multi-Agent System:
- Supervisor agent coordinates specialized sub-agents
- LLM-driven decision making
- Sub-agents: ParserAgent, ExecutorAgent, ValidatorAgent, ReporterAgent

Features:
- Automatic pipeline orchestration
- Intelligent validation and retry logic
- Real-time progress updates via SSE
"""

# Multi-agent orchestration (supervisor + sub-agents)
from app.agents.deep_agent.multi_agent_orchestrator import (
    MultiAgentOrchestrator,
    run_multi_agent
)

# Sub-agents
from app.agents.deep_agent.sub_agents import (
    BaseSubAgent,
    ParserAgent,
    ExecutorAgent,
    ValidatorAgent,
    ReporterAgent
)

__all__ = [
    # Multi-agent orchestration
    "MultiAgentOrchestrator",
    "run_multi_agent",
    # Sub-agents
    "BaseSubAgent",
    "ParserAgent",
    "ExecutorAgent",
    "ValidatorAgent",
    "ReporterAgent",
]
