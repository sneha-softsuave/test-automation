#!/bin/bash

cd "/home/admin1/project - POCs/test-automation-project/test-automation"

echo "🔄 Uploading Excel file..."
UPLOAD_ID=$(curl -s -X POST "http://localhost:9000/api/v1/load-test/upload-excel" \
  -F "file=@uploads/load_test_configs/c50e5118-f014-4092-8c29-7d8d376c0f16_Load test file multi-user with data (5).xlsx" \
  | python3 -c "import sys, json; data = json.load(sys.stdin); print(data['upload_id'])")

echo "✅ Upload ID: $UPLOAD_ID"
echo ""
echo "🧪 Testing with suggestion: 'generate emails only with @gmail.com'"
echo ""

curl -s -X POST "http://localhost:9000/api/v1/load-test/agentic-analyze?upload_id=$UPLOAD_ID&api_name=Login&llm_provider=groq" \
  -H "Content-Type: application/json" \
  -d '{"custom_suggestions": "generate emails only with @gmail.com"}' \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
emails = [entry.get('email') for entry in data.get('test_data', [])[:20]]
print('📧 Generated Emails:')
print('=' * 80)
for i, email in enumerate(emails, 1):
    status = '✅' if '@gmail.com' in email else '❌ NOT @gmail.com'
    print(f'{i}. {email} - {status}')
print('=' * 80)
gmail_count = sum(1 for e in emails if '@gmail.com' in e)
print(f'\\n📊 Result: {gmail_count}/{len(emails)} emails are @gmail.com')
"
