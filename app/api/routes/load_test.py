"""API routes for load testing functionality."""

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from typing import Dict, List
from pathlib import Path
import uuid
import shutil
import asyncio
from datetime import datetime
import httpx

from app.models.load_test_models import (
    APIConfig,
    LoadTestRequest,
    LoadTestStartResponse,
    ExcelUploadResponse,
    LoadTestMetrics,
    ValidationResult,
    MultiAPILoadTestRequest,
    SequentialLoadTestRequest
)
from app.services.excel_to_load_test_parser import ExcelLoadTestParser
from app.services.dynamic_locust_generator import DynamicLocustfileGenerator
from app.services.locust_manager import locust_manager
from app.services.sequential_test_manager import sequential_test_manager, parse_time_to_seconds
from app.services.load_test_report_generator import load_test_report_generator
from app.core.sse_manager import sse_manager

# Don't include /api/v1 prefix here - it's already in main.py
router = APIRouter(prefix="/load-test", tags=["load-test"])

# In-memory storage for uploaded API configs
# In production, use database
# Using a more persistent approach - save to disk
import json

uploaded_configs: Dict[str, List[APIConfig]] = {}
active_tests: Dict[str, Dict] = {}

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
    # Validate file type
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only Excel files (.xlsx, .xls) are supported")

    # Generate upload ID
    upload_id = str(uuid.uuid4())

    # Save uploaded file
    file_path = UPLOAD_DIR / f"{upload_id}_{file.filename}"

    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Parse Excel file
        parser = ExcelLoadTestParser()
        api_configs = parser.execute(str(file_path))

        # Store in memory and persist to disk
        uploaded_configs[upload_id] = api_configs
        save_upload_config(upload_id, api_configs)

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
    # Validate upload session exists (try memory first, then disk)
    if request.upload_id not in uploaded_configs:
        apis = load_upload_config(request.upload_id)
        if not apis:
            raise HTTPException(status_code=404, detail="Upload session not found")
        uploaded_configs[request.upload_id] = apis
    else:
        apis = uploaded_configs[request.upload_id]

    # Find selected API
    selected_api = next((api for api in apis if api.name == request.selected_api_name), None)

    if not selected_api:
        raise HTTPException(status_code=404, detail=f"API '{request.selected_api_name}' not found")

    # Generate test ID
    test_id = f"test_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"

    # Generate Locustfile
    generator = DynamicLocustfileGenerator()
    locustfile_path = LOCUSTFILE_DIR / f"{test_id}.py"

    try:
        generator.generate_single_api(selected_api, str(locustfile_path))

        # Validate generated file
        if not generator.validate_locustfile(str(locustfile_path)):
            raise HTTPException(status_code=500, detail="Generated Locustfile is invalid")

        # Start Locust test
        success = locust_manager.start_test(test_id, str(locustfile_path), request.config)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to start Locust test")

        # Store test metadata
        active_tests[test_id] = {
            "test_id": test_id,
            "api_name": selected_api.name,
            "api": selected_api,  # Store full API object for report generation
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
        success = locust_manager.start_test(test_id, str(locustfile_path), request.config)

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
                    print(f"📊 [STREAM] Calling generate_manual_report...", flush=True)
                    report_filename = load_test_report_generator.generate_manual_report(
                        test_id,
                        api,
                        config,
                        final_metrics,
                        duration
                    )
                    print(f"📄 Manual test report generated: {report_filename}", flush=True)
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

    # Filter selected APIs (maintain Excel order)
    selected_apis = [api for api in apis if api.name in request.selected_api_names]

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
            "apis": [api.name for api in selected_apis],
            "message": f"Starting sequential test with {len(selected_apis)} APIs"
        }
    )

    # Start sequential test
    success = await sequential_test_manager.start_sequential_test(
        sequential_test_id,
        selected_apis,
        request.session_id
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
