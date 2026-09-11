#!/usr/bin/env python3
"""Test script to verify custom suggestions feature."""

import requests
import json

API_BASE = "http://localhost:9000"

# Step 1: Upload a test Excel file (assuming one exists)
# For this test, we'll simulate by using an existing upload_id
# You should replace this with a real upload_id from your uploads

# If you need to upload, uncomment:
# with open('path/to/test_excel.xlsx', 'rb') as f:
#     response = requests.post(f"{API_BASE}/api/v1/load-test/upload-excel", files={'file': f})
#     upload_data = response.json()
#     upload_id = upload_data['upload_id']

# For testing, let's assume there's a recent upload
# You'll need to replace this with actual values

upload_id = "c82ac38d-bbc3-4d2a-9c00-bab7e21ab117"  # Fresh upload
api_name = "Login"  # API name from the config

# Step 2: Call agentic-analyze with custom suggestions
print("🧪 Testing Custom Suggestions Feature")
print("=" * 80)

suggestions = "generate emails only with @gmail.com"
print(f"📝 Suggestion: {suggestions}")
print()

url = f"{API_BASE}/api/v1/load-test/agentic-analyze"
params = {
    "upload_id": upload_id,
    "api_name": api_name,
    "llm_provider": "groq"
}

# Send request with suggestions in body
request_body = {
    "custom_suggestions": suggestions
}

print(f"🌐 Calling: {url}")
print(f"📋 Params: {params}")
print(f"📦 Body: {request_body}")
print()

try:
    response = requests.post(url, params=params, json=request_body, timeout=120)

    print(f"📊 Status Code: {response.status_code}")

    if response.status_code == 200:
        data = response.json()

        print("\n✅ Response received!")
        print("=" * 80)

        # Check if validated_suggestions was processed
        print(f"API Type: {data.get('api_type')}")
        print(f"Recommended Users: {data.get('recommendations', {}).get('users')}")
        print(f"Data Generation Method: {data.get('data_generation_method')}")
        print(f"Generated Data Count: {len(data.get('test_data', []))}")

        # Check the generated emails
        print("\n📧 Generated Emails:")
        test_data = data.get('test_data', [])
        if test_data:
            for i, entry in enumerate(test_data[:10], 1):
                email = entry.get('email') or entry.get('username')
                if email:
                    print(f"   {i}. {email}")
                    # Check if it's @gmail.com
                    if '@gmail.com' not in str(email):
                        print(f"      ❌ NOT @gmail.com!")
                    else:
                        print(f"      ✅ Correct!")

        print("\n" + "=" * 80)
        print("💾 Full response saved to test_suggestions_response.json")

        with open('test_suggestions_response.json', 'w') as f:
            json.dump(data, f, indent=2)
    else:
        print(f"\n❌ Error: {response.status_code}")
        print(response.text)

except Exception as e:
    print(f"\n❌ Exception: {e}")
    import traceback
    traceback.print_exc()
