"""
Sub-Agents for Deep Agent Multi-Agent System

Each sub-agent is specialized for a specific task:
- ParserAgent: Parses test cases using LLM
- ExecutorAgent: Runs tests in browser
- ValidatorAgent: Analyzes results, decides retry
- ReporterAgent: Generates reports and scripts

The Deep Agent Orchestrator supervises and coordinates these sub-agents.
"""

from .base_sub_agent import BaseSubAgent
from .parser_agent import ParserAgent
from .executor_agent import ExecutorAgent
from .validator_agent import ValidatorAgent
from .reporter_agent import ReporterAgent

__all__ = [
    "BaseSubAgent",
    "ParserAgent",
    "ExecutorAgent",
    "ValidatorAgent",
    "ReporterAgent"
]
