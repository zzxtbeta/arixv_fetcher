import asyncio
import os
from src.db.database import DatabaseManager

async def check_authors():
    """Check authors in database"""
    db_uri = os.getenv("DATABASE_URL")
    await DatabaseManager.initialize(db_uri)
    pool = await DatabaseManager.get_pool()
    
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT id, author_name_en, email, orcid, citations, h_index FROM authors ORDER BY id')
            rows = await cur.fetchall()
            
            print('Authors in database:')
            for row in rows:
                print(f'ID: {row[0]}, Name: {row[1]}, Email: {row[2]}, ORCID: {row[3]}, Citations: {row[4]}, H-index: {row[5]}')
            
            print(f'\nTotal authors: {len(rows)}')
            
            # Check for duplicate names
            await cur.execute('SELECT author_name_en, COUNT(*) as count FROM authors GROUP BY author_name_en HAVING COUNT(*) > 1')
            duplicates = await cur.fetchall()
            
            if duplicates:
                print('\nDuplicate author names:')
                for dup in duplicates:
                    print(f'{dup[0]}: {dup[1]} times')
            else:
                print('\nNo duplicate author names found!')

if __name__ == "__main__":
    asyncio.run(check_authors())