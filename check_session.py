import requests
import json
import time

# Check session status
session_id = "batch_20250826_122344"
url = f"http://localhost:8000/data/session-status/{session_id}"

try:
    response = requests.get(url)
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"\nSession Status: {result.get('status')}")
        print(f"Total Papers: {result.get('total_papers')}")
        print(f"Processed Papers: {result.get('processed_papers')}")
        print(f"Total Inserted: {result.get('total_inserted')}")
        print(f"Total Skipped: {result.get('total_skipped')}")
        print(f"Progress: {result.get('progress_percentage', 0):.1f}%")
        
        if result.get('status') == 'processing':
            print("\nBatch processing is still running...")
        elif result.get('status') == 'completed':
            print("\nBatch processing completed successfully!")
        else:
            print(f"\nUnexpected status: {result.get('status')}")
    else:
        print(f"Error: {response.text}")
        
except Exception as e:
    print(f"Error: {e}")