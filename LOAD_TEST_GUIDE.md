# Load Testing - Quick Start Guide

A comprehensive guide to using the load testing features of the Test Automation System.

---

## Table of Contents

1. [Overview](#overview)
2. [Getting Started](#getting-started)
3. [Testing Modes](#testing-modes)
4. [Excel Configuration](#excel-configuration)
5. [Manual Load Testing](#manual-load-testing)
6. [AI-Powered Load Testing](#ai-powered-load-testing)
7. [Sequential Testing](#sequential-testing)
8. [Real-Time Monitoring](#real-time-monitoring)
9. [Reports & Analysis](#reports--analysis)
10. [Troubleshooting](#troubleshooting)

---

## Overview

The Test Automation System provides powerful load testing capabilities with two modes:

- **Manual Mode**: Direct Excel-to-test execution for users who know their requirements
- **AI-Powered Mode**: Intelligent analysis and optimization using AI agents

Both modes support:
- Multi-user testing with unique credentials
- Real-time metrics and terminal logs
- Sequential execution of multiple APIs
- Interactive HTML reports

---

## Getting Started

### Prerequisites

1. **Backend running** on port 9000
2. **Frontend running** on port 3000
3. **Excel file** with API configurations

### Quick Setup

```bash
# Start backend
bash start_backend.sh

# Start frontend (in another terminal)
cd frontend && npm run dev
```

Access the application at `http://localhost:3000`

---

## Testing Modes

### Manual Mode (Default)

Best for:
- Quick tests with known configurations
- Repeating previous test scenarios
- When you have pre-defined test parameters

### AI-Powered Mode

Best for:
- First-time API testing
- Optimization and performance tuning
- Learning optimal test configurations
- Automatic test data generation

Toggle between modes using the **"AI-Powered Mode"** switch in the dashboard.

---

## Excel Configuration

### Required Sheets

#### 1. APIs Sheet
Defines your API endpoints:

| API Name | Endpoint | Method | Base URL |
|----------|----------|--------|----------|
| Login | /api/auth/login | POST | https://example.com |

#### 2. Payload Sheet (Optional)
Defines request payloads with template variables:

| API Name | Payload |
|----------|---------|
| Login | {"email": "{{email}}", "password": "{{password}}"} |

#### 3. Test Data Sheet (Optional)
Provides multi-user test data:

| API Name | email | password |
|----------|-------|----------|
| Login | user1@test.com | pass123 |
| Login | user2@test.com | pass456 |

#### 4. Config Sheet (Optional)
Specifies load test parameters:

| API Name | users | spawn_rate | run_time |
|----------|-------|------------|----------|
| Login | 20 | 5 | 1m |

**Default values** (if Config sheet is missing):
- Users: 10
- Spawn Rate: 2 users/second
- Run Time: 5m (5 minutes)

### Template Variables

Use `{{variable}}` syntax in payloads to reference test data:

```json
{
  "email": "{{email}}",
  "password": "{{password}}",
  "userId": "{{userId}}"
}
```

For detailed Excel formatting, see `docs/EXCEL_FORMAT_GUIDE.md`

---

## Manual Load Testing

### Step 1: Upload Excel File

1. Click **"Upload Excel"** button
2. Select your Excel file
3. System parses and displays available APIs

### Step 2: Configure Test

1. **Select an API** from the list
2. **Configure parameters** (optional - pre-filled from Excel):
   - Number of Users
   - Spawn Rate (users/second)
   - Run Time (e.g., "1m", "30s", "2h")
3. View API details (endpoint, method, payload)

### Step 3: Start Test

1. Click **"Start Load Test"** button
2. System generates Locustfile and starts execution
3. Watch real-time metrics and terminal logs

### Step 4: Monitor Progress

**Live Metrics Cards:**
- Total Requests
- Total Failures
- Success Rate (%)
- Avg Response Time (ms)

**Live Charts:**
- Response Time Over Time
- Request Rate Over Time
- Failure Rate

**Terminal Logs:**
- Real-time log streaming
- Color-coded output (success, error, info)
- Auto-scroll feature

### Step 5: View Report

1. Test completes automatically after run time
2. Click **"View Latest Report"** button
3. Interactive HTML report opens in new tab

---

## AI-Powered Load Testing

### Step 1: Enable AI Mode

Toggle **"AI-Powered Mode"** switch in dashboard

### Step 2: Analyze API

1. Upload Excel file
2. Select an API
3. Click **"🤖 Analyze with AI"** button

### Step 3: Review AI Recommendations

AI analyzes your API and provides:

**Configuration Recommendations:**
- Optimal number of users
- Recommended spawn rate
- Think time (delay between requests)
- Data cycling mode (round-robin, sequential, random)

**AI Reasoning:**
- Why these parameters are recommended
- Expected behavior and performance
- Best practices for your API type

**Test Data Generation:**
- Toggle ON: AI generates realistic test data
- Toggle OFF: Use Excel test data

### Step 4: Apply Recommendations

1. Review AI suggestions
2. Toggle test data generation (optional)
3. Click **"Apply AI Recommendations"** button
4. System updates configuration

### Step 5: Start AI-Optimized Test

1. Click **"Start Load Test"** button
2. System uses AI-generated Locustfile
3. Monitor real-time metrics and logs

### Step 6: View AI-Enhanced Report

Report includes:
- Standard load test metrics
- **AI Analysis Section**:
  - Bottlenecks detected
  - Root cause analysis
  - SLA compliance status
  - Priority recommendations (High/Medium/Low impact)
  - Capacity assessment

---

## Sequential Testing

Run multiple APIs one after another automatically.

### Step 1: Select Multiple APIs

1. Upload Excel file
2. Click checkboxes for **multiple APIs**
3. Click **"Start Sequential Test"** button

### Step 2: Monitor Progress

**Overall Progress Bar:**
- Shows completion percentage across all APIs

**Current API Status:**
- Name of running API
- Individual progress
- Real-time metrics

**Queue Status:**
- List of pending APIs
- Completed APIs (green checkmark)

### Step 3: View Combined Report

After all APIs complete:
- Single HTML report with all API results
- Individual sections per API
- Comparative analysis

---

## Real-Time Monitoring

### Metrics Updates

**Frequency:** Every 2 seconds

**Metrics Displayed:**
- Total Requests
- Total Failures
- Success Rate (%)
- Average Response Time (ms)
- P95 Response Time (ms)
- P99 Response Time (ms)
- Requests Per Second (RPS)

### Terminal Logs

**Log Types:**
- `[INIT]` - User initialization
- `[REQUEST]` - API request sent
- `[RESPONSE]` - Status code received
- `[SUCCESS]` - Successful request
- `[FAILURE]` - Failed request with error details

**Features:**
- Real-time streaming
- Auto-scroll to latest logs
- Color-coded output
- Copy/export functionality

### Charts

**Response Time Chart:**
- Line chart showing response time trend
- Updates every 2 seconds
- Shows P50, P95, P99 percentiles

**Request Rate Chart:**
- Bar chart showing requests per second
- Shows success vs failure breakdown

---

## Reports & Analysis

### Report Structure

**Summary Section:**
- Total Requests
- Success Rate
- Average Response Time
- Peak RPS

**Charts Section:**
- Response Time Distribution
- Request Rate Over Time
- Error Distribution

**Percentiles Table:**
- P50, P75, P90, P95, P99 response times

**AI Insights** (AI Mode only):
- Bottlenecks detected
- Root causes identified
- Priority recommendations
- Capacity assessment

### Downloading Reports

1. Click **"View Latest Report"** button
2. Report opens in new browser tab
3. Use browser's "Save Page" feature to download

### Report Storage

Reports are saved to:
- `load_test_results/report_{test_id}.html` (single API)
- `load_test_results/report_seq_{seq_id}.html` (sequential)

---

## Troubleshooting

### Excel Upload Fails

**Issue:** "Failed to parse Excel file"

**Solutions:**
- Verify Excel file format (.xlsx)
- Check required sheets exist (APIs, Payload, etc.)
- Ensure column headers match expected format
- Check for empty rows or cells

### Test Fails to Start

**Issue:** "Failed to start load test"

**Solutions:**
- Verify API configuration is complete
- Check network connectivity to target API
- Ensure valid user count and spawn rate
- Review terminal logs for error details

### No Metrics Displayed

**Issue:** Metrics cards show "0" or don't update

**Solutions:**
- Check if Locust process is running
- Verify backend is reachable (port 9000)
- Check browser console for SSE connection errors
- Refresh page and restart test

### Terminal Logs Not Appearing

**Issue:** Terminal tab is empty

**Solutions:**
- Verify SSE connection is active
- Check backend logs for errors
- Ensure Locust process is outputting logs
- Try restarting the test

### Report Not Generated

**Issue:** "No report available" message

**Solutions:**
- Ensure test completed successfully
- Check `load_test_results/` folder for report file
- Verify test ran for sufficient duration
- Review backend logs for report generation errors

---

## Advanced Features

### Multi-User Testing

Each Locust user gets unique credentials from test data:
- Round-robin assignment
- Unique email/password per user
- Prevents credential conflicts

See `docs/MULTI_USER_LOGIN_GUIDE.md` for details.

### Custom Runtime Formats

Supported formats:
- `30s` - 30 seconds
- `5m` - 5 minutes
- `1h` - 1 hour
- `90s` - 90 seconds

### AI Test Data Generation

When enabled:
- AI generates realistic test data using Faker library
- Supports common fields (email, password, name, address, phone)
- Ensures data diversity and uniqueness
- LLM fallback for domain-specific fields

---

## Additional Resources

For more detailed information, see documentation in the `docs/` folder:

- **LOAD_TEST_COMPLETE_GUIDE.md** - Complete technical architecture
- **EXCEL_FORMAT_GUIDE.md** - Detailed Excel formatting requirements
- **MULTI_USER_LOGIN_GUIDE.md** - Multi-user testing guide
- **LOGGING_GUIDE.md** - Application logging documentation
- **AI_AGENTIC_GUIDE.md** - AI agent system details
- **VENV_SETUP_COMPLETE.md** - Virtual environment setup

---

## Support

For issues or questions:
- Check `docs/` folder for detailed guides
- Review terminal logs for error messages
- Check backend logs at `backend_logs.txt`

---

**Happy Load Testing! 🚀**
