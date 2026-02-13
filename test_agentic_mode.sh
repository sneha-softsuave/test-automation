#!/bin/bash

echo "🤖 Testing AI-Powered Agentic Load Testing"
echo "=========================================="
echo ""

# Use the upload ID from your previous test
UPLOAD_ID="739b6f51-c198-442c-82d8-910d623fe0c8"
API_NAME="Login"

echo "📋 Configuration:"
echo "   • Upload ID: $UPLOAD_ID"
echo "   • API Name: $API_NAME"
echo ""

echo "🚀 Step 1: Triggering AI Analysis..."
echo "   (Watch your python3 run.py terminal for detailed agent logs!)"
echo ""

curl -X POST http://localhost:9000/api/v1/load-test/agentic-analyze \
  -H "Content-Type: application/json" \
  -d "{
    \"upload_id\": \"$UPLOAD_ID\",
    \"api_name\": \"$API_NAME\"
  }" \
  -w "\n\nHTTP Status: %{http_code}\n" \
  | python3 -m json.tool

echo ""
echo "=========================================="
echo "✅ AI Analysis Complete!"
echo ""
echo "Check your terminal running 'python3 run.py' to see:"
echo "   • 🤖 AGENT 1/6: ConfigParserAgent"
echo "   • 🤖 AGENT 2/6: DataGeneratorAgent (with credentials!)"
echo "   • 🤖 AGENT 3/6: LocustGeneratorAgent (with file preview!)"
echo "   • And more..."
echo ""
echo "Next: Use the recommendations from the response to start the test!"
