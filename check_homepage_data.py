#!/usr/bin/env python3
"""
Script to check if homepage data was successfully extracted and stored in the database
"""

import asyncio
import os
from dotenv import load_dotenv
from src.db.postgres_client import PostgreSQLClient

async def check_homepage_data():
    """Check for homepage data in the authors table"""
    
    # Load environment variables
    load_dotenv()
    
    # Initialize database client
    db_client = PostgreSQLClient()
    
    try:
        print("Checking homepage data in authors table...")
        print("=" * 60)
        
        # Query for authors with homepage data
        query = """
        SELECT 
            author_name_en,
            email,
            homepage,
            citations,
            h_index,
            created_at
        FROM authors 
        WHERE homepage IS NOT NULL 
        ORDER BY created_at DESC 
        LIMIT 10
        """
        
        results = await db_client.select("authors", 
                                         columns="author_name_en, email, homepage, citations, h_index",
                                         filters={"homepage__isnull": False},
                                         limit=10)
        
        if results:
            print(f"Found {len(results)} authors with homepage data:")
            print("-" * 60)
            
            for author in results:
                print(f"Name: {author['author_name_en']}")
                print(f"Email: {author['email'] or 'N/A'}")
                print(f"Homepage: {author['homepage']}")
                print(f"Citations: {author['citations'] or 'N/A'}")
                print(f"H-index: {author['h_index'] or 'N/A'}")
                print(f"Created: {author['created_at']}")
                print("-" * 40)
        else:
            print("No authors found with homepage data.")
            
        # Also check total authors count
        all_authors = await db_client.select("authors", columns="COUNT(*) as total")
        total_authors = all_authors[0]['total'] if all_authors else 0
        
        print(f"\nTotal authors in database: {total_authors}")
        
        # Check authors with any non-null homepage
        homepage_authors = await db_client.select("authors", 
                                                 columns="COUNT(*) as with_homepage",
                                                 filters={"homepage__isnull": False})
        authors_with_homepage = homepage_authors[0]['with_homepage'] if homepage_authors else 0
        
        print(f"Authors with homepage data: {authors_with_homepage}")
        
        if total_authors > 0:
            percentage = (authors_with_homepage / total_authors) * 100
            print(f"Homepage coverage: {percentage:.1f}%")
            
    except Exception as e:
        print(f"Error checking homepage data: {e}")
        
    finally:
        print("\n" + "=" * 60)
        print("Homepage data check completed!")

if __name__ == "__main__":
    asyncio.run(check_homepage_data())
