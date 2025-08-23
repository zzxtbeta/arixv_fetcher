#!/usr/bin/env python3
"""
Test email extraction with fresh arXiv papers.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from agent.utils import search_papers_by_window
from agent.data_graph import build_data_processing_graph
from db.database import DatabaseManager

async def test_fresh_papers():
    """Test email extraction with fresh papers from arXiv."""
    
    print("Fetching fresh papers from arXiv...")
    
    # Get papers from the last 2 days
    categories = ["cs.CV", "cs.AI", "cs.LG"]
    
    papers = search_papers_by_window(
        categories=categories,
        days=2,  # Last 2 days
        max_results=3  # Just test with 3 papers
    )
    
    if not papers:
        print("No papers found for testing.")
        return
    
    print(f"Found {len(papers)} papers to test")
    
    # Process papers through the graph
    graph = await build_data_processing_graph()
    
    for i, paper in enumerate(papers[:2]):  # Test with first 2 papers
        print(f"\n--- Testing Paper {i+1}: {paper.get('title', 'Unknown')[:60]}... ---")
        
        try:
            # Run the graph
            result = await graph.ainvoke(
                {"papers": [paper]},
                config={"configurable": {"thread_id": f"test-{i}"}}
            )
            
            print(f"Graph completed with status: {result.get('status', 'unknown')}")
            
            # Check if emails were extracted
            processed_papers = result.get("papers", [])
            if processed_papers:
                paper_data = processed_papers[0]
                author_affiliations = paper_data.get("author_affiliations", [])
                
                emails_found = 0
                print(f"Authors processed: {len(author_affiliations)}")
                
                for author_info in author_affiliations:
                    name = author_info.get("name")
                    email = author_info.get("email")
                    affiliations = author_info.get("affiliations", [])
                    
                    print(f"  {name}:")
                    if email:
                        print(f"    Email: {email}")
                        emails_found += 1
                    else:
                        print(f"    Email: Not found")
                    
                    if affiliations:
                        print(f"    Affiliations: {', '.join(affiliations)}")
                    else:
                        print(f"    Affiliations: None")
                
                print(f"Total emails found: {emails_found}/{len(author_affiliations)}")
                
                if emails_found > 0:
                    print("✅ Email extraction successful!")
                else:
                    print("⚠️ No emails found (may be normal)")
            
        except Exception as e:
            print(f"❌ Error processing paper: {e}")
    
    # Check database after processing
    print("\n--- Checking database for new emails ---")
    db = DatabaseManager()
    
    async with db.get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM authors WHERE email IS NOT NULL AND email != ''"
            )
            total_with_email = (await cur.fetchone())[0]
            
            await cur.execute(
                "SELECT author_name_en, email FROM authors WHERE email IS NOT NULL AND email != '' ORDER BY id DESC LIMIT 5"
            )
            recent_emails = await cur.fetchall()
            
            print(f"Total authors with emails in database: {total_with_email}")
            print("Most recent authors with emails:")
            for name, email in recent_emails:
                print(f"  {name}: {email}")

if __name__ == "__main__":
    asyncio.run(test_fresh_papers())