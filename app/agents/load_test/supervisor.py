"""Supervisor agent for orchestrating load test agents."""

from typing import Optional, AsyncGenerator, Dict, Any
from datetime import datetime
import asyncio
import json
import uuid
import logging

from app.agents.load_test.state import AgenticLoadTestState, AgentDelegation
from app.agents.load_test.sub_agents import (
    ConfigParserAgent,
    DataGeneratorAgent,
    LocustGeneratorAgent,
    ExecutorAgent,
    AnalyzerAgent,
    ReporterAgent
)
from app.agents.base_agent import LLMProvider
from app.core.config import settings

# Configure logger
logger = logging.getLogger(__name__)


class LoadTestSupervisor:
    """
    Supervisor agent that orchestrates the agentic load testing workflow.

    Workflow:
    1. ConfigParserAgent analyzes API configuration
    2. DataGeneratorAgent generates realistic test data
    3. Returns state with recommendations and generated data
    """

    def __init__(
        self,
        provider: LLMProvider = LLMProvider.GROQ,
        model: Optional[str] = None
    ):
        """Initialize supervisor with LLM configuration."""
        logger.info("="*80)
        logger.info("🤖 Initializing LoadTestSupervisor")
        logger.info("="*80)

        self.provider = provider
        self.model = model or self._get_default_model(provider)

        logger.info(f"📋 Configuration:")
        logger.info(f"   • LLM Provider: {provider.value}")
        logger.info(f"   • Model: {self.model}")
        logger.info(f"   • Source: {'User specified' if model else 'Default from settings'}")

        # Initialize sub-agents
        logger.info("\n🔧 Initializing AI Agents:")
        self.config_parser = self._create_agent(ConfigParserAgent)
        logger.info("   ✓ ConfigParserAgent initialized")

        self.data_generator = self._create_agent(DataGeneratorAgent)
        logger.info("   ✓ DataGeneratorAgent initialized")

        self.locust_generator = self._create_agent(LocustGeneratorAgent)
        logger.info("   ✓ LocustGeneratorAgent initialized")

        self.executor = self._create_agent(ExecutorAgent)
        logger.info("   ✓ ExecutorAgent initialized")

        self.analyzer = self._create_agent(AnalyzerAgent)
        logger.info("   ✓ AnalyzerAgent initialized")

        self.reporter = self._create_agent(ReporterAgent)
        logger.info("   ✓ ReporterAgent initialized")

        logger.info("\n✅ LoadTestSupervisor ready with 6 AI agents")
        logger.info("="*80 + "\n")

    def _get_default_model(self, provider: LLMProvider) -> str:
        """Get default model for provider from settings."""
        models = {
            LLMProvider.GROQ: settings.GROQ_MODEL,
            LLMProvider.OPENAI: settings.OPENAI_MODEL,
            LLMProvider.ANTHROPIC: settings.ANTHROPIC_MODEL,
            LLMProvider.WAYMORE: settings.WAYMORE_MODEL,
        }
        return models.get(provider, settings.GROQ_MODEL)

    def _create_agent(self, agent_class):
        """Create agent with current LLM configuration."""
        if self.provider == LLMProvider.GROQ:
            return agent_class(
                provider=self.provider,
                groq_api_key=settings.GROQ_API_KEY,
                groq_model=self.model
            )
        elif self.provider == LLMProvider.OPENAI:
            return agent_class(
                provider=self.provider,
                openai_api_key=settings.OPENAI_API_KEY,
                openai_model=self.model
            )
        elif self.provider == LLMProvider.WAYMORE:
            return agent_class(
                provider=self.provider,
                waymore_api_key=settings.WAYMORE_API_KEY,
                waymore_model=self.model
            )
        else:  # ANTHROPIC
            return agent_class(
                provider=self.provider,
                anthropic_api_key=settings.ANTHROPIC_API_KEY,
                anthropic_model=self.model
            )

    async def execute_agentic_workflow(
        self,
        raw_config: Dict[str, Any],
        excel_filename: str
    ) -> AsyncGenerator[str, None]:
        """
        Execute agentic workflow and stream SSE events.

        Args:
            raw_config: Parsed API configuration from Excel
            excel_filename: Name of uploaded file

        Yields:
            SSE events as strings
        """
        # Initialize state
        state: AgenticLoadTestState = {
            'raw_config': raw_config,
            'excel_filename': excel_filename,
            'session_id': str(uuid.uuid4()),
            'started_at': datetime.now(),
            'agent_thoughts': [],
            'errors': []
        }

        logger.info("\n" + "="*80)
        logger.info("🚀 Starting Agentic Workflow")
        logger.info("="*80)
        logger.info(f"📝 Session ID: {state['session_id']}")
        logger.info(f"📁 Excel File: {excel_filename}")
        logger.info(f"🎯 API Name: {raw_config.get('name', 'Unknown API')}")
        logger.info(f"🔗 Endpoint: {raw_config.get('endpoint', 'N/A')}")
        logger.info(f"📮 Method: {raw_config.get('method', 'N/A')}")
        logger.info("="*80 + "\n")

        # Send initial event
        yield self._format_sse_event('agentic_test_started', {
            'session_id': state['session_id'],
            'filename': excel_filename,
            'api_name': raw_config.get('name', 'Unknown API')
        })

        try:
            # Phase 1: ConfigParserAgent
            logger.info("🤖 Phase 1/2: ConfigParserAgent")
            logger.info("   └─ Analyzing API configuration...")

            yield self._format_sse_event('agent_phase', {
                'phase': 'parsing',
                'agent': 'ConfigParserAgent',
                'description': 'Analyzing API configuration and inferring requirements'
            })

            state = await asyncio.to_thread(self.config_parser.execute, state)

            if state.get('api_type'):
                logger.info(f"   ✓ API Type Detected: {state['api_type']}")
            if state.get('required_fields'):
                logger.info(f"   ✓ Required Fields: {', '.join(state['required_fields'])}")
            if state.get('recommendations'):
                logger.info(f"   ✓ Recommendations Generated")

            # Stream thoughts from ConfigParserAgent
            for thought in state.get('agent_thoughts', [])[-3:]:  # Last 3 thoughts
                yield self._format_sse_event('agent_thinking', {
                    'agent': thought['agent'],
                    'thought': thought['thought'],
                    'reasoning': thought['reasoning'],
                    'phase': thought['phase']
                })

            # Send parsed config results
            yield self._format_sse_event('config_parsed', {
                'api_type': state.get('api_type'),
                'required_fields': state.get('required_fields', []),
                'recommended_users': state.get('recommended_users'),
                'recommended_spawn_rate': state.get('recommended_spawn_rate'),
                'recommended_think_time': state.get('recommended_think_time'),
                'recommended_data_mode': state.get('recommended_data_mode')
            })

            # Phase 2: DataGeneratorAgent
            if state.get('required_fields'):
                yield self._format_sse_event('agent_delegation', {
                    'from': 'ConfigParserAgent',
                    'to': 'DataGeneratorAgent',
                    'reason': f"Configuration analyzed. Now generating test data for {len(state.get('required_fields', []))} fields."
                })

                yield self._format_sse_event('agent_phase', {
                    'phase': 'generating_data',
                    'agent': 'DataGeneratorAgent',
                    'description': 'Generating realistic test data'
                })

                # Store thought count before data generation
                thoughts_before = len(state.get('agent_thoughts', []))

                state = await asyncio.to_thread(self.data_generator.execute, state)

                # Stream new thoughts from DataGeneratorAgent
                all_thoughts = state.get('agent_thoughts', [])
                new_thoughts = all_thoughts[thoughts_before:]

                for thought in new_thoughts:
                    yield self._format_sse_event('agent_thinking', {
                        'agent': thought['agent'],
                        'thought': thought['thought'],
                        'reasoning': thought['reasoning'],
                        'phase': thought['phase']
                    })

                # Send generated data
                generated_data = state.get('generated_data', [])
                yield self._format_sse_event('data_generated', {
                    'count': len(generated_data),
                    'fields': state.get('required_fields', []),
                    'sample': generated_data[0] if generated_data else None,
                    'generation_method': state.get('data_generation_method')
                })
            else:
                yield self._format_sse_event('data_generation_skipped', {
                    'reason': 'No test data fields required (static payload)'
                })

            # Phase complete
            state['completed_at'] = datetime.now()

            yield self._format_sse_event('agentic_analysis_complete', {
                'session_id': state['session_id'],
                'api_type': state.get('api_type'),
                'recommendations': {
                    'users': state.get('recommended_users'),
                    'spawn_rate': state.get('recommended_spawn_rate'),
                    'think_time': state.get('recommended_think_time'),
                    'data_mode': state.get('recommended_data_mode')
                },
                'generated_data_count': len(state.get('generated_data', [])),
                'required_fields': state.get('required_fields', [])
            })

        except Exception as e:
            error_msg = str(e)
            state['errors'].append(error_msg)

            yield self._format_sse_event('agentic_error', {
                'error': error_msg,
                'phase': state.get('agent_phase', 'unknown')
            })

    def _format_sse_event(self, event_type: str, data: Dict[str, Any]) -> str:
        """Format data as SSE event."""
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    async def execute_full_workflow(
        self,
        raw_config: Dict[str, Any],
        excel_filename: str,
        test_id: str
    ) -> AsyncGenerator[str, None]:
        """
        Execute complete agentic workflow: Config → Data → Locust → Execute → Analyze → Report.

        This is the full Phase 2B workflow with all 6 agents.

        Args:
            raw_config: Parsed API configuration from Excel
            excel_filename: Name of uploaded file
            test_id: Test execution ID

        Yields:
            SSE events as strings
        """
        # Initialize state
        state: AgenticLoadTestState = {
            'raw_config': raw_config,
            'excel_filename': excel_filename,
            'test_id': test_id,
            'session_id': str(uuid.uuid4()),
            'started_at': datetime.now(),
            'agent_thoughts': [],
            'errors': []
        }

        yield self._format_sse_event('full_workflow_started', {
            'session_id': state['session_id'],
            'test_id': test_id,
            'workflow': ['ConfigParser', 'DataGenerator', 'LocustGenerator', 'Executor', 'Analyzer', 'Reporter']
        })

        try:
            # Phase 1: ConfigParserAgent
            yield self._format_sse_event('agent_phase', {
                'phase': 'parsing',
                'agent': 'ConfigParserAgent',
                'step': 1,
                'total_steps': 6
            })

            state = await asyncio.to_thread(self.config_parser.execute, state)
            for event in self._stream_recent_thoughts(state, 'ConfigParserAgent'):
                yield event

            # Phase 2: DataGeneratorAgent
            if state.get('required_fields'):
                yield self._format_sse_event('agent_delegation', {
                    'from': 'ConfigParserAgent',
                    'to': 'DataGeneratorAgent',
                    'reason': f"Generating test data for {len(state.get('required_fields', []))} fields"
                })

                yield self._format_sse_event('agent_phase', {
                    'phase': 'generating_data',
                    'agent': 'DataGeneratorAgent',
                    'step': 2,
                    'total_steps': 6
                })

                thoughts_before = len(state.get('agent_thoughts', []))
                state = await asyncio.to_thread(self.data_generator.execute, state)
                for event in self._stream_recent_thoughts(state, 'DataGeneratorAgent', thoughts_before):
                    yield event

            # Phase 3: LocustGeneratorAgent
            yield self._format_sse_event('agent_delegation', {
                'from': 'DataGeneratorAgent',
                'to': 'LocustGeneratorAgent',
                'reason': 'Creating optimized Locustfile'
            })

            yield self._format_sse_event('agent_phase', {
                'phase': 'creating_locustfile',
                'agent': 'LocustGeneratorAgent',
                'step': 3,
                'total_steps': 6
            })

            thoughts_before = len(state.get('agent_thoughts', []))
            state = await asyncio.to_thread(self.locust_generator.execute, state)
            for event in self._stream_recent_thoughts(state, 'LocustGeneratorAgent', thoughts_before):
                yield event

            yield self._format_sse_event('locustfile_generated', {
                'size': len(state.get('locustfile_content', '')),
                'has_optimizations': 'catch_response' in state.get('locustfile_content', '')
            })

            # Phase 4: ExecutorAgent (monitoring - would happen during actual test)
            # This would be called periodically during test execution
            # For now, we'll simulate with a single check
            yield self._format_sse_event('agent_phase', {
                'phase': 'ready_for_execution',
                'agent': 'ExecutorAgent',
                'step': 4,
                'total_steps': 6,
                'note': 'Workflow ready. Run load test to activate ExecutorAgent monitoring.'
            })

            # Phase 5: AnalyzerAgent (would run after test completes)
            # Simulated for now
            yield self._format_sse_event('agent_phase', {
                'phase': 'ready_for_analysis',
                'agent': 'AnalyzerAgent',
                'step': 5,
                'total_steps': 6,
                'note': 'Will analyze results after test completes.'
            })

            # Phase 6: ReporterAgent (would run after analysis)
            yield self._format_sse_event('agent_phase', {
                'phase': 'ready_for_reporting',
                'agent': 'ReporterAgent',
                'step': 6,
                'total_steps': 6,
                'note': 'Will generate comprehensive report after test.'
            })

            # Complete
            state['completed_at'] = datetime.now()

            yield self._format_sse_event('full_workflow_complete', {
                'session_id': state['session_id'],
                'api_type': state.get('api_type'),
                'locustfile_ready': bool(state.get('locustfile_content')),
                'recommendations': self.get_recommendations(state)
            })

        except Exception as e:
            error_msg = str(e)
            state['errors'].append(error_msg)
            yield self._format_sse_event('workflow_error', {
                'error': error_msg,
                'phase': state.get('agent_phase', 'unknown')
            })

    def _stream_recent_thoughts(
        self,
        state: AgenticLoadTestState,
        agent_name: str,
        thoughts_before: int = 0
    ):
        """Helper to stream recent thoughts from an agent."""
        all_thoughts = state.get('agent_thoughts', [])
        new_thoughts = all_thoughts[thoughts_before:] if thoughts_before else all_thoughts[-3:]

        for thought in new_thoughts:
            if thought['agent'] == agent_name or not thoughts_before:
                yield self._format_sse_event('agent_thinking', {
                    'agent': thought['agent'],
                    'thought': thought['thought'],
                    'reasoning': thought['reasoning'],
                    'phase': thought['phase']
                })

    def get_recommendations(self, state: AgenticLoadTestState) -> Dict[str, Any]:
        """Extract recommendations from state."""
        return {
            'users': state.get('recommended_users', 100),
            'spawn_rate': state.get('recommended_spawn_rate', 10),
            'think_time_min': state.get('recommended_think_time', {}).get('min', 1.0),
            'think_time_max': state.get('recommended_think_time', {}).get('max', 3.0),
            'data_mode': state.get('recommended_data_mode', 'round_robin'),
            'test_data': state.get('generated_data', []),
            'api_type': state.get('api_type', 'unknown'),
            'locustfile': state.get('locustfile_content', '')
        }
