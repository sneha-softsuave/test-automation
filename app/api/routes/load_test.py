"""API routes for load testing functionality."""

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, StreamingResponse
from sse_starlette.sse import EventSourceResponse
from typing import Dict, List, Any, Optional
from pathlib import Path
import uuid
import shutil
import asyncio
from datetime import datetime
import httpx
import logging

from app.models.load_test_models import (
    APIConfig,
    AuthType,
    LoadTestRequest,
    LoadTestStartResponse,
    ExcelUploadResponse,
    LoadTestMetrics,
    ValidationResult,
    MultiAPILoadTestRequest,
    SequentialLoadTestRequest,
    AIAnalysis
)
from app.services.excel_to_load_test_parser import ExcelLoadTestParser
from app.services.dynamic_locust_generator import DynamicLocustfileGenerator
from app.services.locust_manager import locust_manager
from app.services.sequential_test_manager import sequential_test_manager, parse_time_to_seconds
from app.services.load_test_report_generator import load_test_report_generator
from app.core.sse_manager import sse_manager
from app.agents.load_test.supervisor import LoadTestSupervisor
from app.agents.base_agent import LLMProvider
from app.core.config import settings

# Configure logger
logger = logging.getLogger(__name__)


def validate_provider_config(provider: LLMProvider) -> None:
    """
    Validate that provider has required API key configured.

    Args:
        provider: LLM provider to validate

    Raises:
        HTTPException: If provider's API key is not configured
    """
    validation_map = {
        LLMProvider.OPENAI: (settings.OPENAI_API_KEY, "OPENAI_API_KEY"),
        LLMProvider.GROQ: (settings.GROQ_API_KEY, "GROQ_API_KEY"),
        LLMProvider.ANTHROPIC: (settings.ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY"),
        LLMProvider.WAYMORE: (settings.WAYMORE_API_KEY, "WAYMORE_API_KEY"),
    }

    api_key, key_name = validation_map[provider]
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider.value}' selected but {key_name} is not configured in .env"
        )


# Don't include /api/v1 prefix here - it's already in main.py
router = APIRouter(prefix="/load-test", tags=["load-test"])

# In-memory storage for uploaded API configs
# In production, use database
# Using a more persistent approach - save to disk
import json

uploaded_configs: Dict[str, List[APIConfig]] = {}
active_tests: Dict[str, Dict] = {}

# In-memory cache for AI analysis results
# Key format: "{test_id}_{llm_provider}" -> AIAnalysis
ai_analysis_cache: Dict[str, AIAnalysis] = {}

def load_metrics_from_csv(test_id: str) -> Optional[Dict[str, Any]]:
    """
    Load metrics from Locust stats CSV files.

    Args:
        test_id: Test ID (e.g., test_1770976702_bd87f455)

    Returns:
        Dict with metrics or None if not found
    """
    # Extract the timestamp part from test_id (e.g., test_1770976702_bd87f455 -> 1770976702)
    import re
    timestamp_match = re.search(r'test_(\d+)_', test_id)
    if not timestamp_match:
        timestamp_match = re.search(r'(\d+)', test_id)

    if not timestamp_match:
        logger.warning(f"Could not extract timestamp from test_id: {test_id}")
        return None

    timestamp = timestamp_match.group(1)
    stats_file = RESULTS_DIR / f"stats_{timestamp}_stats.csv"

    if not stats_file.exists():
        logger.warning(f"Stats file not found: {stats_file}")
        return None

    try:
        import csv
        with open(stats_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            if not rows:
                return None

            # Get aggregated row (last row or row with Name='Aggregated')
            aggregated_row = None
            for row in rows:
                if row.get('Name') == 'Aggregated' or row.get('Type') == '':
                    aggregated_row = row
                    break

            if not aggregated_row:
                aggregated_row = rows[-1]  # Use last row as fallback

            # Parse metrics
            total_requests = int(aggregated_row.get('Request Count', 0))
            total_failures = int(aggregated_row.get('Failure Count', 0))
            avg_response_time = float(aggregated_row.get('Average Response Time', 0))
            min_response_time = float(aggregated_row.get('Min Response Time', 0))
            max_response_time = float(aggregated_row.get('Max Response Time', 0))
            median_response_time = float(aggregated_row.get('Median Response Time', 0))
            percentile_95 = float(aggregated_row.get('95%', 0))
            percentile_99 = float(aggregated_row.get('99%', 0))
            requests_per_second = float(aggregated_row.get('Requests/s', 0))
            failures_per_second = float(aggregated_row.get('Failures/s', 0))

            metrics = {
                'test_id': test_id,
                'status': 'completed',
                'current_users': 0,  # Not available in CSV
                'total_requests': total_requests,
                'total_failures': total_failures,
                'requests_per_second': requests_per_second,
                'failures_per_second': failures_per_second,
                'avg_response_time': avg_response_time,
                'min_response_time': min_response_time,
                'max_response_time': max_response_time,
                'median_response_time': median_response_time,
                'percentile_95': percentile_95,
                'percentile_99': percentile_99,
                'failure_rate': (total_failures / total_requests * 100) if total_requests > 0 else 0,
                'elapsed_time': 0.0,  # Not available in CSV
            }

            logger.info(f"   ✅ Loaded metrics from CSV: {total_requests} requests, {percentile_95:.0f}ms p95")
            return metrics

    except Exception as e:
        logger.error(f"Failed to parse stats CSV: {e}")
        import traceback
        traceback.print_exc()
        return None

def save_upload_config(upload_id: str, apis: List[APIConfig]):
    """Save uploaded config to disk for persistence."""
    config_file = UPLOAD_DIR / f"{upload_id}_config.json"
    data = {
        "upload_id": upload_id,
        "apis": [api.dict() for api in apis]
    }
    with open(config_file, 'w') as f:
        json.dump(data, f)

def load_upload_config(upload_id: str) -> List[APIConfig]:
    """Load uploaded config from disk."""
    config_file = UPLOAD_DIR / f"{upload_id}_config.json"
    if config_file.exists():
        with open(config_file, 'r') as f:
            data = json.load(f)
            return [APIConfig(**api) for api in data["apis"]]
    return None

# Directories
UPLOAD_DIR = Path("uploads/load_test_configs")
LOCUSTFILE_DIR = Path("generated_locustfiles")
RESULTS_DIR = Path("load_test_results")

# Ensure directories exist
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
LOCUSTFILE_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload-excel", response_model=ExcelUploadResponse)
async def upload_excel(file: UploadFile = File(...)):
    """
    Upload Excel file containing API configurations.

    Returns:
        Parsed API configurations
    """
    logger.info("\n" + "="*80)
    logger.info("📤 API Call: POST /upload-excel")
    logger.info("="*80)
    logger.info(f"📁 File Name: {file.filename}")
    logger.info(f"📝 Content Type: {file.content_type}")

    # Validate file type
    if not file.filename.endswith(('.xlsx', '.xls')):
        logger.error(f"❌ Invalid file type: {file.filename}")
        raise HTTPException(status_code=400, detail="Only Excel files (.xlsx, .xls) are supported")

    # Generate upload ID
    upload_id = str(uuid.uuid4())
    logger.info(f"🆔 Upload ID: {upload_id}")

    # Save uploaded file
    file_path = UPLOAD_DIR / f"{upload_id}_{file.filename}"

    try:
        logger.info("💾 Saving file to disk...")
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"   ✓ Saved to: {file_path}")

        # Parse Excel file
        logger.info("📊 Parsing Excel file...")
        parser = ExcelLoadTestParser()
        api_configs = parser.execute(str(file_path))
        logger.info(f"   ✓ Found {len(api_configs)} API configuration(s)")

        for i, api in enumerate(api_configs, 1):
            logger.info(f"   • API {i}: {api.name} [{api.method} {api.endpoint}]")

        # Store in memory and persist to disk
        uploaded_configs[upload_id] = api_configs
        save_upload_config(upload_id, api_configs)
        logger.info("   ✓ Configuration saved")

        logger.info("✅ Upload successful")
        logger.info("="*80 + "\n")

        return ExcelUploadResponse(
            upload_id=upload_id,
            filename=file.filename,
            total_apis=len(api_configs),
            apis=api_configs,
            message=f"Successfully parsed {len(api_configs)} API configurations"
        )

    except Exception as e:
        # Clean up file on error
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=f"Failed to parse Excel file: {str(e)}")


@router.get("/uploaded-apis/{upload_id}", response_model=List[APIConfig])
async def get_uploaded_apis(upload_id: str):
    """Get parsed API configurations for an upload session."""
    # Try memory first
    if upload_id in uploaded_configs:
        return uploaded_configs[upload_id]

    # Try loading from disk
    apis = load_upload_config(upload_id)
    if apis:
        uploaded_configs[upload_id] = apis  # Cache in memory
        return apis

    raise HTTPException(status_code=404, detail="Upload session not found")


