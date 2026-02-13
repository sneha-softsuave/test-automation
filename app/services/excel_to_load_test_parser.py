"""AI-powered Excel parser for load test API configurations."""

import pandas as pd
import json
import re
from typing import List, Dict, Any, Optional
from pathlib import Path

from app.agents.base_agent import BaseAgent, LLMProvider
from app.models.load_test_models import APIConfig, AuthConfig, AuthType
from app.core.config import settings


class ExcelLoadTestParser(BaseAgent):
    """Parse Excel files containing API endpoint configurations using AI."""

    def __init__(self):
        """Initialize parser with Groq LLM for fast and cost-effective parsing."""
        super().__init__(
            provider=LLMProvider.GROQ,
            groq_api_key=settings.GROQ_API_KEY,
            groq_model=settings.GROQ_MODEL
        )

    def execute(self, excel_path: str) -> List[APIConfig]:
        """
        Parse Excel file and extract API configurations.

        Args:
            excel_path: Path to Excel file

        Returns:
            List of APIConfig objects
        """
        # Read Excel file
        df = self._read_excel(excel_path)

        if df.empty:
            raise ValueError("Excel file is empty")

        # Try AI-powered parsing first (optional, requires API key)
        try:
            # Check if any API keys are configured
            from app.core.config import settings
            has_api_key = bool(settings.OPENAI_API_KEY or settings.GROQ_API_KEY or settings.ANTHROPIC_API_KEY)

            if has_api_key:
                print("🤖 Attempting AI-powered parsing...")
                api_configs = self._parse_with_ai(df)
                if api_configs:
                    print("✅ AI parsing successful!")
                    return api_configs
            else:
                print("ℹ️  No AI API keys configured. Using standard parsing method.")
        except Exception as e:
            print(f"⚠️  AI parsing failed: {str(e)[:100]}")
            print("✓ Falling back to reliable heuristic parsing...")

        # Fallback to heuristic parsing (always works)
        print("📊 Using heuristic parsing...")
        result = self._parse_heuristic(df)
        print(f"✅ Successfully parsed {len(result)} API configuration(s)")
        return result

    def _read_excel(self, excel_path: str) -> pd.DataFrame:
        """Read Excel file into DataFrame."""
        try:
            df = pd.read_excel(excel_path, engine='openpyxl')
            # Remove completely empty rows
            df = df.dropna(how='all')
            return df
        except Exception as e:
            raise ValueError(f"Failed to read Excel file: {e}")

    def _parse_with_ai(self, df: pd.DataFrame) -> List[APIConfig]:
        """Parse DataFrame using AI to handle flexible column naming."""

        # Convert DataFrame to readable format for LLM
        excel_data = self._df_to_text(df)

        # Create structured prompt
        prompt = self._create_parsing_prompt(excel_data)

        # Call LLM
        response = self.call_llm(prompt)

        # LOG RAW AI RESPONSE
        print("\n" + "="*80)
        print("🤖 RAW AI RESPONSE (BEFORE PARSING):")
        print("="*80)
        print(response)
        print("="*80)
        print(f"Response length: {len(response)} characters")
        print("="*80 + "\n")

        # Extract JSON from response
        api_configs = self._extract_json_from_response(response)

        # Convert to APIConfig objects
        return [self._dict_to_api_config(config) for config in api_configs]

    def _df_to_text(self, df: pd.DataFrame) -> str:
        """Convert DataFrame to text representation for LLM."""
        # Get column names
        columns = df.columns.tolist()

        # Get first few rows as examples
        sample_rows = df.head(10).to_dict('records')

        text = f"Columns: {columns}\n\n"
        text += "Sample Data:\n"
        for i, row in enumerate(sample_rows, 1):
            text += f"Row {i}: {row}\n"

        return text

    def _create_parsing_prompt(self, excel_data: str) -> str:
        """Create prompt for LLM to parse Excel data."""
        return f"""You are parsing an Excel file containing API endpoint configurations for load testing.

The Excel file may have flexible column naming. Your task is to:
1. Identify which columns map to which API configuration fields
2. Parse JSON strings from cells (headers, payload, query parameters)
3. Extract authentication configuration
4. Return a valid JSON array of API configurations

Expected fields (columns may vary):
- name: API Name, Name, Test Name, API
- base_url: Base URL, Host, API Host, Server, URL
- endpoint: Endpoint, Path, API Path, Route, API Endpoint
- method: Method, HTTP Method, Request Method, Verb
- headers: Headers, Request Headers (JSON string)
- payload: Payload, Body, Request Body, Data (JSON string)
- query_params: Query Params, Query Parameters, URL Params, Parameters (JSON string)
- auth_type: Auth Type, Authentication, Auth Method (bearer, basic, api_key, none)
- auth_token: Auth Token, Token, API Key, Bearer Token, Authorization
- users: Users, Number of Users, Concurrent Users, User Count (integer)
- spawn_rate: Spawn Rate, Rate, Users Per Second, Spawn (number)
- run_time: Run Time, Duration, Test Duration, Time (e.g., "5m", "1h", "30s")
- test_data: Test Data, User Data, Credentials, Test Dataset (JSON array)
- data_mode: Data Mode, Cycling Mode, Mode (sequential, random, round_robin)
- think_time_min: Think Time Min, Min Wait, Wait Time Min (float in seconds)
- think_time_max: Think Time Max, Max Wait, Wait Time Max (float in seconds)
- user_journey: User Journey, Journey, Flow, Sequence (comma-separated API names)

Excel Data:
{excel_data}

CRITICAL INSTRUCTION - READ CAREFULLY:
You must respond with ONLY raw JSON. Do NOT write Python code. Do NOT write explanations.
Do NOT use markdown formatting like ```json or ```python.
Your ENTIRE response must be a valid JSON array starting with '[' and ending with ']'.

Return a JSON array with this exact structure:
[
  {{
    "name": "API name",
    "base_url": "https://api.example.com",
    "endpoint": "/api/v1/users",
    "method": "GET",
    "headers": {{"Content-Type": "application/json"}},
    "payload": {{"key": "value"}},
    "query_params": {{"page": 1}},
    "auth_config": {{
      "auth_type": "bearer",
      "token": "eyJhbGc..."
    }},
    "description": "API description",
    "users": 10,
    "spawn_rate": 2,
    "run_time": "5m",
    "test_data": [{{"username": "user1", "password": "pass1"}}, {{"username": "user2", "password": "pass2"}}],
    "data_mode": "round_robin",
    "think_time_min": 1.0,
    "think_time_max": 3.0,
    "user_journey": "Login API,Browse API,Checkout API"
  }}
]

Rules:
1. method should be uppercase (GET, POST, PUT, DELETE, PATCH)
2. If headers/payload/query_params are strings, parse them as JSON
3. Set default headers if missing: {{"Content-Type": "application/json"}} for POST/PUT/PATCH
4. Ensure base_url has protocol (https://)
5. auth_type must be one of: bearer, basic, api_key, none
6. If no auth info found, set auth_type to "none"
7. Handle missing/optional fields gracefully
8. If users/spawn_rate/run_time are present, include them; otherwise omit them (don't set to null)
9. users should be integer, spawn_rate should be number, run_time should be string like "5m"
10. If run_time is just a number (e.g., "5", "10"), append "m" to make it "5m", "10m"
11. test_data should be parsed as JSON array if present (e.g., [{{"user":"u1"}}, {{"user":"u2"}}])
12. data_mode should be one of: sequential, random, round_robin (default: round_robin)
13. think_time_min and think_time_max should be floats (default: 1.0 and 3.0)
14. user_journey should be comma-separated string of API names if present
"""

    def _extract_json_from_response(self, response: str) -> List[Dict[str, Any]]:
        """Extract JSON array from LLM response with better error handling."""
        if not response or len(response.strip()) < 2:
            raise ValueError("LLM returned empty response (possible API key issue or rate limit)")

        # Try to find JSON array in response
        json_match = re.search(r'\[.*\]', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            try:
                result = json.loads(json_str)
                if not isinstance(result, list):
                    raise ValueError(f"Expected JSON array, got {type(result)}")
                if len(result) == 0:
                    raise ValueError("LLM returned empty array")
                return result
            except json.JSONDecodeError as e:
                # Show first 200 chars of what LLM returned for debugging
                preview = response[:200] + "..." if len(response) > 200 else response
                raise ValueError(
                    f"Failed to parse JSON from LLM response. "
                    f"Error: {e}. "
                    f"Response preview: {preview}"
                )

        # Show what we got if no JSON found
        preview = response[:200] + "..." if len(response) > 200 else response
        raise ValueError(
            f"No JSON array found in LLM response. "
            f"This usually means: API key missing/invalid, rate limit hit, or LLM service down. "
            f"Response preview: {preview}"
        )

    def _dict_to_api_config(self, config_dict: Dict[str, Any]) -> APIConfig:
        """Convert dictionary to APIConfig object."""

        # Parse auth config
        auth_data = config_dict.get('auth_config', {})
        auth_type_str = auth_data.get('auth_type', 'none').lower()

        # Map auth type string to enum
        auth_type_mapping = {
            'bearer': AuthType.BEARER,
            'basic': AuthType.BASIC,
            'api_key': AuthType.API_KEY,
            'none': AuthType.NONE
        }
        auth_type = auth_type_mapping.get(auth_type_str, AuthType.NONE)

        auth_config = AuthConfig(
            auth_type=auth_type,
            token=auth_data.get('token'),
            username=auth_data.get('username'),
            password=auth_data.get('password'),
            api_key_name=auth_data.get('api_key_name'),
            api_key_value=auth_data.get('api_key_value')
        )

        # Ensure base_url has protocol
        base_url = config_dict.get('base_url', '')
        if base_url and not base_url.startswith(('http://', 'https://')):
            base_url = f'https://{base_url}'

        # Ensure method is uppercase
        method = config_dict.get('method', 'GET').upper()

        # Process run_time: append 'm' if just a number
        run_time = config_dict.get('run_time')
        if run_time is not None:
            run_time = str(run_time).strip()
            # If it's just a number without unit, append 'm' (minutes)
            if run_time and run_time.replace('.', '').isdigit():
                run_time = f"{run_time}m"

        # Get test_data and validate it's a list
        test_data = config_dict.get('test_data')
        if test_data is not None and not isinstance(test_data, list):
            test_data = [test_data]

        # Get data_mode with validation
        data_mode = config_dict.get('data_mode', 'round_robin')
        if data_mode and isinstance(data_mode, str):
            data_mode = data_mode.lower()
            if data_mode not in ['sequential', 'random', 'round_robin']:
                data_mode = 'round_robin'

        # Get think-time values
        think_time_min = config_dict.get('think_time_min', 1.0)
        think_time_max = config_dict.get('think_time_max', 3.0)

        try:
            think_time_min = float(think_time_min)
        except (ValueError, TypeError):
            think_time_min = 1.0

        try:
            think_time_max = float(think_time_max)
        except (ValueError, TypeError):
            think_time_max = 3.0

        # Get user_journey
        user_journey = config_dict.get('user_journey')
        if user_journey and isinstance(user_journey, str):
            user_journey = user_journey.strip()

        return APIConfig(
            name=config_dict.get('name', 'Unnamed API'),
            base_url=base_url,
            endpoint=config_dict.get('endpoint', '/'),
            method=method,
            headers=config_dict.get('headers', {}),
            payload=config_dict.get('payload'),
            query_params=config_dict.get('query_params'),
            auth_config=auth_config,
            description=config_dict.get('description'),
            users=config_dict.get('users'),
            spawn_rate=config_dict.get('spawn_rate'),
            run_time=run_time,
            test_data=test_data,
            data_mode=data_mode,
            think_time_min=think_time_min,
            think_time_max=think_time_max,
            user_journey=user_journey
        )

    def _parse_heuristic(self, df: pd.DataFrame) -> List[APIConfig]:
        """
        Fallback heuristic parsing without AI.
        Maps columns based on common naming patterns.
        """
        api_configs = []

        # Column mapping (case-insensitive)
        column_mapping = self._create_column_mapping(df.columns)

        for _, row in df.iterrows():
            try:
                config = self._parse_row_heuristic(row, column_mapping)
                if config:
                    api_configs.append(config)
            except Exception as e:
                print(f"Failed to parse row: {e}")
                continue

        return api_configs

    def _create_column_mapping(self, columns: List[str]) -> Dict[str, str]:
        """Create mapping of standardized field names to actual column names."""
        mapping = {}
        columns_lower = {col.lower(): col for col in columns}

        # Mapping patterns
        patterns = {
            'name': ['name', 'api name', 'test name', 'api', 'test'],
            'base_url': ['base url', 'host', 'api host', 'server', 'url', 'base_url'],
            'endpoint': ['endpoint', 'path', 'api path', 'route', 'api endpoint'],
            'method': ['method', 'http method', 'request method', 'verb'],
            'headers': ['headers', 'request headers', 'header'],
            'payload': ['payload', 'body', 'request body', 'data'],
            'query_params': ['query params', 'query parameters', 'url params', 'parameters', 'query'],
            'auth_type': ['auth type', 'authentication', 'auth method', 'auth'],
            'auth_token': ['auth token', 'token', 'api key', 'bearer token', 'authorization'],
            'description': ['description', 'desc', 'notes', 'comment'],
            'users': ['users', 'number of users', 'concurrent users', 'user count', 'num users'],
            'spawn_rate': ['spawn rate', 'rate', 'users per second', 'spawn', 'spawn_rate'],
            'run_time': ['run time', 'duration', 'test duration', 'time', 'run_time'],
            'test_data': ['test data', 'test_data', 'data', 'user data', 'credentials', 'test dataset'],
            'data_mode': ['data mode', 'data_mode', 'cycling mode', 'mode'],
            'think_time_min': ['think time min', 'think_time_min', 'wait time min', 'min wait'],
            'think_time_max': ['think time max', 'think_time_max', 'wait time max', 'max wait'],
            'user_journey': ['user journey', 'user_journey', 'journey', 'flow', 'sequence']
        }

        for field, possible_names in patterns.items():
            for possible_name in possible_names:
                if possible_name in columns_lower:
                    mapping[field] = columns_lower[possible_name]
                    break

        return mapping

    def _parse_row_heuristic(self, row: pd.Series, column_mapping: Dict[str, str]) -> Optional[APIConfig]:
        """Parse a single row using heuristic mapping."""

        def get_value(field: str, default: Any = None) -> Any:
            """Get value from row using column mapping."""
            col = column_mapping.get(field)
            if col and col in row.index:
                value = row[col]
                # Handle NaN values
                if pd.isna(value):
                    return default
                return value
            return default

        # Skip if name or base_url is missing
        name = get_value('name')
        base_url = get_value('base_url')

        if not name or not base_url:
            return None

        # Parse JSON fields
        def parse_json_field(field: str, default: Any = None) -> Any:
            """Parse JSON string from field."""
            value = get_value(field)
            if not value:
                return default

            if isinstance(value, str):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    # Try to parse as dict-like string
                    try:
                        return eval(value)
                    except:
                        return default
            return value

        headers = parse_json_field('headers', {})
        payload = parse_json_field('payload')
        query_params = parse_json_field('query_params')

        # Parse test_data (should be JSON array)
        test_data = parse_json_field('test_data')
        if test_data is not None:
            # Ensure it's a list
            if not isinstance(test_data, list):
                test_data = [test_data]  # Wrap single object in array

        # Parse auth
        auth_type_str = get_value('auth_type', 'none')
        if isinstance(auth_type_str, str):
            auth_type_str = auth_type_str.lower()
        else:
            auth_type_str = 'none'

        auth_type_mapping = {
            'bearer': AuthType.BEARER,
            'basic': AuthType.BASIC,
            'api_key': AuthType.API_KEY,
            'none': AuthType.NONE
        }
        auth_type = auth_type_mapping.get(auth_type_str, AuthType.NONE)

        auth_config = AuthConfig(
            auth_type=auth_type,
            token=get_value('auth_token')
        )

        # Ensure base_url has protocol
        if not base_url.startswith(('http://', 'https://')):
            base_url = f'https://{base_url}'

        # Get method
        method = get_value('method', 'GET')
        if isinstance(method, str):
            method = method.upper()
        else:
            method = 'GET'

        # Add default Content-Type if missing
        if method in ['POST', 'PUT', 'PATCH'] and 'Content-Type' not in headers:
            headers['Content-Type'] = 'application/json'

        # Get load test configuration (users, spawn_rate, run_time)
        users = get_value('users')
        if users is not None:
            try:
                users = int(users)
            except (ValueError, TypeError):
                users = None

        spawn_rate = get_value('spawn_rate')
        if spawn_rate is not None:
            try:
                spawn_rate = float(spawn_rate)
            except (ValueError, TypeError):
                spawn_rate = None

        run_time = get_value('run_time')
        if run_time is not None:
            run_time = str(run_time).strip()
            # If it's just a number without unit, append 'm' (minutes)
            if run_time and run_time.replace('.', '').isdigit():
                run_time = f"{run_time}m"

        # Get data_mode
        data_mode = get_value('data_mode', 'round_robin')
        if data_mode:
            data_mode = str(data_mode).lower()
            if data_mode not in ['sequential', 'random', 'round_robin']:
                data_mode = 'round_robin'

        # Get think-time values
        think_time_min = get_value('think_time_min')
        if think_time_min is not None:
            try:
                think_time_min = float(think_time_min)
            except (ValueError, TypeError):
                think_time_min = 1.0
        else:
            think_time_min = 1.0

        think_time_max = get_value('think_time_max')
        if think_time_max is not None:
            try:
                think_time_max = float(think_time_max)
            except (ValueError, TypeError):
                think_time_max = 3.0
        else:
            think_time_max = 3.0

        # Get user_journey
        user_journey = get_value('user_journey')
        if user_journey:
            user_journey = str(user_journey).strip()

        return APIConfig(
            name=str(name),
            base_url=base_url,
            endpoint=get_value('endpoint', '/'),
            method=method,
            headers=headers,
            payload=payload,
            query_params=query_params,
            auth_config=auth_config,
            description=get_value('description'),
            users=users,
            spawn_rate=spawn_rate,
            run_time=run_time,
            test_data=test_data,
            data_mode=data_mode,
            think_time_min=think_time_min,
            think_time_max=think_time_max,
            user_journey=user_journey
        )
