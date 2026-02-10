# Load Testing System - Complete Guide 📊

> **Comprehensive documentation for the AI-powered load testing system**

---

## Table of Contents

1. [Overview](#overview)
2. [Features](#features)
3. [Architecture](#architecture)
4. [Getting Started](#getting-started)
5. [Test Modes](#test-modes)
6. [Excel Configuration](#excel-configuration)
7. [Report System](#report-system)
8. [API Reference](#api-reference)
9. [Troubleshooting](#troubleshooting)
10. [Best Practices](#best-practices)

---

## Overview

The Load Testing System is an AI-powered tool for testing API performance under load. It supports both manual single-API testing and automated sequential testing of multiple APIs.

### Key Capabilities

- ✅ **Manual Mode**: Test a single API with custom configuration
- ✅ **Sequential Mode**: Auto-execute multiple APIs in order
- ✅ **Real-time Metrics**: Live updates via Server-Sent Events (SSE)
- ✅ **Excel Integration**: Upload and parse test configurations
- ✅ **Interactive Reports**: HTML reports with charts and metrics
- ✅ **Persistent Sessions**: Navigate away without losing test progress

---

## Features

### Test Execution

| Feature | Manual Mode | Sequential Mode |
|---------|-------------|-----------------|
| API Selection | Single API | Multiple APIs |
| Configuration | UI Form | Excel File |
| Execution | User triggers | Auto-sequential |
| Real-time Updates | ✅ | ✅ |
| Reports | Per API | Combined |

### Configuration Options

- **Users**: Number of concurrent users (default: 10)
- **Spawn Rate**: Users spawned per second (default: 2.0)
- **Run Time**: Test duration (e.g., "1m", "30s", "2h")
- **Method**: HTTP method (GET, POST, PUT, DELETE, PATCH)
- **Headers**: Custom HTTP headers
- **Body**: Request payload (for POST/PUT)

### Report Features

- **Individual Charts**: Each API gets its own response time chart
- **Metric Cards**: Users, RPS, Avg Response, Failure Rate
- **Stats Tables**: Complete breakdown of all metrics
- **Summary Pie Chart**: Failure comparison across all APIs
- **Download Options**: Preview, JSON export, HTML export

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────┐
│              Frontend (React)               │
│  ┌─────────────────────────────────────┐   │
│  │  LoadTestDashboard (Main UI)        │   │
│  │  • Manual/Sequential mode toggle    │   │
│  │  • API selection & configuration    │   │
│  │  • Real-time metrics display        │   │
│  └─────────────────────────────────────┘   │
│  ┌─────────────────────────────────────┐   │
│  │  LoadTestReports (Report Viewer)    │   │
│  │  • Report display with iframe       │   │
│  │  • Refresh with cache clearing      │   │
│  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
                    ↕ SSE/REST
┌─────────────────────────────────────────────┐
│            Backend (FastAPI)                │
│  ┌─────────────────────────────────────┐   │
│  │  Load Test Routes                   │   │
│  │  • /upload-excel                    │   │
│  │  • /start-from-excel                │   │
│  │  • /start-sequential                │   │
│  │  • /stop/{test_id}                  │   │
│  │  • /current-report                  │   │
│  └─────────────────────────────────────┘   │
│  ┌─────────────────────────────────────┐   │
│  │  SequentialTestManager              │   │
│  │  • Orchestrates multiple API tests  │   │
│  │  • Collects results in order        │   │
│  └─────────────────────────────────────┘   │
│  ┌─────────────────────────────────────┐   │
│  │  LocustManager                      │   │
│  │  • Manages Locust subprocesses      │   │
│  │  • Streams metrics via polling      │   │
│  │  • Caches final metrics             │   │
│  └─────────────────────────────────────┘   │
│  ┌─────────────────────────────────────┐   │
│  │  LoadTestReportGenerator            │   │
│  │  • Generates HTML reports           │   │
│  │  • Creates individual API charts    │   │
│  │  • Adds summary pie chart           │   │
│  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
                    ↕
┌─────────────────────────────────────────────┐
│            Locust (Load Engine)             │
│  • Generates load on target APIs           │
│  • Collects performance metrics            │
│  • Runs in subprocess per test             │
└─────────────────────────────────────────────┘
```

### Data Flow

#### Manual Test Flow
```
1. User uploads Excel → Parse APIs
2. User selects API → Pre-fill form
3. User configures test → Users, spawn rate, run time
4. User clicks "Start Test"
5. Backend generates Locustfile
6. Backend starts Locust subprocess
7. Backend streams metrics via SSE
8. Frontend displays real-time updates
9. Test completes
10. Backend generates HTML report
11. User views report
```

#### Sequential Test Flow
```
1. User uploads Excel → Parse APIs
2. User selects multiple APIs
3. User clicks "Start Sequential Test"
4. Backend starts SequentialTestManager
5. For each API in order:
   a. Generate Locustfile
   b. Start Locust subprocess
   c. Stream metrics via SSE
   d. Collect results
6. All APIs complete
7. Backend generates combined HTML report
8. User views report with all APIs
```

---

## Getting Started

### Prerequisites

- Python 3.8+
- Node.js 16+
- Locust installed (`pip install locust`)

### Backend Setup

```bash
# Navigate to project directory
cd test-automation

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start backend (with auto-reload exclusions)
uvicorn app.main:app --reload --port 9000 --host 0.0.0.0 \
  --reload-exclude "generated_locustfiles/*" \
  --reload-exclude "load_test_results/*" \
  --reload-exclude "uploads/*"
```

**Important**: Always use `--reload-exclude` flags to prevent uvicorn from reloading when Locustfiles are generated.

### Frontend Setup

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

### Access Application

- **Frontend**: http://localhost:5173
- **Backend**: http://localhost:9000
- **API Docs**: http://localhost:9000/docs

---

## Test Modes

### Manual Mode (Single API)

**Use Case**: Test a single API with specific configuration

**Steps**:
1. Toggle to "Manual Mode"
2. Upload Excel file (optional, for API library)
3. Select an API from dropdown
4. Configure test parameters:
   - Users (e.g., 10)
   - Spawn Rate (e.g., 2.0)
   - Run Time (e.g., "1m")
5. Click "Start Test"
6. Monitor real-time metrics
7. View report when complete

**Features**:
- Pre-fill configuration from Excel if available
- Edit configuration before running
- Real-time metrics display
- Stop test at any time

### Sequential Mode (Multiple APIs)

**Use Case**: Test multiple APIs automatically in sequence

**Steps**:
1. Toggle to "Sequential Mode"
2. Upload Excel file with multiple APIs
3. Select APIs to test (in desired order)
4. Click "Start Sequential Test"
5. Monitor progress:
   - Current API being tested
   - Progress bar (e.g., 2/5 APIs)
   - Real-time metrics for current API
6. View combined report when complete

**Features**:
- Auto-execute multiple APIs
- Configuration from Excel (or defaults)
- Single comprehensive report
- APIs appear in execution order
- Stop all tests at once

---

## Excel Configuration

### File Format

**File**: `.xlsx` (Excel format)

**Required Sheet**: First sheet (any name)

**Required Columns**:
- `API Name` or `Name`: API identifier
- `Base URL`: API base URL
- `Endpoint`: API endpoint path
- `Method`: HTTP method (GET, POST, etc.)

**Optional Columns**:
- `Users`: Number of concurrent users
- `Spawn Rate`: Users per second
- `Run Time`: Test duration (e.g., "1m", "30s")
- `Headers`: JSON string of headers
- `Body`: JSON string of request body

### Example Excel Structure

| API Name | Base URL | Endpoint | Method | Users | Spawn Rate | Run Time |
|----------|----------|----------|--------|-------|------------|----------|
| Login | https://api.example.com | /auth/login | POST | 10 | 2.0 | 1m |
| Health Check | https://api.example.com | /health | GET | 5 | 1.0 | 30s |
| Get Profile | https://api.example.com | /user/profile | GET | 15 | 3.0 | 2m |

### Default Values

If not specified in Excel:
- **Users**: 10
- **Spawn Rate**: 2.0
- **Run Time**: "5m"

### Headers Example

```json
{
  "Authorization": "Bearer token123",
  "Content-Type": "application/json"
}
```

### Body Example (POST/PUT)

```json
{
  "username": "user@example.com",
  "password": "password123"
}
```

---

## Report System

### Report Structure

```
📄 Load Test Report
├─ Header
│  └─ Title, Test ID, Timestamp
├─ Summary Cards
│  ├─ Total APIs Tested
│  ├─ Total Requests
│  ├─ Avg Requests/sec
│  ├─ Avg Response Time
│  ├─ Total Duration
│  └─ Total Failures
├─ Download Buttons
│  ├─ 👁️ Preview Report
│  ├─ 📥 Download JSON
│  └─ 📄 Download HTML
├─ API #1 (Execution Order)
│  ├─ Header (Name, Method, Endpoint)
│  ├─ 📊 Response Time Chart
│  │  └─ Min, Avg, Median, 95th, 99th, Max
│  ├─ Metric Cards
│  │  ├─ Users
│  │  ├─ Requests/sec
│  │  ├─ Avg Response Time
│  │  └─ Failure Rate
│  └─ Stats Table
│     └─ Complete metrics breakdown
├─ API #2
│  └─ (same structure)
├─ API #3
│  └─ (same structure)
└─ 🔴 Failure Comparison (Pie Chart)
   └─ Shows failure distribution across all APIs
```

### Chart Types

#### Individual API Chart
- **Type**: Bar Chart
- **Metrics**: Min, Avg, Median, 95th Percentile, 99th Percentile, Max
- **Colors**: Green → Red gradient
- **Location**: After API header, before metrics

#### Summary Pie Chart
- **Type**: Pie Chart
- **Data**: Total failures per API
- **Legend**: Right side
- **Location**: After all API sections

### Report Actions

#### Preview Report
- Opens report in new browser tab
- Full functionality (charts, interactions)
- No download required

#### Download JSON
- Structured data export
- File: `load_test_report_{test_id}.json`
- For programmatic analysis

#### Download HTML
- Complete HTML report
- File: `load_test_report_{test_id}.html`
- Can be opened offline (needs internet for Chart.js)

### Report Refresh

**Feature**: Clear cache and reload latest report

**How to Use**:
1. Navigate to Reports section
2. Click "Refresh" button
3. Report clears immediately
4. Loading spinner appears
5. Latest report loads

**Cache Clearing**:
- Timestamp query parameters
- HTTP cache control headers
- React key-based iframe remount

---

## API Reference

### Upload Excel

```http
POST /api/v1/load-test/upload-excel
Content-Type: multipart/form-data

Body:
  file: <Excel file>

Response:
{
  "apis": [
    {
      "name": "Login",
      "base_url": "https://api.example.com",
      "endpoint": "/auth/login",
      "method": "POST",
      "users": 10,
      "spawn_rate": 2.0,
      "run_time": "1m"
    }
  ]
}
```

### Start Manual Test

```http
POST /api/v1/load-test/start-from-excel
Content-Type: application/json

Body:
{
  "api": {
    "name": "Login",
    "base_url": "https://api.example.com",
    "endpoint": "/auth/login",
    "method": "POST"
  },
  "config": {
    "users": 10,
    "spawn_rate": 2.0,
    "run_time": "1m"
  },
  "session_id": "loadtest_1707562800"
}

Response:
{
  "test_id": "test_1707562800_abc123",
  "message": "Test started"
}
```

### Start Sequential Test

```http
POST /api/v1/load-test/start-sequential
Content-Type: application/json

Body:
{
  "apis": [
    {
      "name": "Login",
      "base_url": "https://api.example.com",
      "endpoint": "/auth/login",
      "method": "POST",
      "users": 10,
      "spawn_rate": 2.0,
      "run_time": "1m"
    },
    {
      "name": "Health",
      "base_url": "https://api.example.com",
      "endpoint": "/health",
      "method": "GET"
    }
  ],
  "session_id": "loadtest_1707562800"
}

Response:
{
  "sequential_test_id": "seq_1707562800_xyz789",
  "message": "Sequential test started",
  "total_apis": 2
}
```

### Stop Test

```http
POST /api/v1/load-test/stop/{test_id}

Response:
{
  "message": "Test stopped",
  "test_id": "test_1707562800_abc123"
}
```

### Stop Sequential Test

```http
POST /api/v1/load-test/stop-sequential/{sequential_test_id}

Response:
{
  "message": "Sequential test stopped",
  "sequential_test_id": "seq_1707562800_xyz789"
}
```

### Get Current Report

```http
GET /api/v1/load-test/current-report

Response:
{
  "filename": "report_test_123.html",
  "test_id": "test_123",
  "type": "manual",
  "timestamp": "2026-02-10T10:30:45",
  "api_name": "Login"
}
```

### Get Report Content

```http
GET /api/v1/load-test/report/{filename}

Response: HTML content
```

---

## Troubleshooting

### Backend Issues

#### Uvicorn Auto-Reload Breaking Tests

**Symptom**: Tests stop when Locustfiles are generated

**Cause**: Uvicorn reloads when files change, killing active tests

**Solution**: Start uvicorn with exclusions
```bash
uvicorn app.main:app --reload --port 9000 --host 0.0.0.0 \
  --reload-exclude "generated_locustfiles/*" \
  --reload-exclude "load_test_results/*" \
  --reload-exclude "uploads/*"
```

#### SSE Connection Lost

**Symptom**: Real-time updates stop

**Cause**: Server restart or navigation

**Solution**: SSE automatically reconnects (implemented via singleton pattern)

#### Metrics Showing 0 After Test

**Symptom**: Final metrics show 0 users, 0 requests

**Cause**: Locust process exits, metrics unavailable

**Solution**: System caches metrics during execution (already implemented)

### Frontend Issues

#### Report Not Refreshing

**Symptom**: Old report shows after clicking refresh

**Cause**: Browser cache

**Solution**: Refresh button now clears cache (implemented)

#### Charts Not Showing

**Symptom**: Empty chart containers

**Possible Causes**:
1. No internet connection (Chart.js from CDN)
2. JavaScript disabled
3. Browser too old

**Solutions**:
1. Check internet connection
2. Enable JavaScript
3. Update browser
4. Check browser console for errors

#### Download Buttons Not Working

**Symptom**: Clicking buttons does nothing

**Possible Causes**:
1. JavaScript error
2. Popup blocker (Preview button)
3. Download blocked by browser

**Solutions**:
1. Check browser console
2. Allow popups
3. Enable downloads in browser settings

### Test Execution Issues

#### Test Starts But Metrics Don't Update

**Check**:
1. Backend logs for errors
2. SSE connection in Network tab
3. Locust process running: `ps aux | grep locust`

**Solution**:
- Restart backend
- Check firewall settings
- Verify Locust installed: `locust --version`

#### Sequential Test Stops Unexpectedly

**Check**:
1. Backend logs for errors
2. Individual API test results
3. Network connectivity to target APIs

**Common Causes**:
- Target API timeout
- Network error
- Invalid configuration

---

## Best Practices

### Test Configuration

#### Choosing User Count
- **Small**: 1-10 users for basic testing
- **Medium**: 10-50 users for moderate load
- **Large**: 50-200 users for high load
- **Stress**: 200+ users for stress testing

#### Spawn Rate Guidelines
- **Gentle**: 1-2 users/sec (gradual ramp-up)
- **Normal**: 2-5 users/sec (standard load)
- **Aggressive**: 5-10 users/sec (quick ramp-up)

#### Run Time Recommendations
- **Quick**: 30s-1m for smoke tests
- **Standard**: 1m-5m for load tests
- **Endurance**: 10m-30m for stability tests
- **Soak**: 1h+ for long-term testing

### Excel Best Practices

1. **Use Descriptive Names**: "Login API" instead of "API1"
2. **Group Related APIs**: Keep similar APIs together
3. **Set Realistic Loads**: Match production traffic patterns
4. **Document Headers**: Add comments for complex headers
5. **Test Incrementally**: Start small, increase gradually

### Sequential Testing

1. **Order Matters**: Put critical APIs first
2. **Allow Cooldown**: Space out intensive tests
3. **Monitor Progress**: Watch real-time updates
4. **Save Results**: Download reports after completion
5. **Analyze Trends**: Compare multiple test runs

### Report Analysis

#### Key Metrics to Watch

**Response Time**:
- Avg < 200ms: Excellent
- Avg < 500ms: Good
- Avg < 1000ms: Acceptable
- Avg > 1000ms: Needs optimization

**Failure Rate**:
- < 0.1%: Excellent
- < 1%: Good
- < 5%: Acceptable
- \> 5%: Critical issue

**Throughput (RPS)**:
- Compare to expected load
- Check if meets SLA
- Monitor for degradation

#### Chart Interpretation

**Individual API Charts**:
- High max values: Outliers or timeouts
- Wide 95th-99th gap: Inconsistent performance
- All metrics high: Slow API or overload

**Failure Pie Chart**:
- Identify problem APIs
- Focus optimization efforts
- Compare failure distribution

---

## File Structure

```
test-automation/
├── app/
│   ├── api/routes/
│   │   └── load_test.py          # Load test API endpoints
│   ├── services/
│   │   ├── locust_manager.py     # Locust subprocess manager
│   │   ├── sequential_test_manager.py  # Sequential orchestrator
│   │   ├── load_test_report_generator.py  # HTML report generator
│   │   ├── dynamic_locust_generator.py  # Locustfile generator
│   │   └── excel_to_load_test_parser.py  # Excel parser
│   └── models/
│       └── load_test_models.py   # Pydantic models
├── frontend/src/
│   ├── components/LoadTesting/
│   │   ├── LoadTestDashboard.tsx  # Main UI
│   │   └── LoadTestReports.tsx    # Report viewer
│   ├── hooks/
│   │   └── useLoadTestSSE.ts      # SSE connection hook
│   └── store/
│       └── useStore.ts            # Zustand state management
├── generated_locustfiles/         # Generated Locustfiles
├── load_test_results/             # Test results and reports
└── uploads/                       # Uploaded Excel files
```

---

## Summary

### What You Get

✅ **Two Test Modes**: Manual and Sequential
✅ **Excel Integration**: Easy configuration
✅ **Real-time Updates**: Live metrics via SSE
✅ **Interactive Reports**: Charts and detailed stats
✅ **Persistent Sessions**: Navigate without losing tests
✅ **Export Options**: JSON and HTML downloads
✅ **Execution Order**: APIs in specified sequence
✅ **Failure Analysis**: Pie chart comparison

### Quick Start Checklist

- [ ] Install dependencies (Python + Node.js)
- [ ] Start backend with reload exclusions
- [ ] Start frontend
- [ ] Upload Excel file
- [ ] Select test mode (Manual/Sequential)
- [ ] Configure or select APIs
- [ ] Start test
- [ ] Monitor real-time metrics
- [ ] View and download report

---

**Version**: 3.0
**Last Updated**: February 10, 2026
**Status**: Production Ready ✅
