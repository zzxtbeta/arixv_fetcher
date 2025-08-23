#!/usr/bin/env python3
"""
Test email extraction with a single paper.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from agent.data_graph import process_single_paper
from agent.utils import search_papers_by_window

async def test_single_paper_email():
    """Test email extraction with a single paper."""
    
    print("Fetching a recent paper from arXiv...")
    
    # Get one recent paper
    papers = search_papers_by_window(
        categories=["cs.AI", "cs.LG", "cs.CV", "cs.CL"],
        days=7,
        max_results=5
    )
    
    if not papers:
        print("No papers found.")
        return
    
    paper = papers[0]
    print(f"Testing paper: {paper.get('title', 'Unknown')[:80]}...")
    print(f"Authors: {paper.get('authors', [])}")
    print(f"PDF URL: {paper.get('pdf_url')}")
    
    # Test the process_single_paper function directly
    try:
        result = await process_single_paper({"paper": paper})
        processed_papers = result.get("papers", [])
        
        if not processed_papers:
            print("❌ No papers returned from processing")
            return
        
        processed_paper = processed_papers[0]
        author_affiliations = processed_paper.get("author_affiliations", [])
        
        print(f"\nProcessing results:")
        print(f"Number of authors processed: {len(author_affiliations)}")
        
        emails_found = 0
        for i, author_info in enumerate(author_affiliations):
            name = author_info.get("name")
            email = author_info.get("email")
            affiliations = author_info.get("affiliations", [])
            
            print(f"\nAuthor {i+1}: {name}")
            if email:
                print(f"  ✅ Email: {email}")
                emails_found += 1
            else:
                print(f"  ❌ Email: Not found")
            
            if affiliations:
                print(f"  🏢 Affiliations: {', '.join(affiliations)}")
            else:
                print(f"  🏢 Affiliations: None")
        
        print(f"\n📊 Summary: {emails_found}/{len(author_affiliations)} authors have emails")
        
        if emails_found > 0:
            print("🎉 Email extraction test PASSED!")
        else:
            print("⚠️ No emails found (this may be normal if the PDF doesn't contain email addresses)")
        
        return emails_found > 0
        
    except Exception as e:
        print(f"❌ Error processing paper: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_single_paper_email())
    if success:
        print("\n✅ Test completed successfully!")
    else:
        print("\n⚠️ Test completed but no emails were extracted.")