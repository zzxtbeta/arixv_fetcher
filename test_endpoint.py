#!/usr/bin/env python3
"""
Test script for the modified /data/fetch-arxiv-by-id endpoint
Tests the new OpenAlex + Tavily integration
"""

import requests
import json
import time

def test_fetch_arxiv_endpoint():
    """Test the /data/fetch-arxiv-by-id endpoint with sample arXiv IDs"""
    
    base_url = "http://localhost:8000"
    endpoint = "/data/fetch-arxiv-by-id"
    
    # Test with a few sample arXiv IDs (comma-separated)
    test_ids_str = "2401.00001,2312.15000"
    
    print("Testing modified /data/fetch-arxiv-by-id endpoint...")
    print("=" * 60)
    
    print(f"\nTesting with arXiv IDs: {test_ids_str}")
    print("-" * 40)
    
    try:
        # Make the API request with query parameters
        response = requests.post(
            f"{base_url}{endpoint}",
            params={"ids": test_ids_str},
            timeout=120  # 2 minutes timeout for processing
        )
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("Request successful!")
            print(f"Fetched: {result.get('fetched', 0)} papers")
            print(f"Inserted: {result.get('inserted', 0)} papers")
            print(f"Skipped: {result.get('skipped', 0)} papers")
            
            # Check if we have processing details
            if 'processing_details' in result:
                details = result['processing_details']
                print(f"Processing Status: {details.get('status', 'unknown')}")
                
        elif response.status_code == 422:
            print("Validation error:")
            print(json.dumps(response.json(), indent=2))
            
        elif response.status_code == 500:
            print("Server error:")
            error_data = response.json()
            print(f"Error: {error_data.get('detail', 'Unknown error')}")
            
        else:
            print(f"Unexpected status code: {response.status_code}")
            print(response.text)
            
    except requests.exceptions.Timeout:
        print("Request timed out (this is normal for complex processing)")
        
    except requests.exceptions.ConnectionError:
        print("Connection error - is the server running on port 8000?")
        
    except Exception as e:
        print(f"Unexpected error: {e}")
    
    print("\n" + "=" * 60)
    print("Test completed!")

if __name__ == "__main__":
    test_fetch_arxiv_endpoint()