@router.delete("/clear-upload/{upload_id}")
async def clear_upload_session(upload_id: str):
    """
    Clear an upload session - removes from memory and deletes files from disk.

    Args:
        upload_id: Upload session ID to clear

    Returns:
        Success message
    """
    print(f"🗑️ Clearing upload session: {upload_id}", flush=True)

    # Remove from memory
    if upload_id in uploaded_configs:
        del uploaded_configs[upload_id]
        print(f"✅ Removed {upload_id} from memory", flush=True)

    # Delete files from disk
    try:
        # Delete config file
        config_file = UPLOAD_DIR / f"{upload_id}_config.json"
        if config_file.exists():
            config_file.unlink()
            print(f"✅ Deleted config file: {config_file.name}", flush=True)

        # Delete uploaded Excel file (find by upload_id prefix)
        for file_path in UPLOAD_DIR.glob(f"{upload_id}_*"):
            if file_path.is_file() and file_path.suffix in ['.xlsx', '.xls']:
                file_path.unlink()
                print(f"✅ Deleted Excel file: {file_path.name}", flush=True)

        return {
            "message": "Upload session cleared successfully",
            "upload_id": upload_id
        }
    except Exception as e:
        print(f"⚠️ Error deleting files for {upload_id}: {e}", flush=True)
        # Return success even if file deletion fails (memory is cleared)
        return {
            "message": "Upload session cleared from memory (some files may remain)",
            "upload_id": upload_id
        }


@router.post("/start-from-excel", response_model=LoadTestStartResponse)
async def start_load_test_from_excel(
    request: LoadTestRequest,
    background_tasks: BackgroundTasks
):
    """
    Start a load test for a selected API from uploaded Excel.

    Args:
        request: Load test configuration

    Returns:
        Test ID and details
    """
    logger.info("\n" + "="*80)
    logger.info("🚀 API Call: POST /start-from-excel")
    logger.info("="*80)
    logger.info(f"🎯 API: {request.selected_api_name}")
    logger.info(f"👥 Users: {request.config.users}")
    logger.info(f"⚡ Spawn Rate: {request.config.spawn_rate}/s")
    logger.info(f"⏱️  Duration: {request.config.run_time}")

    # Use selected_api from request if provided (user edited in UI), otherwise load from config
    if request.selected_api:
        selected_api = request.selected_api
        logger.info("✓ Using API configuration from request (with user edits)")
        logger.info(f"   Auth Type: {selected_api.auth_config.auth_type}")
    else:
        # Validate upload session exists (try memory first, then disk)
        if request.upload_id not in uploaded_configs:
            logger.info("📂 Loading configuration from disk...")
            apis = load_upload_config(request.upload_id)
            if not apis:
                logger.error(f"❌ Upload session not found: {request.upload_id}")
                raise HTTPException(status_code=404, detail="Upload session not found")
            uploaded_configs[request.upload_id] = apis
            logger.info("   ✓ Configuration loaded")
        else:
            apis = uploaded_configs[request.upload_id]
            logger.info("   ✓ Configuration found in memory")

        # Find selected API
        selected_api = next((api for api in apis if api.name == request.selected_api_name), None)

        if not selected_api:
            logger.error(f"❌ API not found: {request.selected_api_name}")
            raise HTTPException(status_code=404, detail=f"API '{request.selected_api_name}' not found")

    logger.info(f"✓ API found: {selected_api.method} {selected_api.endpoint}")
    logger.info(f"   Headers: {selected_api.headers}")
    logger.info(f"   Auth Type: {selected_api.auth_config.auth_type}")
    if selected_api.auth_config.auth_type == AuthType.BEARER:
        logger.info(f"   Bearer Token: {selected_api.auth_config.token[:10]}...***" if selected_api.auth_config.token else "   Bearer Token: None")
    elif selected_api.auth_config.auth_type == AuthType.API_KEY:
        logger.info(f"   API Key ({selected_api.auth_config.api_key_name}): {selected_api.auth_config.api_key_value[:10]}...***" if selected_api.auth_config.api_key_value else "   API Key: None")
    elif selected_api.auth_config.auth_type == AuthType.BASIC:
        logger.info(f"   Basic Auth: {selected_api.auth_config.username}:***")

    # Generate test ID
    test_id = f"test_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"
    logger.info(f"🆔 Test ID: {test_id}")

    # Generate Locustfile
    logger.info("📝 Generating Locustfile...")
    generator = DynamicLocustfileGenerator()
    locustfile_path = LOCUSTFILE_DIR / f"{test_id}.py"

    try:
        generator.generate_single_api(selected_api, str(locustfile_path))
        logger.info(f"   ✓ Locustfile generated: {locustfile_path.name}")

        # Validate generated file
        logger.info("🔍 Validating Locustfile...")
        if not generator.validate_locustfile(str(locustfile_path)):
            logger.error("❌ Generated Locustfile validation failed")
            raise HTTPException(status_code=500, detail="Generated Locustfile is invalid")
        logger.info("   ✓ Validation passed")

        # Start Locust test
        logger.info("🏃 Starting Locust test...")
        success = locust_manager.start_test(test_id, str(locustfile_path), request.config, request.session_id)

        if not success:
            logger.error("❌ Failed to start Locust process")
            raise HTTPException(status_code=500, detail="Failed to start Locust test")
        logger.info("   ✓ Locust process started")

        if not success:
            raise HTTPException(status_code=500, detail="Failed to start Locust test")

        # Store test metadata
        active_tests[test_id] = {
            "test_id": test_id,
            "api_name": selected_api.name,
            "api": selected_api,  # Store full API object for report generation
            "config": request.config,
            "session_id": request.session_id,
            "llm_provider": request.llm_provider or "groq",  # Store for AI insights generation
            "start_time": datetime.now(),
            "status": "running"
        }

        # Send SSE event
        await sse_manager.broadcast_to_session(
            request.session_id,
            "load_test_started",
            {
                "test_id": test_id,
                "api_name": selected_api.name,
                "config": request.config.dict()
            }
        )

        # Start background task to stream metrics
        background_tasks.add_task(stream_metrics_task, test_id, request.session_id)

        return LoadTestStartResponse(
            test_id=test_id,
            message=f"Load test started for {selected_api.name}",
            locustfile_path=str(locustfile_path),
            estimated_duration=request.config.run_time
        )

    except HTTPException:
        raise
    except Exception as e:
        # Clean up on error
        if locustfile_path.exists():
            locustfile_path.unlink()
        raise HTTPException(status_code=500, detail=f"Failed to start load test: {str(e)}")


@router.post("/test-multiple-apis", response_model=LoadTestStartResponse)
async def test_multiple_apis(
    request: MultiAPILoadTestRequest,
    background_tasks: BackgroundTasks
):
    """Test multiple APIs from Excel in a single load test session."""
    # Validate upload session exists (try memory first, then disk)
    if request.upload_id not in uploaded_configs:
        all_apis = load_upload_config(request.upload_id)
        if not all_apis:
            raise HTTPException(status_code=404, detail="Upload session not found")
        uploaded_configs[request.upload_id] = all_apis
    else:
        all_apis = uploaded_configs[request.upload_id]

    # Find selected APIs
    selected_apis = [api for api in all_apis if api.name in request.selected_api_names]

    if not selected_apis:
        raise HTTPException(status_code=404, detail="No matching APIs found")

    # Generate test ID
    test_id = f"test_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"

    # Generate Locustfile for multiple APIs
    generator = DynamicLocustfileGenerator()
    locustfile_path = LOCUSTFILE_DIR / f"{test_id}_multi.py"

    try:
        generator.generate_multi_api(selected_apis, str(locustfile_path))

        if not generator.validate_locustfile(str(locustfile_path)):
            raise HTTPException(status_code=500, detail="Generated Locustfile is invalid")

        # Start test
        success = locust_manager.start_test(test_id, str(locustfile_path), request.config, request.session_id)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to start Locust test")

        # Store metadata
        active_tests[test_id] = {
            "test_id": test_id,
            "api_names": request.selected_api_names,
            "config": request.config,
            "session_id": request.session_id,
            "start_time": datetime.now(),
            "status": "running"
        }

        # Send SSE event
        await sse_manager.broadcast_to_session(
            request.session_id,
            "load_test_started",
            {
                "test_id": test_id,
                "api_names": request.selected_api_names,
                "config": request.config.dict()
            }
        )

        background_tasks.add_task(stream_metrics_task, test_id, request.session_id)

        return LoadTestStartResponse(
            test_id=test_id,
            message=f"Load test started for {len(selected_apis)} APIs",
            locustfile_path=str(locustfile_path),
            estimated_duration=request.config.run_time
        )

    except HTTPException:
        raise
    except Exception as e:
        if locustfile_path.exists():
            locustfile_path.unlink()
        raise HTTPException(status_code=500, detail=f"Failed to start load test: {str(e)}")


