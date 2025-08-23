#!/usr/bin/env python3

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

# Fix for Windows event loop compatibility
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def check_database_content():
    """Check what data exists in the database."""
    
    from src.db.database import DatabaseManager
    
    db_uri = os.getenv("DATABASE_URL")
    if not db_uri:
        logger.error("DATABASE_URL not set")
        return False
    
    try:
        await DatabaseManager.initialize(db_uri)
        pool = await DatabaseManager.get_pool()
        
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # Check papers table
                await cur.execute("SELECT COUNT(*) FROM papers")
                papers_count = (await cur.fetchone())[0]
                logger.info(f"Total papers in database: {papers_count}")
                
                # Check recent papers (last 7 days)
                await cur.execute(
                    "SELECT COUNT(*) FROM papers WHERE published >= %s",
                    (datetime.now(timezone.utc) - timedelta(days=7),)
                )
                recent_papers = (await cur.fetchone())[0]
                logger.info(f"Papers from last 7 days: {recent_papers}")
                
                # Check authors table
                await cur.execute("SELECT COUNT(*) FROM authors")
                authors_count = (await cur.fetchone())[0]
                logger.info(f"Total authors in database: {authors_count}")
                
                # Check affiliations table
                await cur.execute("SELECT COUNT(*) FROM affiliations")
                affiliations_count = (await cur.fetchone())[0]
                logger.info(f"Total affiliations in database: {affiliations_count}")
                
                # Show some recent papers
                await cur.execute(
                    "SELECT paper_title, published, arxiv_entry FROM papers ORDER BY published DESC LIMIT 5"
                )
                recent_papers_data = await cur.fetchall()
                
                if recent_papers_data:
                    logger.info("Recent papers:")
                    for title, published, arxiv_entry in recent_papers_data:
                        logger.info(f"  - {title[:60]}... (published: {published}, arxiv: {arxiv_entry})")
                else:
                    logger.info("No papers found in database")
                
                return True
                
    except Exception as e:
        logger.error(f"Error checking database: {str(e)}")
        return False

if __name__ == "__main__":
    success = asyncio.run(check_database_content())
    exit(0 if success else 1)