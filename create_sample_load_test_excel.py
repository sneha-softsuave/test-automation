"""Create a sample Excel file for load testing."""

import pandas as pd
from pathlib import Path

# Sample API configurations
data = [
    {
        'API Name': 'Get All Posts',
        'Base URL': 'https://jsonplaceholder.typicode.com',
        'Endpoint': '/posts',
        'Method': 'GET',
        'Headers': '{"Content-Type": "application/json"}',
        'Payload': '',
        'Query Params': '',
        'Auth Type': 'none',
        'Auth Token': '',
        'Description': 'Fetch all posts from JSONPlaceholder API'
    },
    {
        'API Name': 'Get Single Post',
        'Base URL': 'https://jsonplaceholder.typicode.com',
        'Endpoint': '/posts/1',
        'Method': 'GET',
        'Headers': '{"Content-Type": "application/json"}',
        'Payload': '',
        'Query Params': '',
        'Auth Type': 'none',
        'Auth Token': '',
        'Description': 'Fetch a single post by ID'
    },
    {
        'API Name': 'Create Post',
        'Base URL': 'https://jsonplaceholder.typicode.com',
        'Endpoint': '/posts',
        'Method': 'POST',
        'Headers': '{"Content-Type": "application/json"}',
        'Payload': '{"title": "Test Post", "body": "This is a test", "userId": 1}',
        'Query Params': '',
        'Auth Type': 'none',
        'Auth Token': '',
        'Description': 'Create a new post'
    },
    {
        'API Name': 'Update Post',
        'Base URL': 'https://jsonplaceholder.typicode.com',
        'Endpoint': '/posts/1',
        'Method': 'PUT',
        'Headers': '{"Content-Type": "application/json"}',
        'Payload': '{"id": 1, "title": "Updated Post", "body": "Updated content", "userId": 1}',
        'Query Params': '',
        'Auth Type': 'none',
        'Auth Token': '',
        'Description': 'Update an existing post'
    },
    {
        'API Name': 'Delete Post',
        'Base URL': 'https://jsonplaceholder.typicode.com',
        'Endpoint': '/posts/1',
        'Method': 'DELETE',
        'Headers': '{"Content-Type": "application/json"}',
        'Payload': '',
        'Query Params': '',
        'Auth Type': 'none',
        'Auth Token': '',
        'Description': 'Delete a post'
    },
]

# Create DataFrame
df = pd.DataFrame(data)

# Create output directory
output_dir = Path('test_data')
output_dir.mkdir(exist_ok=True)

# Save to Excel
output_file = output_dir / 'sample_load_test_apis.xlsx'
df.to_excel(output_file, index=False, engine='openpyxl')

print(f"✅ Sample Excel file created: {output_file}")
print(f"   Total APIs: {len(data)}")
print(f"   Methods: {', '.join(set(d['Method'] for d in data))}")
