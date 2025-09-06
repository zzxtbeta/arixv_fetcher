import asyncio
import os
from dotenv import load_dotenv
from src.agent.utils import search_person_role_with_tavily

# Load environment variables from .env file
load_dotenv()

async def debug_role_supplement():
    """Debug Role Field Supplement for record 714 (Song Han at NVIDIA)"""
    
    # Record 714 details
    author_name = "Song Han"
    affiliation_name = "NVIDIA"
    
    print(f"=== Debugging Role Field Supplement ===")
    print(f"Author: {author_name}")
    print(f"Affiliation: {affiliation_name}")
    print(f"Record ID: 714")
    print("\n" + "="*50 + "\n")
    
    # Call the role search function
    try:
        result = await search_person_role_with_tavily(author_name, affiliation_name)
        
        if result:
            print(f"Search successful: {result.get('search_successful')}")
            print(f"Query used: {result.get('query')}")
            print(f"Extracted role: {result.get('extracted_role')}")
            print(f"Error: {result.get('error')}")
            
            # The detailed debug logs will be printed by the function itself
            
        else:
            print("No result returned from search_person_role_with_tavily")
            
    except Exception as e:
        print(f"Error during role search: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(debug_role_supplement())