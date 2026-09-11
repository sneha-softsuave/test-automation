"""LocustGeneratorAgent: Generates AI-optimized Locustfiles with best practices."""

import json
import re
import logging
from typing import Dict, Any

from app.agents.load_test.sub_agents.base_load_test_agent import BaseLoadTestAgent
from app.agents.load_test.state import AgenticLoadTestState

# Configure logger
logger = logging.getLogger(__name__)


class LocustGeneratorAgent(BaseLoadTestAgent):
    """
    Generates optimized Locustfile based on API analysis and test data.

    Responsibilities:
    - Create Locustfile with best practices
    - Add performance assertions (response time thresholds)
    - Implement smart retry logic
    - Add realistic error handling
    - Optimize wait_time strategy
    - Add logging and monitoring hooks
    """

    def execute(self, state: AgenticLoadTestState) -> AgenticLoadTestState:
        """
        Generate optimized Locustfile.

        Args:
            state: Current state with parsed_config and generated_data

        Returns:
            Updated state with locustfile_path and locustfile_content
        """
        logger.info("\n" + "="*80)
        logger.info("🤖 AGENT 3/6: LocustGeneratorAgent")
        logger.info("="*80)

        self.add_thought(
            state,
            "Generating optimized Locustfile...",
            "Creating load test script with AI-powered best practices",
            "creating_locustfile"
        )

        api_type = state.get('api_type', 'crud_read')
        parsed_config = state.get('parsed_config', {})
        generated_data = state.get('generated_data', [])
        think_time = state.get('recommended_think_time', {'min': 1.0, 'max': 3.0})
        data_mode = state.get('recommended_data_mode', 'round_robin')

        logger.info("📋 Configuration:")
        logger.info(f"   • API Type: {api_type}")
        logger.info(f"   • Endpoint: {parsed_config.get('endpoint', 'N/A')}")
        logger.info(f"   • Method: {parsed_config.get('method', 'N/A')}")
        logger.info(f"   • Test Data Entries: {len(generated_data)}")
        logger.info(f"   • Data Mode: {data_mode}")
        logger.info(f"   • Think Time: {think_time.get('min')}-{think_time.get('max')}s")

        # Generate Locustfile using AI
        logger.info("\n🔧 Generating Locustfile...")
        locustfile_content = self._generate_optimized_locustfile(
            api_type=api_type,
            config=parsed_config,
            test_data=generated_data,
            think_time=think_time,
            data_mode=data_mode
        )

        logger.info(f"   ✅ Generated {len(locustfile_content)} characters")

        # Show preview of generated Locustfile
        logger.info("\n📄 Locustfile Preview (first 50 lines):")
        logger.info("─" * 80)
        lines = locustfile_content.split('\n')
        for i, line in enumerate(lines[:50], 1):
            logger.info(f"{i:3d} │ {line}")
        if len(lines) > 50:
            logger.info(f"... │ [{len(lines) - 50} more lines]")
        logger.info("─" * 80)

        self.add_thought(
            state,
            "Locustfile generation complete",
            f"Generated {len(locustfile_content)} characters with optimizations for {api_type} API",
            "creating_locustfile"
        )

        state['locustfile_content'] = locustfile_content

        logger.info("\n✅ LocustGeneratorAgent Complete!")
        logger.info("="*80 + "\n")

        return state

    def _generate_optimized_locustfile(
        self,
        api_type: str,
        config: Dict[str, Any],
        test_data: list,
        think_time: Dict[str, float],
        data_mode: str
    ) -> str:
        """
        Generate optimized Locustfile using AI.

        Returns:
            Complete Locustfile as string
        """
        # Build context for AI
        endpoint = config.get('endpoint', '/')
        method = config.get('method', 'GET')
        payload = config.get('payload', {})
        headers = config.get('headers', {})
        base_url = config.get('base_url', '')

        prompt = f"""Generate an optimized Locust load testing script in Python.

API Details:
- Type: {api_type}
- Endpoint: {endpoint}
- Method: {method}
- Base URL: {base_url}
- Payload: {json.dumps(payload, indent=2)}
- Headers: {json.dumps(headers, indent=2)}

Test Configuration:
- Test Data: {len(test_data)} entries available
- Data Mode: {data_mode}
- Think Time: {think_time['min']}s - {think_time['max']}s

Requirements:
1. Use Locust's HttpUser and task decorators
2. Implement {data_mode} data cycling in on_start()
3. Add response time assertions (95th percentile thresholds based on API type)
4. Include realistic error handling and retry logic
5. Add logging for debugging
6. Use wait_time = between({think_time['min']}, {think_time['max']})
7. Embed TEST_DATA directly in the file
8. Add catch_response for proper error tracking
9. Include performance monitoring hooks

Best Practices for {api_type} APIs:
{self._get_best_practices(api_type)}

Return ONLY the complete Python code (no markdown, no explanations):"""

        try:
            response = self.call_llm(prompt)

            # Extract Python code from response
            code_match = re.search(r'```python\n(.*?)\n```', response, re.DOTALL)
            if code_match:
                locustfile = code_match.group(1)
            else:
                # If no markdown blocks, assume entire response is code
                locustfile = response.strip()

            # Validate it's Python code
            if 'from locust import' in locustfile and 'class' in locustfile:
                return locustfile

        except Exception as e:
            print(f"AI Locustfile generation failed: {e}")

        # Fallback to template-based generation
        return self._generate_template_locustfile(
            api_type=api_type,
            config=config,
            test_data=test_data,
            think_time=think_time,
            data_mode=data_mode
        )

    def _get_best_practices(self, api_type: str) -> str:
        """Get best practices for specific API type."""
        practices = {
            'authentication': """
- Response time threshold: 95th percentile < 1000ms
- Retry failed logins up to 2 times
- Log successful/failed authentication attempts
- Track session token validity
- Monitor for rate limiting (429 responses)
""",
            'search': """
- Response time threshold: 95th percentile < 500ms
- Cache headers important for performance
- Vary query parameters for realistic load
- Track empty result sets separately
- Monitor search result quality
""",
            'transaction': """
- Response time threshold: 95th percentile < 2000ms
- Implement idempotency checks
- Track transaction IDs for correlation
- Monitor for race conditions
- Log payment status codes separately
""",
            'crud_create': """
- Response time threshold: 95th percentile < 1000ms
- Verify created resource IDs
- Track duplicate creation attempts
- Monitor validation errors
- Check for proper 201 status codes
""",
            'crud_read': """
- Response time threshold: 95th percentile < 500ms
- Track cache hit/miss rates
- Monitor 404 rates
- Vary pagination parameters
- Check response data completeness
"""
        }
        return practices.get(api_type, practices['crud_read'])

    def _generate_template_locustfile(
        self,
        api_type: str,
        config: Dict[str, Any],
        test_data: list,
        think_time: Dict[str, float],
        data_mode: str
    ) -> str:
        """Fallback template-based generation."""
        endpoint = config.get('endpoint', '/')
        method = config.get('method', 'GET').lower()
        payload = config.get('payload', {})
        headers = config.get('headers', {})
        base_url = config.get('base_url', '')

        # Get response time threshold based on API type
        thresholds = {
            'authentication': 1000,
            'search': 500,
            'transaction': 2000,
            'crud_create': 1000,
            'crud_read': 500
        }
        threshold = thresholds.get(api_type, 1000)

        # Build template
        template = f"""from locust import HttpUser, task, between, events
import json
import random
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OptimizedAPIUser(HttpUser):
    \"\"\"AI-optimized load test for {api_type} API\"\"\"

    host = "{base_url}"
    wait_time = between({think_time['min']}, {think_time['max']})

    # Performance threshold (95th percentile)
    RESPONSE_TIME_THRESHOLD = {threshold}  # milliseconds

    # Embedded test data
    TEST_DATA = {json.dumps(test_data, indent=4)}
    DATA_MODE = "{data_mode}"

    def on_start(self):
        \"\"\"Initialize user session with data assignment.\"\"\"
        self.headers = {json.dumps(headers, indent=8)}

        # Assign test data based on mode
        if self.DATA_MODE == "sequential":
            data_index = getattr(self.environment.runner, 'user_count', 0) % len(self.TEST_DATA)
        elif self.DATA_MODE == "random":
            data_index = random.randint(0, len(self.TEST_DATA) - 1)
        else:  # round_robin
            data_index = hash(id(self)) % len(self.TEST_DATA)

        self.user_data = self.TEST_DATA[data_index] if self.TEST_DATA else {{}}
        self.request_count = 0
        self.start_time = datetime.now()

        logger.info(f"User {{id(self)}} started with data index {{data_index}}")

    @task
    def api_request(self):
        \"\"\"Main API request with optimizations.\"\"\"
        self.request_count += 1

        # Build dynamic payload
        payload = {self._substitute_variables(payload)}

        # Make request with comprehensive error handling
        with self.client.{method}(
            "{endpoint}",
            {"json=payload," if method in ['post', 'put', 'patch'] and payload else ""}
            headers=self.headers,
            catch_response=True,
            name="{method.upper()} {endpoint}"
        ) as response:
            try:
                # Check status code
                if response.status_code in [200, 201, 204]:
                    # Check response time against threshold
                    if response.elapsed.total_seconds() * 1000 > self.RESPONSE_TIME_THRESHOLD:
                        response.failure(
                            f"Response time {{response.elapsed.total_seconds() * 1000:.0f}}ms "
                            f"exceeded threshold {{self.RESPONSE_TIME_THRESHOLD}}ms"
                        )
                    else:
                        response.success()
                        logger.debug(f"Request {{self.request_count}} succeeded in {{response.elapsed.total_seconds() * 1000:.0f}}ms")

                elif response.status_code == 429:
                    # Rate limiting
                    response.failure("Rate limited (429)")
                    logger.warning(f"User {{id(self)}} rate limited")
                    # Back off
                    self.wait_time = between({think_time['max'] * 2}, {think_time['max'] * 4})

                elif response.status_code >= 500:
                    # Server error - might be transient
                    response.failure(f"Server error: {{response.status_code}}")
                    logger.error(f"Server error {{response.status_code}}: {{response.text[:200]}}")

                else:
                    # Client error
                    response.failure(f"Client error: {{response.status_code}}")
                    logger.warning(f"Client error {{response.status_code}}: {{response.text[:200]}}")

            except Exception as e:
                response.failure(f"Exception: {{str(e)}}")
                logger.error(f"Request failed with exception: {{e}}")

    def on_stop(self):
        \"\"\"Cleanup on user stop.\"\"\"
        duration = (datetime.now() - self.start_time).total_seconds()
        logger.info(
            f"User {{id(self)}} stopped. "
            f"Duration: {{duration:.1f}}s, "
            f"Requests: {{self.request_count}}"
        )


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    \"\"\"Called when test starts.\"\"\"
    logger.info("=" * 60)
    logger.info(f"Load test starting for {api_type} API")
    logger.info(f"Target: {base_url}{endpoint}")
    logger.info(f"Data mode: {data_mode}")
    logger.info(f"Response time threshold: {threshold}ms (95th percentile)")
    logger.info("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    \"\"\"Called when test stops.\"\"\"
    logger.info("=" * 60)
    logger.info("Load test completed")
    logger.info("=" * 60)
"""
        return template

    def _substitute_variables(self, obj: Any) -> str:
        """Generate code for variable substitution."""
        if not obj:
            return "None"

        def process_value(value: Any, depth: int = 0) -> str:
            indent = "    " * depth

            if isinstance(value, str):
                if '{{' in value and '}}' in value:
                    # String with variables
                    pattern = r'\{\{(\w+)\}\}'
                    replaced = re.sub(pattern, r'{self.user_data.get("\1", "")}', value)
                    return f'f"{replaced}"'
                else:
                    return repr(value)
            elif isinstance(value, dict):
                items = []
                for k, v in value.items():
                    val_str = process_value(v, depth + 1)
                    items.append(f'{indent}    {repr(k)}: {val_str}')
                if items:
                    return "{\n" + ",\n".join(items) + f"\n{indent}}}"
                return "{}"
            elif isinstance(value, list):
                items = [process_value(item, depth + 1) for item in value]
                return "[" + ", ".join(items) + "]"
            else:
                return repr(value)

        return process_value(obj)
