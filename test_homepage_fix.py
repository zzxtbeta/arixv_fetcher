#!/usr/bin/env python3
"""
Test script to verify homepage extraction and persistence fix in /data/fetch-arxiv-by-id endpoint
"""

import asyncio
import requests
import json
from dotenv import load_dotenv
from src.db.postgres_client import PostgreSQLClient

async def test_homepage_fix():
    """Test the homepage extraction fix with a new ArXiv paper"""
    
    # Load environment variables
    load_dotenv()
    
    print("Testing homepage extraction fix for /data/fetch-arxiv-by-id endpoint")
    print("=" * 70)
    
    # Test with a paper that should have authors with homepages
    test_paper_id = "2408.13442"  # Paper with authors from known institutions
    
    print(f"Testing with ArXiv paper ID: {test_paper_id}")
    print("-" * 50)
    
    # Call the API endpoint
    try:
        response = requests.post(
            "http://localhost:8000/data/fetch-arxiv-by-id",
            json={"arxiv_id": test_paper_id},
            timeout=300  # 5 minutes timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✓ API call successful")
            print(f"Response: {json.dumps(result, indent=2)}")
        else:
            print(f"✗ API call failed with status {response.status_code}")
            print(f"Response: {response.text}")
            return
            
    except Exception as e:
        print(f"✗ API call failed: {e}")
        return
    
    # Wait a moment for processing to complete
    await asyncio.sleep(2)
    
    # Check database for homepage data
    print("\n" + "=" * 50)
    print("Checking database for homepage data...")
    
    db_client = PostgreSQLClient()
    
    try:
        # Query for authors from this paper with homepage data
        authors_with_homepage = await db_client.select(
            "authors", 
            columns="author_name_en, email, homepage, citations, h_index",
            filters={"homepage__isnull": False},
            limit=20
        )
        
        if authors_with_homepage:
            print(f"✓ Found {len(authors_with_homepage)} authors with homepage data:")
            print("-" * 50)
            
            for author in authors_with_homepage:
                print(f"Name: {author['author_name_en']}")
                print(f"Email: {author['email'] or 'N/A'}")
                print(f"Homepage: {author['homepage']}")
                print(f"Citations: {author['citations'] or 'N/A'}")
                print(f"H-index: {author['h_index'] or 'N/A'}")
                print("-" * 30)
        else:
            print("✗ No authors found with homepage data")
            
        # Check total authors count
        all_authors = await db_client.select("authors", columns="COUNT(*) as total")
        total_authors = all_authors[0]['total'] if all_authors else 0
        
        # Check authors with homepage
        homepage_authors = await db_client.select(
            "authors", 
            columns="COUNT(*) as with_homepage",
            filters={"homepage__isnull": False}
        )
        authors_with_homepage_count = homepage_authors[0]['with_homepage'] if homepage_authors else 0
        
        print(f"\nDatabase Summary:")
        print(f"Total authors: {total_authors}")
        print(f"Authors with homepage: {authors_with_homepage_count}")
        
        if total_authors > 0:
            percentage = (authors_with_homepage_count / total_authors) * 100
            print(f"Homepage coverage: {percentage:.1f}%")
            
    except Exception as e:
        print(f"✗ Database check failed: {e}")
    
    print("\n" + "=" * 70)
    print("Homepage fix test completed!")

if __name__ == "__main__":
    asyncio.run(test_homepage_fix())
