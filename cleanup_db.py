import asyncio
import os
from src.db.database import DatabaseManager

async def cleanup_database():
    """Clean up duplicate data from database"""
    db_uri = os.getenv("DATABASE_URL")
    await DatabaseManager.initialize(db_uri)
    pool = await DatabaseManager.get_pool()
    
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            # Delete in correct order due to foreign key constraints
            await cur.execute('DELETE FROM author_paper')
            await cur.execute('DELETE FROM paper_category')
            await cur.execute('DELETE FROM author_affiliation')
            await cur.execute('DELETE FROM authors')
            await cur.execute('DELETE FROM papers')
            print('Database cleaned successfully')

if __name__ == "__main__":
    asyncio.run(cleanup_database())