@router.post("/stop/{test_id}")
async def stop_load_test(test_id: str):
    """Stop a running load test."""
    print(f"[STOP] Attempting to stop test: {test_id}")
    print(f"[STOP] Active tests: {list(active_tests.keys())}")
    print(f"[STOP] Active processes: {list(locust_manager.active_processes.keys())}")

    # Get session_id before checking active_tests
    session_id = None
    if test_id in active_tests:
        session_id = active_tests[test_id].get("session_id")
        active_tests[test_id]["status"] = "stopped"
        print(f"[STOP] Found test in active_tests, session_id: {session_id}")
    else:
        print(f"[STOP] Test {test_id} not in active_tests")

    # Try to stop the test even if not in active_tests
    # (in case server restarted but process is still running)
    success = locust_manager.stop_test(test_id)
    print(f"[STOP] locust_manager.stop_test result: {success}")

    # Also try to stop by finding the process directly
    if not success:
        import subprocess
        try:
            print(f"[STOP] Trying pkill for locustfile_{test_id}")
            # Find and kill any locust processes with this test_id
            result = subprocess.run(
                ["pkill", "-f", f"locustfile_{test_id}"],
                check=False,
                capture_output=True
            )
            print(f"[STOP] pkill result: returncode={result.returncode}, stdout={result.stdout}, stderr={result.stderr}")
            success = True
        except Exception as e:
            print(f"[STOP] Failed to pkill test {test_id}: {e}")

    if success or test_id not in active_tests:
        # Send SSE event if we have a session
        if session_id:
            await sse_manager.broadcast_to_session(
                session_id,
                "load_test_stopped",
                {"test_id": test_id}
            )
            print(f"[STOP] Sent SSE stop event to session {session_id}")

        print(f"[STOP] Successfully stopped test {test_id}")
        return {"message": "Load test stopped successfully", "test_id": test_id, "status": "stopped"}
    else:
        print(f"[STOP] Failed to stop test {test_id}")
        raise HTTPException(status_code=500, detail="Failed to stop load test")


@router.get("/results/{test_id}")
async def get_test_results(test_id: str):
    """Get results for a completed load test."""
    if test_id not in active_tests:
        raise HTTPException(status_code=404, detail="Test not found")

    # Get final metrics
    metrics = await locust_manager.get_metrics(test_id)

    return {
        "test_id": test_id,
        "test_info": active_tests[test_id],
        "metrics": metrics
    }


@router.post("/validate-config", response_model=ValidationResult)
async def validate_api_config(api: APIConfig):
    """
    Validate an API configuration by making a test request.

    Args:
        api: API configuration to validate

    Returns:
        Validation result with status and response time
    """
    warnings = []

    # Basic validations
    if not api.base_url:
        return ValidationResult(
            valid=False,
            error_message="Base URL is required"
        )

    if not api.endpoint:
        warnings.append("Endpoint is empty, using root path '/'")

    # Try to make a test request
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Build headers
            headers = api.headers.copy()

            # Add auth if configured
            if api.auth_config.auth_type.value == "bearer" and api.auth_config.token:
                headers["Authorization"] = f"Bearer {api.auth_config.token}"
            elif api.auth_config.auth_type.value == "api_key" and api.auth_config.api_key_name:
                headers[api.auth_config.api_key_name] = api.auth_config.api_key_value

            # Build full URL
            url = f"{api.base_url.rstrip('/')}{api.endpoint}"

            # Make request
            start_time = datetime.now()

            if api.method == "GET":
                response = await client.get(url, headers=headers, params=api.query_params)
            elif api.method == "POST":
                response = await client.post(url, json=api.payload, headers=headers, params=api.query_params)
            elif api.method == "PUT":
                response = await client.put(url, json=api.payload, headers=headers, params=api.query_params)
            elif api.method == "PATCH":
                response = await client.patch(url, json=api.payload, headers=headers, params=api.query_params)
            elif api.method == "DELETE":
                response = await client.delete(url, headers=headers, params=api.query_params)
            else:
                return ValidationResult(
                    valid=False,
                    error_message=f"Unsupported HTTP method: {api.method}"
                )

            response_time = (datetime.now() - start_time).total_seconds() * 1000

            # Check response
            if response.status_code >= 500:
                warnings.append(f"Server error: {response.status_code}")
            elif response.status_code >= 400:
                warnings.append(f"Client error: {response.status_code}")

            return ValidationResult(
                valid=True,
                status_code=response.status_code,
                response_time_ms=response_time,
                warnings=warnings
            )

    except httpx.TimeoutException:
        return ValidationResult(
            valid=False,
            error_message="Request timed out after 10 seconds",
            warnings=warnings
        )
    except Exception as e:
        return ValidationResult(
            valid=False,
            error_message=f"Request failed: {str(e)}",
            warnings=warnings
        )


@router.get("/templates")
async def get_api_templates():
    """Return sample API configuration templates."""
    templates = [
        {
            "name": "GET Request Example",
            "base_url": "https://jsonplaceholder.typicode.com",
            "endpoint": "/posts",
            "method": "GET",
            "headers": {"Content-Type": "application/json"},
            "description": "Simple GET request example"
        },
        {
            "name": "POST Request Example",
            "base_url": "https://jsonplaceholder.typicode.com",
            "endpoint": "/posts",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "payload": {"title": "foo", "body": "bar", "userId": 1},
            "description": "POST request with JSON body"
        },
        {
            "name": "Authenticated GET Example",
            "base_url": "https://api.example.com",
            "endpoint": "/api/v1/users",
            "method": "GET",
            "headers": {"Content-Type": "application/json"},
            "auth_config": {
                "auth_type": "bearer",
                "token": "your-token-here"
            },
            "description": "GET request with Bearer authentication"
        }
    ]

    return {"templates": templates}


async def generate_ai_insights_background(
    test_id: str,
    llm_provider: str,
    metrics: Any,
    config: Any,
    api: Any,
    regenerate_report: bool = True
):
    """
    Background task to generate AI insights after test completion.
    This runs asynchronously without blocking the main flow.
    """
    try:
        print(f"🤖 [BACKGROUND] Starting AI insights generation for {test_id}", flush=True)

        # Convert metrics to dict if needed
        metrics_dict = metrics.dict() if hasattr(metrics, 'dict') else metrics
        metrics_dict['test_id'] = test_id

        # Convert config to dict if needed
        config_dict = config.dict() if hasattr(config, 'dict') else config if isinstance(config, dict) else {}

        # Convert API to dict if needed
        api_dict = {}
        if api:
            if hasattr(api, 'dict'):
                api_dict = api.dict()
            elif isinstance(api, dict):
                api_dict = api
            else:
                api_dict = {
                    'endpoint': getattr(api, 'endpoint', '/api/endpoint'),
                    'method': getattr(api, 'method', 'GET'),
                    'api_type': 'unknown'
                }

        # Validate provider
        try:
            provider = LLMProvider(llm_provider.lower())
        except ValueError:
            provider = LLMProvider.GROQ

        # Check if provider has API key configured
        try:
            validate_provider_config(provider)
        except HTTPException:
            print(f"⚠️ [BACKGROUND] API key not configured for {provider.value}, skipping AI insights", flush=True)
            return

        # Initialize AnalyzerAgent
        from app.agents.load_test.sub_agents.analyzer_agent import AnalyzerAgent

        if provider == LLMProvider.GROQ:
            analyzer = AnalyzerAgent(
                provider=provider,
                groq_api_key=settings.GROQ_API_KEY,
                groq_model=settings.GROQ_MODEL
            )
        elif provider == LLMProvider.OPENAI:
            analyzer = AnalyzerAgent(
                provider=provider,
                openai_api_key=settings.OPENAI_API_KEY,
                openai_model=settings.OPENAI_MODEL
            )
        elif provider == LLMProvider.WAYMORE:
            analyzer = AnalyzerAgent(
                provider=provider,
                waymore_api_key=settings.WAYMORE_API_KEY,
                waymore_model=settings.WAYMORE_MODEL
            )
        else:  # ANTHROPIC
            analyzer = AnalyzerAgent(
                provider=provider,
                anthropic_api_key=settings.ANTHROPIC_API_KEY,
                anthropic_model=settings.ANTHROPIC_MODEL
            )

        # Generate analysis
        analysis = analyzer.analyze_and_suggest(
            metrics=metrics_dict,
            test_config=config_dict,
            api_details=api_dict
        )

        # Cache the result
        cache_key = f"{test_id}_{llm_provider}"
        ai_analysis_cache[cache_key] = analysis

        print(f"✅ [BACKGROUND] AI insights generated and cached for {test_id} (score: {analysis.performance_score}/100)", flush=True)

        # Regenerate report with AI insights
        if regenerate_report:
            print(f"📊 [BACKGROUND] Regenerating report with AI insights...", flush=True)

            # Check if this is a sequential test or single test
            if test_id.startswith('seq_'):
                # Sequential test - get api_results from sequential_test_manager
                from app.services.sequential_test_manager import sequential_test_manager
                test_info = sequential_test_manager.get_sequential_test_status(test_id)
                if test_info and test_info.get('api_results'):
                    duration = (datetime.now() - test_info['start_time']).total_seconds()
                    report_filename = load_test_report_generator.generate_sequential_report(
                        sequential_test_id=test_id,
                        api_results=test_info['api_results'],
                        total_duration=duration,
                        llm_provider=llm_provider
                    )
                    print(f"✅ [BACKGROUND] Sequential report regenerated with AI insights: {report_filename}", flush=True)
            else:
                # Single test - get data from active_tests
                if test_id in active_tests:
                    test_info = active_tests[test_id]
                    api_obj = test_info.get('api')
                    config_obj = test_info.get('config')
                    start_time = test_info.get('start_time')

                    if api_obj and config_obj:
                        duration = (datetime.now() - start_time).total_seconds()
                        report_filename = load_test_report_generator.generate_manual_report(
                            test_id=test_id,
                            api=api_obj,
                            config=config_obj,
                            metrics=metrics,
                            duration=duration,
                            llm_provider=llm_provider
                        )
                        print(f"✅ [BACKGROUND] Manual report regenerated with AI insights: {report_filename}", flush=True)

    except Exception as e:
        print(f"❌ [BACKGROUND] Failed to generate AI insights: {e}", flush=True)
        import traceback
        traceback.print_exc()


