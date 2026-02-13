"""Dynamic Locustfile generator for API load testing."""

from typing import List, Optional, Dict, Any
from jinja2 import Template
from pathlib import Path
import json
import re

from app.models.load_test_models import APIConfig, AuthType


class DynamicLocustfileGenerator:
    """Generate Locustfiles dynamically from API configurations."""

    # Jinja2 template for single API test
    SINGLE_API_TEMPLATE = """from locust import HttpUser, task, between, events
import json
import random
import threading
import sys
from pathlib import Path

# Global failure tracking (deduplicated by status code)
_failure_samples = {}
_failure_lock = threading.Lock()
_test_id = "{{ test_id }}"

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    \"\"\"Save deduplicated failures when test stops\"\"\"
    if _failure_samples:
        failures_file = Path("load_test_results") / f"{_test_id}_failures.json"
        failures_file.parent.mkdir(exist_ok=True)

        with open(failures_file, 'w') as f:
            json.dump({
                "unique_failures": list(_failure_samples.values()),
                "total_failure_types": len(_failure_samples)
            }, f, indent=2)
        print(f"[FAILURES] Saved {len(_failure_samples)} unique failure types to {failures_file}", flush=True)

class DynamicAPIUser(HttpUser):
    \"\"\"Load test for {{ api.name }}\"\"\"

    host = "{{ api.base_url }}"
    wait_time = between({{ think_time_min }}, {{ think_time_max }})

    {% if test_data %}
    # Embedded test data for multi-user scenarios
    TEST_DATA = {{ test_data }}
    DATA_MODE = "{{ data_mode }}"

    # Thread-safe counter for proper sequential/round-robin distribution
    _user_counter = 0
    _counter_lock = threading.Lock()
    {% endif %}

    def _mask_token(self, token: str, chars: int = 10) -> str:
        \"\"\"Mask token showing only first N characters.\"\"\"
        if not token or len(token) <= chars:
            return token
        return f"{token[:chars]}...***"

    def _get_masked_headers(self) -> dict:
        \"\"\"Get headers with masked sensitive values for logging.\"\"\"
        masked = self.headers.copy()
        # Mask Authorization header
        if 'Authorization' in masked:
            auth_value = masked['Authorization']
            if auth_value.startswith('Bearer '):
                token = auth_value.replace('Bearer ', '')
                masked['Authorization'] = f"Bearer {self._mask_token(token)}"
            elif auth_value.startswith('Basic '):
                masked['Authorization'] = "Basic ***"
        # Mask any other sensitive headers (API keys, tokens, etc.)
        for key in masked:
            if any(sensitive in key.lower() for sensitive in ['token', 'key', 'secret', 'password']):
                if key != 'Authorization':  # Already handled
                    masked[key] = self._mask_token(str(masked[key]))
        return masked

    def _capture_failure(self, response, method, endpoint, error_message=""):
        \"\"\"Capture unique failure sample (deduplicated by status code)\"\"\"
        global _failure_samples, _failure_lock

        status_code = response.status_code

        # Only capture if we haven't seen this status code before
        with _failure_lock:
            if status_code not in _failure_samples:
                # Parse response body
                try:
                    response_body = response.json()
                except:
                    response_body = response.text[:1000] if response.text else ""

                _failure_samples[status_code] = {
                    "status_code": status_code,
                    "method": method,
                    "endpoint": endpoint,
                    "error_message": error_message or f"HTTP {status_code}",
                    "response_body": response_body,
                    "count": 1
                }
                print(f"[FAILURE CAPTURED] Status {status_code} - {method} {endpoint}", flush=True)
            else:
                # Increment count for existing failure type
                _failure_samples[status_code]["count"] += 1

    def on_start(self):
        \"\"\"Initialize headers and authentication.\"\"\"
        self.headers = {{ headers }}
        self.auth_info = "None"

        {% if test_data %}
        # Assign user-specific data based on cycling mode
        if self.DATA_MODE == "sequential":
            # Sequential: use thread-safe counter for proper distribution
            with DynamicAPIUser._counter_lock:
                data_index = DynamicAPIUser._user_counter % len(self.TEST_DATA)
                DynamicAPIUser._user_counter += 1
        elif self.DATA_MODE == "random":
            # Random: pick random data for each user
            data_index = random.randint(0, len(self.TEST_DATA) - 1)
        else:  # round_robin (default)
            # Round-robin: use thread-safe counter for proper distribution
            with DynamicAPIUser._counter_lock:
                data_index = DynamicAPIUser._user_counter % len(self.TEST_DATA)
                DynamicAPIUser._user_counter += 1

        self.user_data = self.TEST_DATA[data_index]
        print(f"[INIT] User started - using data: {self.user_data.get('email', 'N/A')}", flush=True)
        {% endif %}

        {% if api.auth_config.auth_type.value == "bearer" and api.auth_config.token %}
        # Bearer token authentication
        self.headers["Authorization"] = "Bearer {{ api.auth_config.token }}"
        self.auth_info = f"Bearer Token: {self._mask_token('{{ api.auth_config.token }}')}"
        {% elif api.auth_config.auth_type.value == "api_key" and api.auth_config.api_key_name and api.auth_config.api_key_value %}
        # API Key authentication
        self.headers["{{ api.auth_config.api_key_name }}"] = "{{ api.auth_config.api_key_value }}"
        self.auth_info = f"API Key ({{ api.auth_config.api_key_name }}): {self._mask_token('{{ api.auth_config.api_key_value }}')}"
        {% elif api.auth_config.auth_type.value == "basic" and api.auth_config.username and api.auth_config.password %}
        # Basic authentication
        import base64
        credentials = base64.b64encode(b"{{ api.auth_config.username }}:{{ api.auth_config.password }}").decode("utf-8")
        self.headers["Authorization"] = f"Basic {credentials}"
        self.auth_info = f"Basic Auth ({{ api.auth_config.username }}:***)"
        {% endif %}

    @task
    def {{ task_name }}(self):
        \"\"\"{{ api.description or api.name }}\"\"\"

        {% if test_data %}
        # Build dynamic payload/params with user-specific data
        {% if dynamic_payload %}
        payload = {{ dynamic_payload }}
        {% else %}
        payload = {{ payload }}
        {% endif %}
        {% if dynamic_query_params %}
        query_params = {{ dynamic_query_params }}
        {% else %}
        query_params = {{ query_params }}
        {% endif %}
        {% else %}
        # Static payload (no test data)
        payload = {{ payload }}
        query_params = {{ query_params }}
        {% endif %}

        {% if api.method == "GET" %}
        {% if api.query_params %}
        print(f"[REQUEST] GET {{ api.endpoint }} - Auth: {self.auth_info} - Headers: {self._get_masked_headers()} - Query Params: {query_params}", flush=True)
        {% else %}
        print(f"[REQUEST] GET {{ api.endpoint }} - Auth: {self.auth_info} - Headers: {self._get_masked_headers()}", flush=True)
        {% endif %}
        with self.client.get(
            "{{ api.endpoint }}",
            headers=self.headers,
            {% if api.query_params %}params=query_params,{% endif %}
            catch_response=True,
            name="{{ api.method }} {{ api.endpoint }}"
        ) as response:
            print(f"[RESPONSE] Status Code: {response.status_code}", flush=True)
            if response.status_code in [200, 201, 204]:
                # For authentication/login endpoints, validate response content
                {% if 'login' in api.endpoint.lower() or 'auth' in api.endpoint.lower() or 'signin' in api.endpoint.lower() %}
                try:
                    response_json = response.json()
                    if 'error' in response_json or 'message' in response_json:
                        error_msg = response_json.get('error') or response_json.get('message', '')
                        if any(keyword in str(error_msg).lower() for keyword in ['invalid', 'incorrect', 'wrong', 'failed', 'denied', 'unauthorized']):
                            self._capture_failure(response, "{{ api.method }}", "{{ api.endpoint }}", f"Authentication failed: {error_msg}")
                            response.failure(f"Authentication failed: {error_msg}")
                            print(f"[FAILURE] Authentication failed: {error_msg}", flush=True)
                        else:
                            response.success()
                            print(f"[SUCCESS] Request successful ({response.status_code})", flush=True)
                    elif any(key in response_json for key in ['token', 'access_token', 'user', 'data', 'session']):
                        response.success()
                        print(f"[SUCCESS] Login successful ({response.status_code})", flush=True)
                    else:
                        self._capture_failure(response, "{{ api.method }}", "{{ api.endpoint }}", f"Unexpected response format: {list(response_json.keys())}")
                        response.failure(f"Unexpected response format: {list(response_json.keys())}")
                        print(f"[FAILURE] Unexpected response format", flush=True)
                except:
                    self._capture_failure(response, "{{ api.method }}", "{{ api.endpoint }}", "Invalid JSON response or authentication failed")
                    response.failure(f"Invalid JSON response or authentication failed")
                    print(f"[FAILURE] Invalid JSON response", flush=True)
                {% else %}
                response.success()
                print(f"[SUCCESS] Request successful ({response.status_code})", flush=True)
                {% endif %}
            else:
                try:
                    response_body = response.json()
                except:
                    response_body = response.text[:200] if response.text else "No response body"
                self._capture_failure(response, "{{ api.method }}", "{{ api.endpoint }}", f"HTTP {response.status_code}")
                response.failure(f"Got status code {response.status_code}")
                print(f"[FAILURE] Got status code {response.status_code} - Query Params: {query_params} - Response: {response_body}", flush=True)

        {% elif api.method == "POST" %}
        print(f"[REQUEST] POST {{ api.endpoint }} - Auth: {self.auth_info} - Headers: {self._get_masked_headers()} - Payload: {payload}", flush=True)
        with self.client.post(
            "{{ api.endpoint }}",
            json=payload,
            headers=self.headers,
            {% if api.query_params %}params=query_params,{% endif %}
            catch_response=True,
            name="{{ api.method }} {{ api.endpoint }}"
        ) as response:
            print(f"[RESPONSE] Status Code: {response.status_code}", flush=True)
            if response.status_code in [200, 201, 204]:
                # For authentication/login endpoints, validate response content
                {% if 'login' in api.endpoint.lower() or 'auth' in api.endpoint.lower() or 'signin' in api.endpoint.lower() %}
                try:
                    response_json = response.json()
                    # Check for common error indicators
                    if 'error' in response_json or 'message' in response_json:
                        error_msg = response_json.get('error') or response_json.get('message', '')
                        if any(keyword in str(error_msg).lower() for keyword in ['invalid', 'incorrect', 'wrong', 'failed', 'denied', 'unauthorized']):
                            self._capture_failure(response, "{{ api.method }}", "{{ api.endpoint }}", f"Authentication failed: {error_msg}")
                            response.failure(f"Authentication failed: {error_msg}")
                            print(f"[FAILURE] Authentication failed: {error_msg}", flush=True)
                        else:
                            response.success()
                            print(f"[SUCCESS] Request successful ({response.status_code})", flush=True)
                    # Check for success indicators (token, user, access_token, etc.)
                    elif any(key in response_json for key in ['token', 'access_token', 'user', 'data', 'session']):
                        response.success()
                        print(f"[SUCCESS] Login successful ({response.status_code})", flush=True)
                    else:
                        # No clear success indicator found
                        response.failure(f"Unexpected response format: {list(response_json.keys())}")
                        print(f"[FAILURE] Unexpected response format", flush=True)
                except:
                    # If response is not JSON or parsing fails, mark as failure
                    response.failure(f"Invalid JSON response or authentication failed")
                    print(f"[FAILURE] Invalid JSON response", flush=True)
                {% else %}
                # Non-auth endpoints: status code is sufficient
                response.success()
                print(f"[SUCCESS] Request successful ({response.status_code})", flush=True)
                {% endif %}
            else:
                try:
                    response_body = response.json()
                except:
                    response_body = response.text[:200] if response.text else "No response body"
                self._capture_failure(response, "{{ api.method }}", "{{ api.endpoint }}", f"HTTP {response.status_code}")
                response.failure(f"Got status code {response.status_code}")
                print(f"[FAILURE] Got status code {response.status_code} - Payload: {payload} - Response: {response_body}", flush=True)

        {% elif api.method == "PUT" %}
        print(f"[REQUEST] PUT {{ api.endpoint }} - Auth: {self.auth_info} - Headers: {self._get_masked_headers()} - Payload: {payload}", flush=True)
        with self.client.put(
            "{{ api.endpoint }}",
            json=payload,
            headers=self.headers,
            {% if api.query_params %}params=query_params,{% endif %}
            catch_response=True,
            name="{{ api.method }} {{ api.endpoint }}"
        ) as response:
            if response.status_code in [200, 201, 204]:
                response.success()
                print(f"[SUCCESS] Request successful ({response.status_code})", flush=True)
            else:
                try:
                    response_body = response.json()
                except:
                    response_body = response.text[:200] if response.text else "No response body"
                self._capture_failure(response, "{{ api.method }}", "{{ api.endpoint }}", f"HTTP {response.status_code}")
                response.failure(f"Got status code {response.status_code}")
                print(f"[FAILURE] Got status code {response.status_code} - Payload: {payload} - Response: {response_body}", flush=True)

        {% elif api.method == "PATCH" %}
        print(f"[REQUEST] PATCH {{ api.endpoint }} - Auth: {self.auth_info} - Headers: {self._get_masked_headers()} - Payload: {payload}", flush=True)
        with self.client.patch(
            "{{ api.endpoint }}",
            json=payload,
            headers=self.headers,
            {% if api.query_params %}params=query_params,{% endif %}
            catch_response=True,
            name="{{ api.method }} {{ api.endpoint }}"
        ) as response:
            if response.status_code in [200, 201, 204]:
                response.success()
                print(f"[SUCCESS] Request successful ({response.status_code})", flush=True)
            else:
                try:
                    response_body = response.json()
                except:
                    response_body = response.text[:200] if response.text else "No response body"
                self._capture_failure(response, "{{ api.method }}", "{{ api.endpoint }}", f"HTTP {response.status_code}")
                response.failure(f"Got status code {response.status_code}")
                print(f"[FAILURE] Got status code {response.status_code} - Payload: {payload} - Response: {response_body}", flush=True)

        {% elif api.method == "DELETE" %}
        {% if api.query_params %}
        print(f"[REQUEST] DELETE {{ api.endpoint }} - Auth: {self.auth_info} - Headers: {self._get_masked_headers()} - Query Params: {query_params}", flush=True)
        {% else %}
        print(f"[REQUEST] DELETE {{ api.endpoint }} - Auth: {self.auth_info} - Headers: {self._get_masked_headers()}", flush=True)
        {% endif %}
        with self.client.delete(
            "{{ api.endpoint }}",
            headers=self.headers,
            {% if api.query_params %}params=query_params,{% endif %}
            catch_response=True,
            name="{{ api.method }} {{ api.endpoint }}"
        ) as response:
            if response.status_code in [200, 201, 204]:
                response.success()
                print(f"[SUCCESS] Request successful ({response.status_code})", flush=True)
            else:
                try:
                    response_body = response.json()
                except:
                    response_body = response.text[:200] if response.text else "No response body"
                self._capture_failure(response, "{{ api.method }}", "{{ api.endpoint }}", f"HTTP {response.status_code}")
                response.failure(f"Got status code {response.status_code}")
                {% if api.query_params %}
                print(f"[FAILURE] Got status code {response.status_code} - Query Params: {query_params} - Response: {response_body}", flush=True)
                {% else %}
                print(f"[FAILURE] Got status code {response.status_code} - Response: {response_body}", flush=True)
                {% endif %}
        {% endif %}
"""

    # Template for multiple API tests
    MULTI_API_TEMPLATE = """from locust import HttpUser, task, between
import json
import random

class MultiAPIUser(HttpUser):
    \"\"\"Load test for multiple APIs\"\"\"

    host = "{{ base_url }}"
    wait_time = between(1, 3)

    def on_start(self):
        \"\"\"Initialize headers and authentication.\"\"\"
        self.headers = {}
        {% for api in apis %}
        # Headers for {{ api.name }}
        self.headers_{{ loop.index }} = {{ api.headers }}
        {% if api.auth_config.auth_type.value == "bearer" and api.auth_config.token %}
        self.headers_{{ loop.index }}["Authorization"] = "Bearer {{ api.auth_config.token }}"
        {% elif api.auth_config.auth_type.value == "api_key" and api.auth_config.api_key_name and api.auth_config.api_key_value %}
        self.headers_{{ loop.index }}["{{ api.auth_config.api_key_name }}"] = "{{ api.auth_config.api_key_value }}"
        {% elif api.auth_config.auth_type.value == "basic" and api.auth_config.username and api.auth_config.password %}
        import base64
        credentials = base64.b64encode(b"{{ api.auth_config.username }}:{{ api.auth_config.password }}").decode("utf-8")
        self.headers_{{ loop.index }}["Authorization"] = f"Basic {credentials}"
        {% endif %}
        {% endfor %}

    {% for api in apis %}
    @task({{ api.weight or 1 }})
    def task_{{ loop.index }}_{{ api.name | replace(' ', '_') | replace('-', '_') | lower }}(self):
        \"\"\"{{ api.description or api.name }}\"\"\"

        {% if api.method == "GET" %}
        with self.client.get(
            "{{ api.endpoint }}",
            headers=self.headers_{{ loop.index }},
            {% if api.query_params %}params={{ api.query_params }},{% endif %}
            catch_response=True,
            name="{{ api.method }} {{ api.endpoint }}"
        ) as response:
            if response.status_code in [200, 201, 204]:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")

        {% elif api.method in ["POST", "PUT", "PATCH"] %}
        with self.client.{{ api.method.lower() }}(
            "{{ api.endpoint }}",
            json={{ api.payload or {} }},
            headers=self.headers_{{ loop.index }},
            {% if api.query_params %}params={{ api.query_params }},{% endif %}
            catch_response=True,
            name="{{ api.method }} {{ api.endpoint }}"
        ) as response:
            if response.status_code in [200, 201, 204]:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")

        {% elif api.method == "DELETE" %}
        with self.client.delete(
            "{{ api.endpoint }}",
            headers=self.headers_{{ loop.index }},
            {% if api.query_params %}params={{ api.query_params }},{% endif %}
            catch_response=True,
            name="{{ api.method }} {{ api.endpoint }}"
        ) as response:
            if response.status_code in [200, 201, 204]:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")
        {% endif %}

    {% endfor %}
"""

    def generate_single_api(self, api: APIConfig, output_path: str) -> str:
        """
        Generate Locustfile for a single API endpoint.

        Args:
            api: API configuration
            output_path: Path to save the generated Locustfile

        Returns:
            Path to generated file
        """
        template = Template(self.SINGLE_API_TEMPLATE)

        # Prepare template variables
        task_name = self._sanitize_task_name(api.name)
        headers = json.dumps(api.headers)

        # Extract test data
        test_data = api.test_data if api.test_data else None
        data_mode = api.data_mode or "round_robin"

        # Think-time values
        think_time_min = api.think_time_min if api.think_time_min is not None else 1.0
        think_time_max = api.think_time_max if api.think_time_max is not None else 3.0

        # Process payload and query params for variable substitution
        dynamic_payload = None
        dynamic_query_params = None

        if test_data:
            # Check if payload/query_params contain {{variable}} placeholders
            if api.payload and self._has_variables(api.payload):
                dynamic_payload = self._substitute_variables(api.payload)
            if api.query_params and self._has_variables(api.query_params):
                dynamic_query_params = self._substitute_variables(api.query_params)

        # Convert JSON booleans to Python booleans
        payload = self._json_to_python(api.payload) if api.payload else "None"
        query_params = self._json_to_python(api.query_params) if api.query_params else "None"

        # Extract test_id from output_path (e.g., "test_1234567890_abcdef.py" -> "test_1234567890_abcdef")
        test_id = Path(output_path).stem

        # Render template
        content = template.render(
            api=api,
            task_name=task_name,
            headers=headers,
            payload=payload,
            query_params=query_params,
            test_data=json.dumps(test_data) if test_data else None,
            data_mode=data_mode,
            think_time_min=think_time_min,
            think_time_max=think_time_max,
            dynamic_payload=dynamic_payload,
            dynamic_query_params=dynamic_query_params,
            test_id=test_id
        )

        # Write to file
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(content)

        return str(output_file)

    def generate_multi_api(self, apis: List[APIConfig], output_path: str) -> str:
        """
        Generate Locustfile for multiple API endpoints.

        Args:
            apis: List of API configurations
            output_path: Path to save the generated Locustfile

        Returns:
            Path to generated file
        """
        if not apis:
            raise ValueError("No APIs provided")

        template = Template(self.MULTI_API_TEMPLATE)

        # Use first API's base_url (assuming all from same host)
        base_url = apis[0].base_url

        # Render template
        content = template.render(
            base_url=base_url,
            apis=apis
        )

        # Write to file
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(content)

        return str(output_file)

    def _json_to_python(self, obj: dict) -> str:
        """Convert JSON object to Python dict string with proper boolean values."""
        return json.dumps(obj).replace('true', 'True').replace('false', 'False').replace('null', 'None')

    def _sanitize_task_name(self, name: str) -> str:
        """Convert API name to valid Python function name."""
        # Replace spaces and special characters with underscores
        sanitized = name.lower()
        sanitized = ''.join(c if c.isalnum() else '_' for c in sanitized)
        # Remove leading digits
        if sanitized and sanitized[0].isdigit():
            sanitized = 'api_' + sanitized
        # Ensure not empty
        if not sanitized:
            sanitized = 'test_api'
        return sanitized

    def _has_variables(self, obj: Any) -> bool:
        """Check if object contains {{variable}} placeholders."""
        obj_str = json.dumps(obj) if isinstance(obj, (dict, list)) else str(obj)
        return '{{' in obj_str and '}}' in obj_str

    def _substitute_variables(self, obj: Any) -> str:
        """
        Replace {{variable}} placeholders with runtime lookups from self.user_data.

        Args:
            obj: The payload or query_params object

        Returns:
            Python code string that will evaluate to the object with variables substituted
        """
        def replace_in_string(s: str) -> str:
            """Replace {{var}} with self.user_data.get('var', '')."""
            pattern = r'\{\{(\w+)\}\}'

            def replace_func(match):
                var_name = match.group(1)
                return f"{{self.user_data.get('{var_name}', '')}}"

            return re.sub(pattern, replace_func, s)

        def process_value(value: Any) -> str:
            """Process a value recursively."""
            if isinstance(value, str):
                if '{{' in value and '}}' in value:
                    # String contains variables - return f-string
                    replaced = replace_in_string(value)
                    return f'f"{replaced}"'
                else:
                    return repr(value)
            elif isinstance(value, dict):
                # Process dict recursively
                items = []
                for k, v in value.items():
                    key_str = repr(k)
                    val_str = process_value(v)
                    items.append(f"{key_str}: {val_str}")
                return "{" + ", ".join(items) + "}"
            elif isinstance(value, list):
                # Process list recursively
                items = [process_value(item) for item in value]
                return "[" + ", ".join(items) + "]"
            else:
                # Numbers, booleans, None
                return repr(value)

        return process_value(obj)

    def validate_locustfile(self, file_path: str) -> bool:
        """
        Validate that generated Locustfile is syntactically correct.

        Args:
            file_path: Path to Locustfile

        Returns:
            True if valid, False otherwise
        """
        try:
            with open(file_path, 'r') as f:
                code = f.read()
            compile(code, file_path, 'exec')
            return True
        except SyntaxError as e:
            print(f"Syntax error in generated Locustfile: {e}")
            return False
        except Exception as e:
            print(f"Error validating Locustfile: {e}")
            return False
