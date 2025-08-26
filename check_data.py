import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add the src directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from db.supabase_client import supabase_client

def check_data():
    try:
        print("Checking database using supabase_client...")
        
        # Check papers count
        count = supabase_client.count("papers")
        print(f"Total papers in database: {count}")
        
        # Get latest papers
        latest = supabase_client.select(
            table="papers",
            columns="id, paper_title, published, arxiv_entry",
            order_by=("published", False),
            limit=5
        )
        
        print(f"\nLatest 5 papers:")
        if latest:
            for paper in latest:
                title = paper.get('paper_title', 'No title')[:50]
                print(f"  ID: {paper.get('id')}, Title: {title}..., Published: {paper.get('published')}")
        else:
            print("  No papers found")
            
        # Test the specific API endpoint logic
        print("\nTesting latest-papers API logic...")
        papers = supabase_client.select(
            table="papers",
            columns="id, paper_title, published, pdf_source, arxiv_entry",
            order_by=("published", False),
            limit=20,
            offset=0
        )
        
        print(f"API test - Found {len(papers) if papers else 0} papers")
        if papers:
            print(f"First paper: {papers[0].get('paper_title', 'No title')[:50]}...")
                
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_data()