async def stream_metrics_task(test_id: str, session_id: str):
    """Background task to stream metrics via SSE."""
    try:
        while locust_manager.is_test_running(test_id):
            # Get current metrics
            metrics = await locust_manager.get_metrics(test_id)

            if metrics:
                # Broadcast to SSE - use model_dump with mode='json' for datetime serialization
                await sse_manager.broadcast_to_session(
                    session_id,
                    "load_test_metrics",
                    metrics.model_dump(mode='json')
                )

            # Wait 2 seconds before next poll
            await asyncio.sleep(2)

        # Test completed, send final metrics
        print(f"🏁 [STREAM] Test {test_id} completed, fetching final metrics...", flush=True)
        final_metrics = await locust_manager.get_metrics(test_id)
        print(f"🏁 [STREAM] Final metrics: {final_metrics}", flush=True)

        if final_metrics:
            final_metrics.status = "completed"
            await sse_manager.broadcast_to_session(
                session_id,
                "load_test_completed",
                final_metrics.model_dump(mode='json')
            )

        # Update test status and generate report
        print(f"📝 [STREAM] Checking active_tests for {test_id}...", flush=True)
        print(f"📝 [STREAM] Active tests keys: {list(active_tests.keys())}", flush=True)

        if test_id in active_tests:
            print(f"✅ [STREAM] Found test {test_id} in active_tests", flush=True)
            active_tests[test_id]["status"] = "completed"

            # Generate HTML report for manual test
            try:
                test_info = active_tests[test_id]
                api = test_info.get("api")
                config = test_info.get("config")
                start_time = test_info.get("start_time")

                print(f"📊 [STREAM] Report generation check - api: {api is not None}, config: {config is not None}, final_metrics: {final_metrics is not None}", flush=True)

                if api and config and final_metrics:
                    duration = (datetime.now() - start_time).total_seconds()
                    # Get LLM provider from session or default to groq
                    llm_provider_str = test_info.get("llm_provider", "groq")

                    print(f"📊 [STREAM] Calling generate_manual_report with provider: {llm_provider_str}...", flush=True)
                    report_filename = load_test_report_generator.generate_manual_report(
                        test_id,
                        api,
                        config,
                        final_metrics,
                        duration,
                        llm_provider_str
                    )
                    print(f"📄 Manual test report generated: {report_filename}", flush=True)

                    # Auto-generate AI insights in background
                    try:
                        print(f"🤖 [STREAM] Auto-generating AI insights for test: {test_id}", flush=True)

                        # Generate insights asynchronously (don't block the stream)
                        asyncio.create_task(
                            generate_ai_insights_background(
                                test_id=test_id,
                                llm_provider=llm_provider_str,
                                metrics=final_metrics,
                                config=config,
                                api=api,
                                regenerate_report=True
                            )
                        )
                        print(f"✅ [STREAM] AI insights generation started in background", flush=True)
                    except Exception as e:
                        print(f"⚠️ Failed to start AI insights generation: {e}", flush=True)
                else:
                    print(f"⚠️ [STREAM] Cannot generate report - missing data: api={api is not None}, config={config is not None}, metrics={final_metrics is not None}", flush=True)
            except Exception as e:
                print(f"⚠️ Failed to generate manual test report: {e}", flush=True)
                import traceback
                traceback.print_exc()
        else:
            print(f"❌ [STREAM] Test {test_id} NOT found in active_tests", flush=True)

    except Exception as e:
        print(f"Error streaming metrics for test {test_id}: {e}")
        await sse_manager.broadcast_to_session(
            session_id,
            "load_test_error",
            {"test_id": test_id, "error": str(e)}
        )


