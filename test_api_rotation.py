#!/usr/bin/env python3
"""Test script for Tavily API key rotation functionality."""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from agent.utils import (
    get_tavily_client, 
    rotate_tavily_api_key, 
    search_person_role_with_tavily
)

# Import global variables directly
import agent.utils as utils

def test_api_key_rotation():
    """Test the API key rotation functionality."""
    print("Testing Tavily API Key Rotation")
    print("=" * 40)
    
    # Print available API keys (masked for security)
    print(f"Available API keys: {len(utils._TAVILY_API_KEYS)}")
    for i, key in enumerate(utils._TAVILY_API_KEYS):
        masked_key = key[:10] + "..." + key[-5:] if len(key) > 15 else key
        print(f"  {i+1}. {masked_key}")
    
    print(f"\nCurrent API key index: {utils._CURRENT_TAVILY_KEY_INDEX}")
    
    # Test getting client
    print("\nTesting get_tavily_client()...")
    client = get_tavily_client()
    if client:
        print("✓ Successfully got Tavily client")
    else:
        print("✗ Failed to get Tavily client")
        return
    
    # Test API key rotation
    print("\nTesting rotate_tavily_api_key()...")
    old_index = utils._CURRENT_TAVILY_KEY_INDEX
    success = rotate_tavily_api_key()
    if success:
        print(f"✓ Successfully rotated from index {old_index} to {utils._CURRENT_TAVILY_KEY_INDEX}")
    else:
        print("✗ Failed to rotate API key")
    
    # Test search function with rotation
    print("\nTesting search_person_role_with_tavily()...")
    result = search_person_role_with_tavily(
        name="John Smith",
        affiliation="MIT"
    )
    
    if result and result.get('search_successful'):
        print("✓ Search completed successfully")
        print(f"  Query: {result.get('query', 'N/A')}")
        print(f"  Results count: {len(result.get('results', []))}")
    else:
        print("✗ Search failed")
        if result:
            print(f"  Error: {result.get('error', 'Unknown error')}")
    
    print("\nTest completed.")

if __name__ == "__main__":
    test_api_key_rotation()