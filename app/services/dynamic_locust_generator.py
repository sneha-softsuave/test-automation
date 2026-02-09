"""Dynamic Locustfile generator for API load testing."""

from typing import List
from jinja2 import Template
from pathlib import Path
import json

from app.models.load_test_models import APIConfig, AuthType


class DynamicLocustfileGenerator:
    """Generate Locustfiles dynamically from API configurations."""

    # Jinja2 template for single API test
    SINGLE_API_TEMPLATE = """from locust import HttpUser, task, between
import json

class DynamicAPIUser(HttpUser):
    \"\"\"Load test for {{ api.name }}\"\"\"

    host = "{{ api.base_url }}"
    wait_time = between(1, 3)

    def on_start(self):
        \"\"\"Initialize headers and authentication.\"\"\"
        self.headers = {{ headers }}

        {% if api.auth_config.auth_type.value == "bearer" and api.auth_config.token %}
        # Bearer token authentication
        self.headers["Authorization"] = "Bearer {{ api.auth_config.token }}"
        {% elif api.auth_config.auth_type.value == "api_key" and api.auth_config.api_key_name and api.auth_config.api_key_value %}
        # API Key authentication
        self.headers["{{ api.auth_config.api_key_name }}"] = "{{ api.auth_config.api_key_value }}"
        {% elif api.auth_config.auth_type.value == "basic" and api.auth_config.username and api.auth_config.password %}
        # Basic authentication
        import base64
        credentials = base64.b64encode(b"{{ api.auth_config.username }}:{{ api.auth_config.password }}").decode("utf-8")
        self.headers["Authorization"] = f"Basic {credentials}"
        {% endif %}

    @task
    def {{ task_name }}(self):
        \"\"\"{{ api.description or api.name }}\"\"\"

        {% if api.method == "GET" %}
        with self.client.get(
            "{{ api.endpoint }}",
            headers=self.headers,
            {% if api.query_params %}params={{ query_params }},{% endif %}
            catch_response=True,
            name="{{ api.method }} {{ api.endpoint }}"
        ) as response:
            if response.status_code in [200, 201, 204]:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")

        {% elif api.method == "POST" %}
        with self.client.post(
            "{{ api.endpoint }}",
            json={{ payload }},
            headers=self.headers,
            {% if api.query_params %}params={{ query_params }},{% endif %}
            catch_response=True,
            name="{{ api.method }} {{ api.endpoint }}"
        ) as response:
            if response.status_code in [200, 201, 204]:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")

        {% elif api.method == "PUT" %}
        with self.client.put(
            "{{ api.endpoint }}",
            json={{ payload }},
            headers=self.headers,
            {% if api.query_params %}params={{ query_params }},{% endif %}
            catch_response=True,
            name="{{ api.method }} {{ api.endpoint }}"
        ) as response:
            if response.status_code in [200, 201, 204]:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")

        {% elif api.method == "PATCH" %}
        with self.client.patch(
            "{{ api.endpoint }}",
            json={{ payload }},
            headers=self.headers,
            {% if api.query_params %}params={{ query_params }},{% endif %}
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
            headers=self.headers,
            {% if api.query_params %}params={{ query_params }},{% endif %}
            catch_response=True,
            name="{{ api.method }} {{ api.endpoint }}"
        ) as response:
            if response.status_code in [200, 201, 204]:
                response.success()
            else:
                response.failure(f"Got status code {response.status_code}")
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
        # Convert JSON booleans to Python booleans
        payload = self._json_to_python(api.payload) if api.payload else "None"
        query_params = self._json_to_python(api.query_params) if api.query_params else "None"

        # Render template
        content = template.render(
            api=api,
            task_name=task_name,
            headers=headers,
            payload=payload,
            query_params=query_params
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