@router.post("/start-sequential", response_model=LoadTestStartResponse)
async def start_sequential_test(
    request: SequentialLoadTestRequest,
    background_tasks: BackgroundTasks
):
    """
    Start sequential load testing of multiple APIs.
    Each API runs one after another in Excel row order.

    Args:
        request: Sequential load test request

    Returns:
        Sequential test ID and details
    """
    # Validate upload session (try memory first, then disk)
    if request.upload_id not in uploaded_configs:
        apis = load_upload_config(request.upload_id)
        if not apis:
            raise HTTPException(status_code=404, detail="Upload session not found")
        uploaded_configs[request.upload_id] = apis
    else:
        apis = uploaded_configs[request.upload_id]

    # Use user-edited configs if provided, otherwise fall back to uploaded Excel configs
    if request.selected_apis_config:
        # User edited configs — use directly (already ordered by frontend)
        selected_apis = request.selected_apis_config
        logger.info(f"✓ Using user-edited API configs for {len(selected_apis)} APIs")
    else:
        # Filter selected APIs from uploaded Excel (maintain Excel row order)
        selected_apis = [api for api in apis if api.name in request.selected_api_names]
        logger.info(f"✓ Using Excel configs for {len(selected_apis)} APIs")

    if not selected_apis:
        raise HTTPException(status_code=404, detail="No matching APIs found")

    # Generate sequential test ID
    sequential_test_id = f"seq_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"

    # Send initial SSE event
    await sse_manager.broadcast_to_session(
        request.session_id,
        "sequential_test_started",
        {
            "sequential_test_id": sequential_test_id,
            "total_apis": len(selected_apis),
            "current_index": 0,
            "current_api": None,
            "status": "running",
            "apis": [api.name for api in selected_apis],
            "message": f"Starting sequential test with {len(selected_apis)} APIs"
        }
    )

    # Start sequential test
    success = await sequential_test_manager.start_sequential_test(
        sequential_test_id,
        selected_apis,
        request.session_id,
        request.llm_provider or "groq"  # Pass LLM provider for AI insights
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to start sequential test")

    # Calculate total estimated duration
    total_duration_seconds = sum([parse_time_to_seconds(api.run_time) if hasattr(api, 'run_time') and api.run_time else 300 for api in selected_apis])
    total_duration_minutes = total_duration_seconds // 60

    return LoadTestStartResponse(
        test_id=sequential_test_id,
        message=f"Sequential test started for {len(selected_apis)} APIs",
        locustfile_path="",  # Multiple files
        estimated_duration=f"{total_duration_minutes}m"
    )


@router.post("/stop-sequential/{sequential_test_id}")
async def stop_sequential_test(sequential_test_id: str):
    """Stop a running sequential test."""
    # Get session_id before stopping
    test_info = sequential_test_manager.get_sequential_test_status(sequential_test_id)
    session_id = test_info.get("session_id") if test_info else None

    success = sequential_test_manager.stop_sequential_test(sequential_test_id)

    if success:
        # Broadcast stop event via SSE if we have a session
        if session_id:
            await sse_manager.broadcast_to_session(
                session_id,
                "sequential_test_stopped",
                {
                    "sequential_test_id": sequential_test_id,
                    "message": "Stopped by user"
                }
            )
            print(f"📡 Broadcasted sequential_test_stopped event to session {session_id}", flush=True)

        return {"message": "Sequential test stopped", "sequential_test_id": sequential_test_id}
    else:
        raise HTTPException(status_code=404, detail="Sequential test not found")


@router.get("/sequential-status/{sequential_test_id}")
async def get_sequential_status(sequential_test_id: str):
    """Get status of a sequential test."""
    status = sequential_test_manager.get_sequential_test_status(sequential_test_id)

    if status:
        return status
    else:
        raise HTTPException(status_code=404, detail="Sequential test not found")


@router.get("/current-report")
async def get_current_report():
    """Get information about the current/latest report."""
    report_info = load_test_report_generator.get_current_report()
    
    if not report_info:
        raise HTTPException(status_code=404, detail="No report available")
    
    return report_info


@router.get("/report/{filename}")
async def get_report_html(filename: str):
    """Get HTML content of a specific report."""
    from fastapi.responses import HTMLResponse
    
    report_path = load_test_report_generator.results_dir / filename
    
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    
    try:
        with open(report_path, 'r') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except Exception as e:
        print(f"❌ Error reading report {filename}: {e}", flush=True)
        raise HTTPException(status_code=500, detail="Failed to read report")


@router.post("/agentic-analyze")
async def analyze_api_with_agents(
    upload_id: str,
    api_name: str,
    llm_provider: str = "groq",
    model: str = None,
    request: Request = None
):
    """
    Analyze API configuration using AI agents and generate recommendations.

    Phase 2A: Uses ConfigParserAgent and DataGeneratorAgent to:
    - Detect API type
    - Extract required fields
    - Recommend load test parameters
    - Generate realistic test data

    Args:
        upload_id: Upload session ID
        api_name: Name of API to analyze
        llm_provider: LLM provider (groq, openai, anthropic)
        model: Optional model override

    Returns:
        JSON with recommendations and generated data
    """
    logger.info("\n" + "="*80)
    logger.info("🤖 API Call: POST /agentic-analyze")
    logger.info("="*80)
    logger.info(f"🎯 API Name: {api_name}")
    logger.info(f"🆔 Upload ID: {upload_id}")
    logger.info(f"🧠 LLM Provider: {llm_provider}")
    if model:
        logger.info(f"📝 Model: {model}")

    # Extract custom suggestions from request body (NEW)
    custom_suggestions = None
    if request:
        try:
            body = await request.json()
            custom_suggestions = body.get('custom_suggestions')
            if custom_suggestions:
                logger.info(f"📝 Custom Suggestions Provided:")
                logger.info(f"   └─ {custom_suggestions[:200]}...")
        except:
            pass  # No body or invalid JSON

    # Get uploaded API config
    if upload_id not in uploaded_configs:
        logger.error(f"❌ Upload session not found: {upload_id}")
        raise HTTPException(status_code=404, detail="Upload session not found")

    apis = uploaded_configs[upload_id]
    api = next((a for a in apis if a.name == api_name), None)

    if not api:
        logger.error(f"❌ API not found: {api_name}")
        raise HTTPException(status_code=404, detail=f"API '{api_name}' not found")

    logger.info(f"✓ API Configuration Found")
    logger.info(f"   • Endpoint: {api.endpoint}")
    logger.info(f"   • Method: {api.method}")

    # Convert API config to dict for state
    raw_config = api.dict()

    # Initialize supervisor with selected LLM
    try:
        provider = LLMProvider(llm_provider.lower())
    except ValueError:
        provider = LLMProvider.GROQ
        logger.warning(f"⚠️  Invalid provider '{llm_provider}', defaulting to GROQ")

    # Validate provider configuration
    validate_provider_config(provider)

    logger.info(f"\n🔧 Initializing LoadTestSupervisor...")
    supervisor = LoadTestSupervisor(provider=provider, model=model)

    try:
        # Execute workflow (blocking for now, will be async with SSE later)
        from app.agents.load_test.state import AgenticLoadTestState
        from datetime import datetime
        import uuid as uuid_lib

        state: AgenticLoadTestState = {
            'raw_config': raw_config,
            'excel_filename': 'uploaded_excel',
            'session_id': str(uuid_lib.uuid4()),
            'started_at': datetime.now(),
            'agent_thoughts': [],
            'errors': [],
            'custom_suggestions': custom_suggestions  # NEW
        }

        # Run ConfigParserAgent
        logger.info("\n🤖 Step 1/2: Running ConfigParserAgent")
        logger.info("   └─ Analyzing API structure and requirements...")
        state = supervisor.config_parser.execute(state)

        if state.get('api_type'):
            logger.info(f"   ✓ API Type: {state['api_type']}")
        if state.get('required_fields'):
            logger.info(f"   ✓ Required Fields: {', '.join(state['required_fields'])}")

        # Run DataGeneratorAgent
        if state.get('required_fields'):
            logger.info("\n🤖 Step 2/2: Running DataGeneratorAgent")
            logger.info("   └─ Generating realistic test data...")
            state = supervisor.data_generator.execute(state)

            if state.get('generated_data'):
                logger.info(f"   ✓ Generated {len(state['generated_data'])} test data entries")

        # Extract recommendations
        recommendations = supervisor.get_recommendations(state)

        logger.info("\n✅ Analysis Complete!")
        logger.info(f"📊 Recommendations:")
        logger.info(f"   • Users: {recommendations.get('users')}")
        logger.info(f"   • Spawn Rate: {recommendations.get('spawn_rate')}/s")
        logger.info(f"   • Think Time: {recommendations.get('think_time_min')}-{recommendations.get('think_time_max')}s")
        logger.info("="*80 + "\n")

        return {
            'success': True,
            'session_id': state['session_id'],
            'api_type': state.get('api_type'),
            'required_fields': state.get('required_fields', []),
            'recommendations': recommendations,
            'agent_thoughts': [
                {
                    'agent': t['agent'],
                    'thought': t['thought'],
                    'reasoning': t['reasoning']
                }
                for t in state.get('agent_thoughts', [])
            ]
        }

    except Exception as e:
        print(f"❌ Agentic analysis error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {str(e)}")


@router.post("/agentic-apply")
async def apply_agentic_recommendations(
    upload_id: str,
    api_name: str,
    request_body: Dict[str, Any]
):
    """
    Apply AI-generated recommendations to an API configuration.

    Args:
        upload_id: Upload session ID
        api_name: Name of API to update
        request_body: Body containing recommendations

    Returns:
        Updated API configuration
    """
    recommendations = request_body.get('recommendations', {})

    logger.info("\n" + "="*80)
    logger.info("✏️  API Call: POST /agentic-apply")
    logger.info("="*80)
    logger.info(f"🎯 API: {api_name}")
    logger.info(f"🆔 Upload ID: {upload_id}")
    logger.info(f"📊 Recommendations received:")
    logger.info(f"   • Users: {recommendations.get('users')}")
    logger.info(f"   • Spawn Rate: {recommendations.get('spawn_rate')}")
    logger.info(f"   • Think Time: {recommendations.get('think_time_min')}-{recommendations.get('think_time_max')}s")
    logger.info(f"   • Test Data: {len(recommendations.get('test_data', []))} entries")

    if upload_id not in uploaded_configs:
        logger.error(f"❌ Upload session not found: {upload_id}")
        raise HTTPException(status_code=404, detail="Upload session not found")

    apis = uploaded_configs[upload_id]
    api_index = next((i for i, a in enumerate(apis) if a.name == api_name), None)

    if api_index is None:
        logger.error(f"❌ API not found: {api_name}")
        raise HTTPException(status_code=404, detail=f"API '{api_name}' not found")

    api = apis[api_index]

    logger.info(f"📝 Applying recommendations to API configuration...")
    logger.info(f"   Existing test_data: {len(api.test_data or [])} entries")

    # Apply recommendations
    api.users = recommendations.get('users')
    api.spawn_rate = recommendations.get('spawn_rate')
    api.think_time_min = recommendations.get('think_time_min')
    api.think_time_max = recommendations.get('think_time_max')
    api.data_mode = recommendations.get('data_mode', 'round_robin')

    # Only update test_data if it's explicitly provided in recommendations
    # If not provided (None or not in dict), keep existing Excel data
    if 'test_data' in recommendations and recommendations['test_data'] is not None:
        api.test_data = recommendations['test_data']
        logger.info(f"   ✅ Updating with AI test_data: {len(api.test_data)} entries")
    else:
        logger.info(f"   ✅ Keeping existing Excel test_data: {len(api.test_data or [])} entries")

    # Update in storage
    apis[api_index] = api
    uploaded_configs[upload_id] = apis

    # Save to disk
    save_upload_config(upload_id, apis)

    logger.info("✅ Recommendations Applied Successfully!")
    logger.info(f"📊 Updated Configuration:")
    logger.info(f"   • Users: {api.users}")
    logger.info(f"   • Spawn Rate: {api.spawn_rate}/s")
    logger.info(f"   • Think Time: {api.think_time_min}-{api.think_time_max}s")
    logger.info(f"   • Test Data: {len(api.test_data or [])} entries")
    logger.info("="*80 + "\n")

    return {
        'success': True,
        'api': api.dict()
    }


@router.post("/agentic-analyze-batch")
async def analyze_apis_batch(
    request_body: Dict[str, Any]
):
    """
    Batch analyze multiple APIs using AI agents.

    Request Body:
    {
        "upload_id": "abc123",
        "api_names": ["Health", "Login"],
        "llm_provider": "groq",  // optional
        "model": "model_name"     // optional
    }

    Returns:
        JSON with recommendations for all APIs
    """
    upload_id = request_body.get('upload_id')
    api_names = request_body.get('api_names', [])
    llm_provider = request_body.get('llm_provider', 'groq')
    model = request_body.get('model')
    custom_suggestions = request_body.get('custom_suggestions')  # NEW

    logger.info("\n" + "="*80)
    logger.info("🤖 API Call: POST /agentic-analyze-batch")
    logger.info("="*80)
    logger.info(f"🆔 Upload ID: {upload_id}")
    logger.info(f"🎯 APIs to Analyze: {len(api_names)}")
    logger.info(f"   └─ {', '.join(api_names)}")
    logger.info(f"🧠 LLM Provider: {llm_provider}")

    # NEW: Log custom suggestions if provided
    if custom_suggestions:
        logger.info(f"📝 Batch Custom Suggestions:")
        logger.info(f"   └─ {custom_suggestions[:200]}...")

    # Get uploaded API configs
    if upload_id not in uploaded_configs:
        logger.error(f"❌ Upload session not found: {upload_id}")
        raise HTTPException(status_code=404, detail="Upload session not found")

    all_apis = uploaded_configs[upload_id]

    # Find selected APIs
    selected_apis = [api for api in all_apis if api.name in api_names]

    if not selected_apis:
        logger.error(f"❌ No matching APIs found")
        raise HTTPException(status_code=404, detail="No matching APIs found")

    logger.info(f"✓ Found {len(selected_apis)} APIs to analyze")

    # Initialize supervisor with selected LLM
    try:
        provider = LLMProvider(llm_provider.lower())
    except ValueError:
        provider = LLMProvider.GROQ
        logger.warning(f"⚠️  Invalid provider '{llm_provider}', defaulting to GROQ")

    # Validate provider configuration
    validate_provider_config(provider)

    logger.info(f"\n🔧 Initializing LoadTestSupervisor...")
    supervisor = LoadTestSupervisor(provider=provider, model=model)

    results = []

    # Analyze each API
    for idx, api in enumerate(selected_apis, 1):
        logger.info(f"\n{'─'*80}")
        logger.info(f"🤖 Analyzing API {idx}/{len(selected_apis)}: {api.name}")
        logger.info(f"{'─'*80}")
        logger.info(f"   • Endpoint: {api.endpoint}")
        logger.info(f"   • Method: {api.method}")

        try:
            # Convert API config to dict for state
            raw_config = api.dict()

            from app.agents.load_test.state import AgenticLoadTestState
            from datetime import datetime
            import uuid as uuid_lib

            state: AgenticLoadTestState = {
                'raw_config': raw_config,
                'excel_filename': 'uploaded_excel',
                'session_id': str(uuid_lib.uuid4()),
                'started_at': datetime.now(),
                'agent_thoughts': [],
                'errors': [],
                'custom_suggestions': custom_suggestions  # NEW
            }

            # Run ConfigParserAgent
            logger.info(f"   🤖 Step 1/2: Running ConfigParserAgent...")
            state = supervisor.config_parser.execute(state)

            if state.get('api_type'):
                logger.info(f"   ✓ API Type: {state['api_type']}")
            if state.get('required_fields'):
                logger.info(f"   ✓ Required Fields: {', '.join(state['required_fields'])}")

            # Run DataGeneratorAgent if there are required fields
            if state.get('required_fields'):
                logger.info(f"   🤖 Step 2/2: Running DataGeneratorAgent...")
                state = supervisor.data_generator.execute(state)

                if state.get('generated_data'):
                    logger.info(f"   ✓ Generated {len(state['generated_data'])} test data entries")

            # Extract recommendations
            recommendations = supervisor.get_recommendations(state)

            logger.info(f"   ✅ Analysis Complete for {api.name}!")
            logger.info(f"   📊 Recommendations:")
            logger.info(f"      • Users: {recommendations.get('users')}")
            logger.info(f"      • Spawn Rate: {recommendations.get('spawn_rate')}/s")
            logger.info(f"      • Think Time: {recommendations.get('think_time_min')}-{recommendations.get('think_time_max')}s")
            logger.info(f"      • Test Data: {len(recommendations.get('test_data', []))} entries")

            results.append({
                'api_name': api.name,
                'api_type': state.get('api_type'),
                'endpoint': api.endpoint,
                'method': api.method,
                'required_fields': state.get('required_fields', []),
                'recommendations': recommendations
            })

        except Exception as e:
            logger.error(f"   ❌ Error analyzing {api.name}: {str(e)}")
            # Continue with other APIs even if one fails
            results.append({
                'api_name': api.name,
                'api_type': 'unknown',
                'endpoint': api.endpoint,
                'method': api.method,
                'required_fields': [],
                'recommendations': {
                    'users': 10,
                    'spawn_rate': 2,
                    'think_time_min': 1.0,
                    'think_time_max': 3.0,
                    'data_mode': 'round_robin',
                    'test_data': []
                },
                'error': str(e)
            })

    logger.info(f"\n{'='*80}")
    logger.info(f"✅ Batch Analysis Complete!")
    logger.info(f"   📊 Successfully analyzed {len(results)} APIs")
    logger.info(f"{'='*80}\n")

    return {
        'success': True,
        'total_apis': len(results),
        'results': results
    }


@router.post("/agentic-apply-batch")
async def apply_batch_recommendations(
    upload_id: str,
    request_body: Dict[str, Any]
):
    """
    Apply AI recommendations to multiple APIs in batch.

    Args:
        upload_id: Upload session ID
        request_body: Body containing list of API configs with recommendations

    Request Body Format:
    {
        "apis": [
            {
                "api_name": "Health",
                "use_ai_test_data": false,
                "recommendations": {...}
            },
            ...
        ]
    }

    Returns:
        Updated API configurations
    """
    apis_to_update = request_body.get('apis', [])

    logger.info("\n" + "="*80)
    logger.info("✏️  API Call: POST /agentic-apply-batch")
    logger.info("="*80)
    logger.info(f"🆔 Upload ID: {upload_id}")
    logger.info(f"📊 APIs to Update: {len(apis_to_update)}")

    if upload_id not in uploaded_configs:
        logger.error(f"❌ Upload session not found: {upload_id}")
        raise HTTPException(status_code=404, detail="Upload session not found")

    all_apis = uploaded_configs[upload_id]
    updated_apis = []

    # Process each API
    for api_config in apis_to_update:
        api_name = api_config.get('api_name')
        use_ai_test_data = api_config.get('use_ai_test_data', False)
        recommendations = api_config.get('recommendations', {})

        logger.info(f"\n{'─'*80}")
        logger.info(f"📝 Processing: {api_name}")
        logger.info(f"   • Use AI Test Data: {use_ai_test_data}")
        logger.info(f"   • Users: {recommendations.get('users')}")
        logger.info(f"   • Spawn Rate: {recommendations.get('spawn_rate')}/s")
        logger.info(f"   • Test Data: {len(recommendations.get('test_data', []))} entries")

        # Find API in storage
        api_index = next((i for i, a in enumerate(all_apis) if a.name == api_name), None)

        if api_index is None:
            logger.warning(f"⚠️  API not found: {api_name}, skipping...")
            continue

        api = all_apis[api_index]

        # Apply recommendations
        api.users = recommendations.get('users', api.users)
        api.spawn_rate = recommendations.get('spawn_rate', api.spawn_rate)
        api.think_time_min = recommendations.get('think_time_min', api.think_time_min)
        api.think_time_max = recommendations.get('think_time_max', api.think_time_max)
        api.data_mode = recommendations.get('data_mode', api.data_mode or 'round_robin')

        # Handle test data based on toggle
        if use_ai_test_data and 'test_data' in recommendations:
            # Use AI-generated test data
            api.test_data = recommendations['test_data']
            logger.info(f"   ✅ Applied AI test_data: {len(api.test_data or [])} entries")
        else:
            # Keep Excel test data (don't overwrite)
            logger.info(f"   ✅ Keeping Excel test_data: {len(api.test_data or [])} entries")

        # Update in storage
        all_apis[api_index] = api
        updated_apis.append(api.dict())

        logger.info(f"   ✅ Updated {api_name}")

    # Save all changes
    uploaded_configs[upload_id] = all_apis
    save_upload_config(upload_id, all_apis)

    logger.info(f"\n{'='*80}")
    logger.info(f"✅ Batch Apply Complete!")
    logger.info(f"   📊 Updated {len(updated_apis)} APIs")
    logger.info(f"{'='*80}\n")

    return {
        'success': True,
        'total_updated': len(updated_apis),
        'updated_apis': updated_apis
    }


@router.get("/agentic-workflow-stream")
async def agentic_workflow_stream(
    upload_id: str,
    api_name: str,
    llm_provider: str = "groq",
    model: str = None
):
    """
    Execute full agentic workflow with SSE streaming.

    Phase 2B: Complete workflow with all 6 agents:
    1. ConfigParserAgent - Analyze API
    2. DataGeneratorAgent - Generate test data
    3. LocustGeneratorAgent - Create optimized Locustfile
    4. ExecutorAgent - Monitor execution (during test)
    5. AnalyzerAgent - Analyze results (after test)
    6. ReporterAgent - Generate report (after test)

    Returns:
        SSE stream with real-time agent thoughts and progress
    """
    print(f"\n🚀 Starting full agentic workflow for: {api_name}", flush=True)

    # Get uploaded API config
    if upload_id not in uploaded_configs:
        raise HTTPException(status_code=404, detail="Upload session not found")

    apis = uploaded_configs[upload_id]
    api = next((a for a in apis if a.name == api_name), None)

    if not api:
        raise HTTPException(status_code=404, detail=f"API '{api_name}' not found")

    # Convert API config to dict
    raw_config = api.dict()

    # Initialize supervisor
    try:
        provider = LLMProvider(llm_provider.lower())
    except ValueError:
        provider = LLMProvider.GROQ

    # Validate provider configuration
    validate_provider_config(provider)

    supervisor = LoadTestSupervisor(provider=provider, model=model)

    # Generate test ID
    import uuid
    test_id = f"agentic_{uuid.uuid4().hex[:8]}"

    # Stream workflow
    async def event_generator():
        try:
            async for event in supervisor.execute_full_workflow(
                raw_config=raw_config,
                excel_filename='uploaded_excel',
                test_id=test_id
            ):
                yield event
                await asyncio.sleep(0.1)  # Small delay for smooth streaming

        except Exception as e:
            print(f"❌ Workflow error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            yield f"event: workflow_error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return EventSourceResponse(event_generator())


@router.post("/analyze-with-all-agents")
async def analyze_with_all_agents(
    upload_id: str,
    api_name: str,
    llm_provider: str = "groq"
):
    """
    Run complete analysis with all agents (blocking version).

    This runs the full workflow and returns final results.
    For real-time streaming, use /agentic-workflow-stream instead.
    """
    print(f"\n🤖 Running full agent analysis for: {api_name}", flush=True)

    if upload_id not in uploaded_configs:
        raise HTTPException(status_code=404, detail="Upload session not found")

    apis = uploaded_configs[upload_id]
    api = next((a for a in apis if a.name == api_name), None)

    if not api:
        raise HTTPException(status_code=404, detail=f"API '{api_name}' not found")

    raw_config = api.dict()

    try:
        provider = LLMProvider(llm_provider.lower())
    except ValueError:
        provider = LLMProvider.GROQ

    # Validate provider configuration
    validate_provider_config(provider)

    supervisor = LoadTestSupervisor(provider=provider)

    try:
        from app.agents.load_test.state import AgenticLoadTestState
        from datetime import datetime
        import uuid as uuid_lib

        state: AgenticLoadTestState = {
            'raw_config': raw_config,
            'excel_filename': 'uploaded_excel',
            'test_id': f"agent_{uuid_lib.uuid4().hex[:8]}",
            'session_id': str(uuid_lib.uuid4()),
            'started_at': datetime.now(),
            'agent_thoughts': [],
            'errors': []
        }

        # Run all agents sequentially
        print("🔍 Running ConfigParserAgent...", flush=True)
        state = supervisor.config_parser.execute(state)

        if state.get('required_fields'):
            print("🎲 Running DataGeneratorAgent...", flush=True)
            state = supervisor.data_generator.execute(state)

        print("⚙️ Running LocustGeneratorAgent...", flush=True)
        state = supervisor.locust_generator.execute(state)

        print("✅ All agents complete", flush=True)

        recommendations = supervisor.get_recommendations(state)

        return {
            'success': True,
            'session_id': state['session_id'],
            'api_type': state.get('api_type'),
            'required_fields': state.get('required_fields', []),
            'recommendations': recommendations,
            'locustfile_generated': bool(state.get('locustfile_content')),
            'agent_thoughts': [
                {
                    'agent': t['agent'],
                    'thought': t['thought'],
                    'reasoning': t['reasoning']
                }
                for t in state.get('agent_thoughts', [])
            ]
        }

    except Exception as e:
        print(f"❌ Agent analysis error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {str(e)}")


@router.get("/analysis/{test_id}")
async def get_test_analysis(test_id: str, llm_provider: str = "groq", force_regenerate: bool = False):
    """
    Get AI-powered analysis and suggestions for a completed load test.

    Args:
        test_id: Load test ID (can be single test or sequential test ID)
        llm_provider: AI provider (groq, openai, anthropic)
        force_regenerate: If True, bypass cache and regenerate analysis

    Returns:
        AI analysis with test and API suggestions
    """
    # Handle "undefined" from frontend - treat as default "groq"
    if llm_provider == "undefined" or not llm_provider:
        llm_provider = "groq"

    # Check cache first (unless force_regenerate is True)
    cache_key = f"{test_id}_{llm_provider}"
    if not force_regenerate and cache_key in ai_analysis_cache:
        logger.info(f"✅ Returning cached AI analysis for test: {test_id} (provider: {llm_provider})")
        return ai_analysis_cache[cache_key]

    logger.info(f"🤖 Generating AI analysis for test: {test_id}")

    # Try to get metrics from active_tests or locust_manager cache
    metrics_dict = None
    test_config_dict = {}
    api_details_dict = {}

    # Check if test is in active_tests (recent tests)
    if test_id in active_tests:
        test_info = active_tests[test_id]
        metrics_dict = test_info.get('metrics', {})
        test_config_dict = test_info.get('config', {})

        # Convert APIConfig object to dict if needed
        api_obj = test_info.get('api', {})
        if hasattr(api_obj, 'dict'):
            api_details_dict = api_obj.dict()
        elif isinstance(api_obj, dict):
            api_details_dict = api_obj
        else:
            api_details_dict = {}

        logger.info(f"   📊 Found test in active_tests")

    # If not in active_tests, try to get from locust_manager cache
    if not metrics_dict:
        cached_metrics = await locust_manager.get_metrics(test_id)
        if cached_metrics:
            metrics_dict = cached_metrics.dict() if hasattr(cached_metrics, 'dict') else cached_metrics
            logger.info(f"   📊 Found test in locust_manager cache")

    # If still no metrics, try loading from CSV files
    if not metrics_dict:
        logger.info(f"   📊 Attempting to load metrics from CSV files...")
        metrics_dict = load_metrics_from_csv(test_id)
        if metrics_dict:
            logger.info(f"   ✅ Loaded metrics from CSV files")

    # If still no metrics, check if it's a sequential test
    if not metrics_dict and test_id.startswith('seq_'):
        seq_test = sequential_test_manager.get_test_status(test_id)
        if seq_test and seq_test.get('api_results'):
            # Use the last completed API's metrics as representative
            last_result = seq_test['api_results'][-1]
            metrics_dict = last_result.get('metrics', {})
            test_config_dict = last_result.get('config', {})
            api_details_dict = {
                'endpoint': last_result.get('endpoint', '/api/endpoint'),
                'method': last_result.get('method', 'GET'),
                'api_type': 'unknown'
            }
            logger.info(f"   📊 Found sequential test with {len(seq_test['api_results'])} API results")

    if not metrics_dict:
        raise HTTPException(
            status_code=404,
            detail=f"No metrics found for test_id: {test_id}. Test may be too old or not completed."
        )

    # Ensure metrics is a dict and has test_id
    if isinstance(metrics_dict, LoadTestMetrics):
        metrics_dict = metrics_dict.dict()
    metrics_dict['test_id'] = test_id

    # Convert config to dict if needed
    if hasattr(test_config_dict, 'dict'):
        test_config_dict = test_config_dict.dict()

    # Validate provider (but don't fail if API key is missing - we'll use fallback)
    try:
        provider = LLMProvider(llm_provider.lower())
    except ValueError:
        provider = LLMProvider.GROQ

    # Check if provider has API key configured
    use_ai = False
    try:
        validate_provider_config(provider)
        use_ai = True
        logger.info(f"   ✅ Using AI-powered analysis with {provider.value}")
    except HTTPException:
        logger.warning(f"   ⚠️ API key not configured for {provider.value}, using rule-based analysis only")
        # Don't fail - we'll use rule-based fallback

    # Initialize AnalyzerAgent (only if we have API key)
    analyzer = None
    if use_ai:
        try:
            from app.agents.load_test.sub_agents.analyzer_agent import AnalyzerAgent

            # Pass API keys based on provider
            if provider == LLMProvider.GROQ:
                analyzer = AnalyzerAgent(
                    provider=provider,
                    groq_api_key=settings.GROQ_API_KEY,
                    groq_model=settings.GROQ_MODEL
                )
            elif provider == LLMProvider.OPENAI:
                analyzer = AnalyzerAgent(
                    provider=provider,
                    openai_api_key=settings.OPENAI_API_KEY,
                    openai_model=settings.OPENAI_MODEL
                )
            elif provider == LLMProvider.WAYMORE:
                analyzer = AnalyzerAgent(
                    provider=provider,
                    waymore_api_key=settings.WAYMORE_API_KEY,
                    waymore_model=settings.WAYMORE_MODEL
                )
            else:  # ANTHROPIC
                analyzer = AnalyzerAgent(
                    provider=provider,
                    anthropic_api_key=settings.ANTHROPIC_API_KEY,
                    anthropic_model=settings.ANTHROPIC_MODEL
                )
        except Exception as e:
            logger.warning(f"   ⚠️ Failed to initialize AnalyzerAgent: {e}. Using fallback.")
            analyzer = None

    # Generate analysis (with or without AI)
    try:
        if analyzer:
            # Use AI-powered analysis
            analysis = analyzer.analyze_and_suggest(
                metrics=metrics_dict,
                test_config=test_config_dict,
                api_details=api_details_dict
            )
            logger.info(f"   ✅ Generated AI analysis with score: {analysis.performance_score}/100")
        else:
            # Use fallback rule-based analysis
            from app.agents.load_test.sub_agents.analyzer_agent import AnalyzerAgent
            from app.models.load_test_models import AIAnalysis, TestSuggestion, APISuggestion, SuggestionMetrics
            from datetime import datetime
            import uuid

            logger.info(f"   📊 Generating rule-based analysis (AI not available)")

            # Calculate performance score using rule-based method
            total_requests = metrics_dict.get('total_requests', 0)
            total_failures = metrics_dict.get('total_failures', 0)
            error_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0
            p95 = metrics_dict.get('percentile_95', 0)
            p99 = metrics_dict.get('percentile_99', 0)
            avg_response = metrics_dict.get('avg_response_time', 0)
            max_response = metrics_dict.get('max_response_time', 0)
            min_response = metrics_dict.get('min_response_time', 0)

            # Calculate score
            score = 0
            if error_rate < 0.1:
                score += 30
            elif error_rate < 1.0:
                score += 20
            elif error_rate < 5.0:
                score += 10

            if p95 < 200:
                score += 30
            elif p95 < 500:
                score += 20
            elif p95 < 1000:
                score += 10

            if p99 < 500:
                score += 20
            elif p99 < 1000:
                score += 15
            elif p99 < 2000:
                score += 10

            variance_ratio = (max_response - min_response) / avg_response if avg_response > 0 else 0
            if variance_ratio < 5:
                score += 20
            elif variance_ratio < 10:
                score += 15
            elif variance_ratio < 20:
                score += 10

            performance_level = 'good' if score >= 80 else 'warning' if score >= 60 else 'critical'

            # Generate rule-based test suggestions
            test_suggestions = []
            users = test_config_dict.get('users', 10)
            spawn_rate = test_config_dict.get('spawn_rate', 2)
            run_time = test_config_dict.get('run_time', '5m')

            if error_rate < 2 and users < 500:
                test_suggestions.append(TestSuggestion(
                    id="test_1",
                    severity="warning",
                    title="Increase load to find capacity limits",
                    description=f"Your API handled {users} users with only {error_rate:.2f}% error rate. This indicates headroom for more load.",
                    reasoning="Finding the breaking point helps plan capacity and understand system limits.",
                    metrics=SuggestionMetrics(
                        current_users=users,
                        recommended_users=min(users * 5, 500),
                        current_spawn_rate=spawn_rate,
                        recommended_spawn_rate=min(spawn_rate * 2, 20),
                        current_duration=run_time,
                        recommended_duration="10m"
                    )
                ))

            if error_rate > 10:
                test_suggestions.append(TestSuggestion(
                    id="test_2",
                    severity="critical",
                    title="Reduce load to establish baseline",
                    description=f"Error rate of {error_rate:.2f}% is too high. Need to find stable baseline first.",
                    reasoning="Establishing a stable baseline helps isolate performance issues.",
                    metrics=SuggestionMetrics(
                        current_users=users,
                        recommended_users=max(users // 5, 10),
                        current_spawn_rate=spawn_rate,
                        recommended_spawn_rate=max(spawn_rate / 2, 1),
                        current_duration=run_time,
                        recommended_duration="5m"
                    )
                ))

            # Generate rule-based API suggestions
            api_suggestions = []

            if p95 > 200:
                improvement_pct = ((p95 - 200) / p95 * 100)
                api_suggestions.append(APISuggestion(
                    id="api_1",
                    severity="warning" if p95 < 500 else "critical",
                    category="response_time",
                    title="Optimize p95 response time",
                    description=f"Your p95 response time is {p95:.0f}ms, which is above the 200ms production standard.",
                    high_level="Implement caching for frequently accessed data",
                    technical="Add Redis cache with 5-minute TTL for GET endpoints. Consider database query optimization and proper indexing.",
                    metrics=SuggestionMetrics(
                        current_p95=p95,
                        target_p95=200,
                        improvement_needed=f"{improvement_pct:.0f}% reduction needed"
                    )
                ))

            if error_rate > 0.1:
                api_suggestions.append(APISuggestion(
                    id="api_2",
                    severity="critical" if error_rate > 5 else "warning",
                    category="error_rate",
                    title="High error rate detected",
                    description=f"{error_rate:.2f}% of requests failed",
                    high_level="Investigate server errors and add retry logic",
                    technical="Check database connection pool size. Current error rate suggests resource exhaustion. Increase DB connections from default to 50. Review error logs for specific failure patterns.",
                    metrics=SuggestionMetrics(
                        current_error_rate=error_rate,
                        target_error_rate=0.1,
                        failed_requests=total_failures,
                        total_requests=total_requests
                    )
                ))

            # Create analysis object
            analysis = AIAnalysis(
                test_id=test_id,
                performance_score=score,
                performance_level=performance_level,
                test_suggestions=test_suggestions,
                api_suggestions=api_suggestions,
                generated_at=datetime.now().isoformat()
            )

            logger.info(f"   ✅ Generated rule-based analysis with score: {score}/100")

        # Cache the analysis result
        cache_key = f"{test_id}_{llm_provider}"
        ai_analysis_cache[cache_key] = analysis
        logger.info(f"   💾 Cached AI analysis for future requests (key: {cache_key})")

        # Convert to dict for JSON response
        return analysis.dict()

    except Exception as e:
        logger.error(f"   ❌ Failed to generate analysis: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Analysis generation failed: {str(e)}")


@router.delete("/analysis/cache/{test_id}")
async def clear_analysis_cache(test_id: str, llm_provider: Optional[str] = None):
    """
    Clear cached AI analysis for a specific test.

    Args:
        test_id: Load test ID
        llm_provider: Optional specific provider to clear. If not provided, clears all providers.

    Returns:
        Success message
    """
    cleared_count = 0

    if llm_provider:
        # Clear specific provider cache
        cache_key = f"{test_id}_{llm_provider}"
        if cache_key in ai_analysis_cache:
            del ai_analysis_cache[cache_key]
            cleared_count = 1
            logger.info(f"🗑️ Cleared AI analysis cache for test: {test_id} (provider: {llm_provider})")
    else:
        # Clear all provider caches for this test
        keys_to_delete = [key for key in ai_analysis_cache.keys() if key.startswith(f"{test_id}_")]
        for key in keys_to_delete:
            del ai_analysis_cache[key]
            cleared_count += 1
        logger.info(f"🗑️ Cleared {cleared_count} AI analysis cache entries for test: {test_id}")

    return {
        "success": True,
        "message": f"Cleared {cleared_count} cache entries for test {test_id}",
        "cleared_count": cleared_count
    }


@router.delete("/analysis/cache")
async def clear_all_analysis_cache():
    """
    Clear all cached AI analysis results.

    Returns:
        Success message with count of cleared entries
    """
    cleared_count = len(ai_analysis_cache)
    ai_analysis_cache.clear()
    logger.info(f"🗑️ Cleared all AI analysis cache ({cleared_count} entries)")

    return {
        "success": True,
        "message": f"Cleared all AI analysis cache ({cleared_count} entries)",
        "cleared_count": cleared_count
    }
