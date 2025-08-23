#!/usr/bin/env python3
"""
Check if emails are being extracted and stored in the database.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from db.database import DatabaseManager

async def check_emails():
    """Check emails in the database."""
    
    db = DatabaseManager()
    
    async with db.get_connection() as conn:
        async with conn.cursor() as cur:
            # Check total authors
            await cur.execute("SELECT COUNT(*) FROM authors")
            total_authors = (await cur.fetchone())[0]
            
            # Check authors with emails
            await cur.execute("SELECT COUNT(*) FROM authors WHERE email IS NOT NULL AND email != ''")
            authors_with_email = (await cur.fetchone())[0]
            
            # Get some examples
            await cur.execute(
                "SELECT author_name_en, email FROM authors WHERE email IS NOT NULL AND email != '' LIMIT 10"
            )
            examples = await cur.fetchall()
            
            print(f"Total authors: {total_authors}")
            print(f"Authors with email: {authors_with_email}")
            print(f"Percentage: {(authors_with_email/total_authors*100):.1f}%" if total_authors > 0 else "N/A")
            
            if examples:
                print("\nExamples of authors with emails:")
                for name, email in examples:
                    print(f"  {name}: {email}")
            else:
                print("\nNo authors with emails found.")
                
            # Check recent papers and their author affiliations data
            await cur.execute(
                "SELECT id, paper_title FROM papers ORDER BY id DESC LIMIT 3"
            )
            recent_papers = await cur.fetchall()
            
            print("\nChecking recent papers for author affiliation data...")
            for paper_id, title in recent_papers:
                print(f"\nPaper: {title[:50]}...")
                await cur.execute(
                    """
                    SELECT a.author_name_en, a.email 
                    FROM authors a 
                    JOIN author_paper ap ON a.id = ap.author_id 
                    WHERE ap.paper_id = %s
                    ORDER BY ap.author_order
                    """,
                    (paper_id,)
                )
                paper_authors = await cur.fetchall()
                for author_name, email in paper_authors:
                    print(f"  {author_name}: {email if email else 'No email'}")

if __name__ == "__main__":
    asyncio.run(check_emails())