import requests
import json

# Test the upload-papers-json endpoint
url = "http://localhost:8000/data/upload-papers-json"

# Read the test JSON file
with open("test_papers.json", "rb") as f:
    files = {"file": ("test_papers.json", f, "application/json")}
    
    try:
        response = requests.post(url, files=files)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"\nSuccess! Session ID: {result.get('session_id')}")
            print(f"Total papers: {result.get('total_papers')}")
            print(f"Batch size: {result.get('batch_size')}")
        else:
            print(f"\nError: {response.status_code}")
            
    except Exception as e:
        print(f"Error: {e}")